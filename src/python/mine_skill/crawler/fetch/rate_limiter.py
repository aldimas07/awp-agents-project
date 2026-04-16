"""Rate limiter utilities for per-platform pacing and retry backoff."""

import asyncio
import json
import time
from pathlib import Path

_CONFIG_PATH = Path(__file__).resolve().parent.parent.parent / "references" / "rate_limits.json"
_DEFAULT_RPM = 30
_DEFAULT_BACKOFF = [2, 5, 10]


class RateLimiter:
    """Async rate limiter using per-platform minimum intervals."""

    def __init__(self) -> None:
        self._config: dict = {}
        if _CONFIG_PATH.exists():
            with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
                self._config = json.load(f)
        self._locks: dict[str, asyncio.Lock] = {}
        self._last_request: dict[str, float] = {}

    def _get_rpm(self, platform: str) -> int:
        """Return requests_per_minute for a platform, falling back to defaults."""
        if platform in self._config:
            return self._config[platform].get("requests_per_minute", _DEFAULT_RPM)
        return self._config.get("defaults", {}).get("requests_per_minute", _DEFAULT_RPM)

    def get_backoff_seconds(self, platform: str, attempt: int) -> float:
        """Return retry backoff seconds for a platform and zero-based attempt."""
        values = self._config.get(platform, {}).get(
            "backoff_seconds",
            self._config.get("defaults", {}).get("backoff_seconds", _DEFAULT_BACKOFF),
        )
        if not values:
            return 0.0
        index = min(max(attempt, 0), len(values) - 1)
        return float(values[index])

    def _get_lock(self, platform: str) -> asyncio.Lock:
        """Return (or create) the asyncio.Lock for a platform."""
        return self._locks.setdefault(platform, asyncio.Lock())

    async def acquire(self, platform: str) -> None:
        """Wait until the next request is allowed for *platform*."""
        lock = self._get_lock(platform)
        async with lock:
            interval = 60.0 / self._get_rpm(platform)
            now = time.monotonic()
            last = self._last_request.get(platform, 0.0)
            wait = interval - (now - last)
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_request[platform] = time.monotonic()
