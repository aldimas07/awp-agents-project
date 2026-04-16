"""Per-platform async rate limiter using token bucket algorithm."""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[2]
_RATE_LIMITS_PATH = _ROOT / "references" / "rate_limits.json"


def load_rate_limit_policy(platform: str) -> dict[str, Any]:
    config = _load_rate_limits()
    defaults = config.get("defaults", {})
    platform_config = config.get(platform, {})
    return {
        "requests_per_minute": float(platform_config.get("requests_per_minute", defaults.get("requests_per_minute", 30))),
        "backoff_seconds": list(platform_config.get("backoff_seconds", defaults.get("backoff_seconds", [2, 5, 10]))),
        "max_retries": int(platform_config.get("max_retries", defaults.get("max_retries", 3))),
    }


class TokenBucketThrottle:
    """Async-friendly token bucket rate limiter.

    Parameters
    ----------
    requests_per_minute:
        Sustained request rate.  The bucket refills at this rate and allows
        short bursts of up to 5 seconds worth of tokens.
    """

    def __init__(self, requests_per_minute: float = 30.0) -> None:
        self._rate = requests_per_minute / 60.0  # tokens per second
        self._capacity = max(1.0, requests_per_minute / 60.0 * 5)  # 5-second burst
        self._tokens = self._capacity
        self._last_refill = time.monotonic()

    async def acquire(self) -> float:
        """Wait until a token is available.  Returns wait time in seconds."""
        self._refill()
        if self._tokens >= 1.0:
            self._tokens -= 1.0
            return 0.0
        deficit = 1.0 - self._tokens
        wait = deficit / self._rate
        await asyncio.sleep(wait)
        self._refill()
        self._tokens -= 1.0
        return wait

    def _refill(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last_refill
        self._tokens = min(self._capacity, self._tokens + elapsed * self._rate)
        self._last_refill = now

    @classmethod
    def for_platform(cls, platform: str) -> TokenBucketThrottle:
        """Create throttle from ``references/rate_limits.json`` config."""
        return cls(requests_per_minute=load_rate_limit_policy(platform)["requests_per_minute"])


def _load_rate_limits() -> dict[str, Any]:
    if _RATE_LIMITS_PATH.exists():
        return json.loads(_RATE_LIMITS_PATH.read_text(encoding="utf-8"))
    return {}
