"""Unified fetch interface - single entry point for all fetch operations.

This module provides a synchronous interface that wraps FetchEngine,
replacing the old orchestrator.py. All fetch operations should go through
`unified_fetch()` which handles:
- Backend selection (http/playwright/camoufox)
- BrowserPool management
- WaitStrategy application
- Session persistence
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from .browser_common import run_sync_compatible
from .engine import FetchEngine

# Global engine instance for sync interface
_engine: FetchEngine | None = None
_engine_session_root: Path | None = None
import threading as _threading
_engine_thread_lock = _threading.Lock()


async def _get_or_create_engine(session_root: Path) -> FetchEngine:
    """Get or create a FetchEngine instance for the given session root."""
    global _engine, _engine_session_root

    # Use threading lock since asyncio.run() creates new loops per call
    with _engine_thread_lock:
        if _engine is not None and _engine_session_root == session_root:
            return _engine

        old_engine = _engine
        _engine = FetchEngine(session_root)
        _engine_session_root = session_root

    # Close old engine outside the lock to avoid blocking
    if old_engine is not None:
        try:
            await old_engine.close()
        except Exception:
            pass

    return _engine


async def _unified_fetch_async(
    url: str,
    platform: str,
    resource_type: str | None,
    backend: str,
    storage_state_path: str | None,
    api_fetcher: Any | None,
    api_kwargs: dict | None,
) -> dict[str, Any]:
    """Async implementation of unified fetch."""
    session_root = Path(storage_state_path).parent if storage_state_path else Path.cwd() / ".sessions"
    session_root.mkdir(parents=True, exist_ok=True)

    engine = await _get_or_create_engine(session_root)

    result = await engine.fetch(
        url=url,
        platform=platform,
        resource_type=resource_type,
        requires_auth=storage_state_path is not None,
        override_backend=backend,
        api_fetcher=api_fetcher,
        api_kwargs=api_kwargs,
    )

    return result.to_legacy_dict()


def unified_fetch(
    url: str,
    platform: str,
    resource_type: str | None = None,
    *,
    backend: str = "http",
    storage_state_path: str | None = None,
    api_fetcher: Any | None = None,
    api_kwargs: dict | None = None,
) -> dict[str, Any]:
    """
    Unified fetch interface - replaces old orchestrator.fetch_with_backend().

    Args:
        url: Target URL to fetch
        platform: Platform name (linkedin, amazon, etc.)
        resource_type: Resource type (profile, product, etc.)
        backend: Backend to use (http, playwright, camoufox, api)
        storage_state_path: Path to browser storage state (for auth)
        api_fetcher: Custom API fetcher callable for api backend
        api_kwargs: Kwargs to pass to api_fetcher

    Returns:
        Legacy-compatible dict with url, html, content_type, status_code, etc.
    """
    def run() -> dict[str, Any]:
        return asyncio.run(_unified_fetch_async(
            url=url,
            platform=platform,
            resource_type=resource_type,
            backend=backend,
            storage_state_path=storage_state_path,
            api_fetcher=api_fetcher,
            api_kwargs=api_kwargs,
        ))

    return run_sync_compatible(run)


# Backward compatibility alias
def fetch_with_backend(
    url: str,
    platform: str,
    requires_browser: bool,
    retry_count: int,
    *,
    backend: str | None = None,
    storage_state_path: str | None = None,
    timeout: float = 20.0,
) -> dict:
    """
    DEPRECATED: Use unified_fetch() instead.

    This function exists for backward compatibility with old code.
    It maps old-style parameters to the new unified_fetch interface.
    """
    # Map old-style backend selection to explicit backend
    if backend is None:
        if requires_browser:
            backend = "playwright"
        else:
            backend = "http"

    return unified_fetch(
        url=url,
        platform=platform,
        backend=backend,
        storage_state_path=storage_state_path,
    )
