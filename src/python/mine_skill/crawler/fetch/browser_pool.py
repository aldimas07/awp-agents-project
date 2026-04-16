from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

try:
    from playwright.async_api import async_playwright, Browser, BrowserContext, Playwright
except ModuleNotFoundError:
    async_playwright = None  # type: ignore[assignment,misc]
    Browser = None  # type: ignore[assignment,misc]
    BrowserContext = None  # type: ignore[assignment,misc]
    Playwright = None  # type: ignore[assignment,misc]


class BrowserPool:
    """Manages a pool of browser instances and per-platform contexts.

    Avoids cold-start costs by keeping browsers alive and reusing contexts
    with the correct storage_state for each platform.
    """

    def __init__(self, session_root: Path, max_contexts_per_browser: int = 5) -> None:
        self._session_root = session_root
        self._max_contexts = max_contexts_per_browser
        self._pw: Any | None = None
        self._browsers: dict[str, Any] = {}  # backend_type -> Browser
        self._contexts: dict[str, list[Any]] = {}  # platform -> [BrowserContext]
        self._available: dict[str, asyncio.Queue] = {}  # platform -> Queue of available contexts
        self._lock = asyncio.Lock()
        self._started = False

    async def start(self) -> None:
        if self._started:
            return
        if async_playwright is None:
            raise RuntimeError("playwright is not installed")
        self._pw = await async_playwright().start()
        self._started = True
        logger.info("BrowserPool started")

    async def _ensure_browser(self, backend_type: str) -> Any:
        """Launch or return a cached browser for the given backend type."""
        if backend_type in self._browsers:
            return self._browsers[backend_type]
        async with self._lock:
            if backend_type in self._browsers:
                return self._browsers[backend_type]
            if backend_type == "camoufox":
                try:
                    if os.name == "nt":
                        raise RuntimeError("camoufox async backend is unstable on Windows")
                    from camoufox.async_api import AsyncCamoufox
                    browser = await AsyncCamoufox(headless=True).__aenter__()
                except Exception:
                    logger.warning("camoufox not available, falling back to chromium")
                    browser = await self._pw.chromium.launch(headless=True)
            else:
                browser = await self._pw.chromium.launch(headless=True)
            self._browsers[backend_type] = browser
            return browser

    def _storage_state_path(self, platform: str) -> Path:
        return self._session_root / f"{platform}.json"

    def _load_storage_state(self, platform: str) -> dict | None:
        path = self._storage_state_path(platform)
        if path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                logger.warning("Failed to load storage_state for %s", platform)
        return None

    async def _save_storage_state(self, platform: str, context: Any) -> None:
        try:
            state = await context.storage_state()
            path = self._storage_state_path(platform)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            logger.warning("Failed to save storage_state for %s", platform)

    async def _is_context_alive(self, ctx: Any) -> bool:
        """Check if a pooled context is still usable."""
        try:
            # A lightweight probe — accessing pages is synchronous and cheap
            _ = ctx.pages
            return True
        except Exception:
            return False

    async def acquire_context(self, platform: str, backend_type: str = "playwright") -> Any:
        """Get a browser context for the given platform. Reuses pooled contexts when available."""
        if not self._started:
            await self.start()

        key = f"{platform}:{backend_type}"

        while key in self._available and not self._available[key].empty():
            ctx = self._available[key].get_nowait()
            if await self._is_context_alive(ctx):
                logger.debug("Reusing pooled context for %s", key)
                return ctx
            logger.warning("Discarding dead pooled context for %s", key)
            if key in self._contexts:
                try:
                    self._contexts[key].remove(ctx)
                except ValueError:
                    pass

        browser = await self._ensure_browser(backend_type)
        storage_state = self._load_storage_state(platform)
        ctx = await browser.new_context(storage_state=storage_state)

        async with self._lock:
            if key not in self._contexts:
                self._contexts[key] = []
                self._available[key] = asyncio.Queue()
            self._contexts[key].append(ctx)
        logger.debug("Created new context for %s (total: %d)", key, len(self._contexts[key]))
        return ctx

    async def release_context(self, platform: str, context: Any, backend_type: str = "playwright", *, save_state: bool = True) -> None:
        """Return a context to the pool. Saves storage_state if requested."""
        key = f"{platform}:{backend_type}"

        if save_state:
            await self._save_storage_state(platform, context)

        if key in self._available and self._available[key].qsize() < self._max_contexts:
            # Clear pages before returning to pool
            pages = context.pages
            for page in pages:
                try:
                    await page.close()
                except Exception:
                    pass
            self._available[key].put_nowait(context)
            logger.debug("Returned context to pool for %s", key)
        else:
            try:
                await context.close()
            except Exception:
                pass
            if key in self._contexts:
                try:
                    self._contexts[key].remove(context)
                except ValueError:
                    pass

    async def close(self) -> None:
        """Shut down all browsers and contexts."""
        for key, contexts in self._contexts.items():
            for ctx in contexts:
                try:
                    await ctx.close()
                except Exception:
                    pass
        self._contexts.clear()
        self._available.clear()

        for name, browser in self._browsers.items():
            try:
                await browser.close()
            except Exception:
                pass
        self._browsers.clear()

        if self._pw is not None:
            try:
                await self._pw.stop()
            except Exception:
                pass
            self._pw = None
        self._started = False
        logger.info("BrowserPool closed")
