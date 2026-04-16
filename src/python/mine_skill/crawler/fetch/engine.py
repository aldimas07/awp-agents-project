from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from .http_backend import _decode_response_text, _resolve_text_encoding
from .backend_router import resolve_backend
from .browser_pool import BrowserPool
from .circuit_breaker import CircuitBreaker
from .error_classifier import FetchError, classify, classify_content
from .models import FetchTiming, RawFetchResult
from .rate_limiter import RateLimiter
from .session_manager import SessionManager
from .wait_strategy import apply_wait_strategy

logger = logging.getLogger(__name__)

_DEFAULT_HTTP_HEADERS = {
    "User-Agent": "mine-runtime/0.1 (contact: crawler@example.com)",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


class FetchEngine:
    """Unified fetch engine integrating browser pool, wait strategies, backend routing, and session management."""

    def __init__(
        self,
        session_root: Path,
        *,
        max_retries: int = 2,
        http_timeout: float = 30.0,
    ) -> None:
        self._session_root = session_root
        self._max_retries = max_retries
        self._http_timeout = http_timeout
        self._pool = BrowserPool(session_root)
        self._session_mgr = SessionManager(session_root)
        self._rate_limiter = RateLimiter()
        self._circuit_breaker = CircuitBreaker()
        self._started = False

    @property
    def session_manager(self) -> SessionManager:
        return self._session_mgr

    @property
    def browser_pool(self) -> BrowserPool:
        return self._pool

    async def start(self) -> None:
        if not self._started:
            await self._pool.start()
            self._started = True

    async def close(self) -> None:
        if self._started:
            await self._pool.close()
            self._started = False

    async def __aenter__(self) -> FetchEngine:
        await self.start()
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.close()

    async def fetch(
        self,
        url: str,
        platform: str,
        resource_type: str | None = None,
        *,
        requires_auth: bool = False,
        override_backend: str | None = None,
        preferred_backend: str | None = None,
        fallback_chain: list[str] | None = None,
        api_fetcher: Any | None = None,
        api_kwargs: dict | None = None,
    ) -> RawFetchResult:
        """Fetch a URL with automatic backend selection, wait strategies, and retry/escalation."""
        circuit_error = self._circuit_breaker.open_error(platform)
        if circuit_error is not None:
            err = RuntimeError(circuit_error.message)
            err.fetch_error = circuit_error  # type: ignore[attr-defined]
            raise err

        if override_backend:
            initial_backend = override_backend
            fallback_chain: list[str] = []
        elif preferred_backend is not None:
            initial_backend = preferred_backend
            fallback_chain = list(fallback_chain or [])
        else:
            initial_backend, fallback_chain = resolve_backend(platform, resource_type, requires_auth)

        backends_to_try = [initial_backend] + fallback_chain
        last_error: Exception | None = None
        last_fetch_error: FetchError | None = None
        consecutive_failures = 0

        for attempt, backend in enumerate(backends_to_try):
            if consecutive_failures >= self._max_retries:
                break
            try:
                # Enforce per-platform rate limit before each request
                await self._rate_limiter.acquire(platform)

                result = await self._fetch_with_backend(
                    url=url,
                    platform=platform,
                    resource_type=resource_type or "",
                    backend=backend,
                    api_fetcher=api_fetcher,
                    api_kwargs=api_kwargs,
                )

                content_error = None
                if "html" in result.content_type.lower():
                    content_error = classify_content(result.html, result.final_url)
                if content_error:
                    err = RuntimeError(content_error.message)
                    err.fetch_error = content_error  # type: ignore[attr-defined]
                    raise err
                consecutive_failures = 0
                self._circuit_breaker.record_success(platform)
                return result
            except Exception as exc:
                last_error = exc
                consecutive_failures += 1
                last_fetch_error = getattr(exc, "fetch_error", None) or classify(exc)
                logger.warning(
                    "Fetch failed with backend=%s for %s (attempt %d/%d): [%s] %s",
                    backend, url, attempt + 1, len(backends_to_try),
                    last_fetch_error.error_code if last_fetch_error else "UNKNOWN",
                    exc,
                )
                if last_fetch_error and not last_fetch_error.retryable:
                    break
                if last_fetch_error and last_fetch_error.retryable:
                    backoff_seconds = self._rate_limiter.get_backoff_seconds(platform, attempt)
                    await self._circuit_breaker.record_failure_safe(platform, last_fetch_error, backoff_seconds)
                    if backoff_seconds > 0:
                        logger.info(
                            "Backing off %.1fs for %s after %s",
                            backoff_seconds,
                            url,
                            last_fetch_error.error_code,
                        )
                        await asyncio.sleep(backoff_seconds)
                    if not self._circuit_breaker.allow_request(platform):
                        break
                continue

        err = RuntimeError(
            f"All backends exhausted for {url} (tried {backends_to_try})"
        )
        err.fetch_error = last_fetch_error  # type: ignore[attr-defined]
        raise err from last_error

    async def _fetch_with_backend(
        self,
        *,
        url: str,
        platform: str,
        resource_type: str,
        backend: str,
        api_fetcher: Any | None = None,
        api_kwargs: dict | None = None,
    ) -> RawFetchResult:
        start_ms = _now_ms()

        if backend == "http":
            return await self._fetch_http(url, start_ms)
        elif backend == "api":
            return await self._fetch_api(url, api_fetcher, api_kwargs, start_ms)
        elif backend in ("playwright", "camoufox"):
            return await self._fetch_browser(url, platform, resource_type, backend, start_ms)
        else:
            raise ValueError(f"Unsupported backend: {backend!r}")

    async def _fetch_http(self, url: str, start_ms: int) -> RawFetchResult:
        nav_start = _now_ms()
        async with httpx.AsyncClient(
            timeout=self._http_timeout,
            follow_redirects=True,
            headers=_DEFAULT_HTTP_HEADERS,
        ) as client:
            response = await client.get(url)
            response.raise_for_status()

        nav_ms = _now_ms() - nav_start
        headers = dict(response.headers)
        content_type = headers.get("content-type", "")
        encoding = _resolve_text_encoding(response)
        json_data = None
        if "json" in content_type:
            try:
                json_data = response.json()
            except Exception:
                pass

        return RawFetchResult(
            url=url,
            final_url=str(response.url),
            backend="http",
            fetch_time=datetime.now(UTC),
            content_type=content_type,
            status_code=response.status_code,
            html=_decode_response_text(response, encoding),
            json_data=json_data,
            content_bytes=response.content,
            headers=headers,
            timing=FetchTiming(
                start_ms=start_ms,
                navigation_ms=nav_ms,
                wait_strategy_ms=0,
                total_ms=_now_ms() - start_ms,
            ),
        )

    async def _fetch_api(
        self,
        url: str,
        api_fetcher: Any | None,
        api_kwargs: dict | None,
        start_ms: int,
    ) -> RawFetchResult:
        if api_fetcher is None:
            raise ValueError("api backend requires an api_fetcher callable")
        nav_start = _now_ms()
        kwargs = api_kwargs or {}
        if asyncio.iscoroutinefunction(api_fetcher):
            data = await api_fetcher(url, **kwargs)
        else:
            data = api_fetcher(url, **kwargs)
        nav_ms = _now_ms() - nav_start
        known_keys = {
            "url",
            "status_code",
            "content_type",
            "json_data",
            "headers",
            "text",
            "html",
            "content_bytes",
            "screenshot_bytes",
            "backend",
        }

        return RawFetchResult(
            url=url,
            final_url=data.get("url", url),
            backend="api",
            fetch_time=datetime.now(UTC),
            content_type=data.get("content_type", ""),
            status_code=data.get("status_code", 200),
            html=data.get("text") or data.get("html"),
            json_data=data.get("json_data"),
            content_bytes=data.get("content_bytes"),
            headers=data.get("headers", {}),
            extra_data={key: value for key, value in data.items() if key not in known_keys},
            timing=FetchTiming(
                start_ms=start_ms,
                navigation_ms=nav_ms,
                wait_strategy_ms=0,
                total_ms=_now_ms() - start_ms,
            ),
        )

    async def _fetch_browser(
        self,
        url: str,
        platform: str,
        resource_type: str,
        backend: str,
        start_ms: int,
    ) -> RawFetchResult:
        if not self._started:
            await self.start()

        context = await self._pool.acquire_context(platform, backend)
        page = None
        try:
            page = await context.new_page()
            twister_payloads: list[dict[str, Any]] = []

            def _handle_response(response: Any) -> None:
                if "twisterDimensionSlotsDefault" in response.url:
                    twister_payloads.append({"url": response.url, "content_type": response.headers.get("content-type", ""), "_response": response})  # type: ignore[dict-item]

            page.on("response", _handle_response)
            nav_start = _now_ms()

            try:
                await page.goto(url, wait_until="domcontentloaded")
            except Exception as exc:
                logger.warning("Navigation to %s failed: %s", url, exc)
                raise

            nav_ms = _now_ms() - nav_start

            # Apply wait strategy
            wait_name, wait_ms = await apply_wait_strategy(page, platform, resource_type)

            html = await page.content()
            captured_twister_payloads: list[dict[str, str]] = []
            for payload in twister_payloads:
                response = payload.pop("_response", None)
                if response is None:
                    continue
                try:
                    body = await response.text()
                except Exception:
                    continue
                if not body.strip():
                    continue
                captured_twister_payloads.append({
                    "url": payload.get("url", ""),
                    "content_type": payload.get("content_type", ""),
                    "body": body,
                })
            if captured_twister_payloads:
                html += self._embed_json_script("amazon-twister-responses", captured_twister_payloads)
            final_url = page.url
            screenshot = await page.screenshot(type="png")

            # Check if cookies were updated
            cookies_updated = await self._session_mgr.refresh_session(platform, context)

            total_ms = _now_ms() - start_ms

            return RawFetchResult(
                url=url,
                final_url=final_url,
                backend=backend,  # type: ignore[arg-type]
                fetch_time=datetime.now(UTC),
                content_type="text/html; charset=utf-8",
                status_code=200,
                html=html,
                content_bytes=html.encode("utf-8"),
                screenshot=screenshot,
                cookies_updated=cookies_updated,
                wait_strategy_used=wait_name,
                timing=FetchTiming(
                    start_ms=start_ms,
                    navigation_ms=nav_ms,
                    wait_strategy_ms=wait_ms,
                    total_ms=total_ms,
                ),
            )
        finally:
            if page is not None:
                try:
                    await page.close()
                except Exception:
                    pass
            await self._pool.release_context(platform, context, backend)

    @staticmethod
    def _embed_json_script(data_key: str, payload: Any) -> str:
        json_text = json.dumps(payload, ensure_ascii=False).replace("</script", "<\\/script")
        return f'\n<script type="application/json" data-{data_key}="true">{json_text}</script>'


def _now_ms() -> int:
    return int(time.monotonic() * 1000)
