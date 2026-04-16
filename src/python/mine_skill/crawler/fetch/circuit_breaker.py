from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

from .error_classifier import FetchError

_CONFIG_PATH = Path(__file__).resolve().parent.parent.parent / "references" / "rate_limits.json"
_DEFAULT_THRESHOLD = 2
_DEFAULT_COOLDOWN_SECONDS = 30.0
_TRIP_ERRORS = {
    "RATE_LIMITED",
    "AUTH_EXPIRED",
    "CAPTCHA",
    "IP_BLOCKED",
    "SERVER_ERROR",
    "NETWORK_ERROR",
}


class CircuitBreaker:
    def __init__(self) -> None:
        self._config: dict = {}
        if _CONFIG_PATH.exists():
            self._config = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
        self._states: dict[str, dict[str, float | int | str]] = {}
        self._lock = asyncio.Lock()

    def allow_request(self, platform: str) -> bool:
        state = self._states.get(platform)
        if state is None:
            return True
        if "open_until" not in state:
            return True
        open_until = float(state.get("open_until", 0.0))
        if open_until <= time.monotonic():
            self._states.pop(platform, None)
            return True
        return False

    def open_error(self, platform: str) -> FetchError | None:
        state = self._states.get(platform)
        if state is None:
            return None
        if "open_until" not in state:
            return None
        open_until = float(state.get("open_until", 0.0))
        if open_until <= time.monotonic():
            self._states.pop(platform, None)
            return None
        remaining = max(open_until - time.monotonic(), 0.0)
        return FetchError(
            error_code="CIRCUIT_OPEN",
            agent_hint="wait_and_retry",
            message=f"circuit open for {platform}, retry after {remaining:.1f}s",
            retryable=True,
        )

    def record_success(self, platform: str) -> None:
        self._states.pop(platform, None)

    def record_failure(self, platform: str, error: FetchError | None, cooldown_seconds: float) -> None:
        # Note: must be called within an async context that serialises access,
        # or explicitly wrapped with ``async with self._lock``.
        if error is None or error.error_code not in _TRIP_ERRORS:
            return
        state = self._states.setdefault(platform, {"failures": 0})
        failures = int(state.get("failures", 0)) + 1
        state["failures"] = failures
        state["last_error_code"] = error.error_code
        if failures >= self._threshold(platform):
            state["open_until"] = time.monotonic() + max(cooldown_seconds, self._cooldown(platform))

    async def record_failure_safe(self, platform: str, error: FetchError | None, cooldown_seconds: float) -> None:
        """Thread-safe version of record_failure for concurrent async callers."""
        async with self._lock:
            self.record_failure(platform, error, cooldown_seconds)

    def _threshold(self, platform: str) -> int:
        return int(
            self._config.get(platform, {}).get(
                "circuit_breaker_threshold",
                self._config.get("defaults", {}).get("circuit_breaker_threshold", _DEFAULT_THRESHOLD),
            )
        )

    def _cooldown(self, platform: str) -> float:
        return float(
            self._config.get(platform, {}).get(
                "circuit_breaker_cooldown_seconds",
                self._config.get("defaults", {}).get("circuit_breaker_cooldown_seconds", _DEFAULT_COOLDOWN_SECONDS),
            )
        )
