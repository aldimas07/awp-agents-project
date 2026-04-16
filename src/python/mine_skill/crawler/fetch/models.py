from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from .error_classifier import FetchError


class SessionStatus(str, Enum):
    VALID = "valid"
    EXPIRED = "expired"
    MISSING = "missing"
    INVALID = "invalid"


@dataclass(frozen=True, slots=True)
class FetchTiming:
    start_ms: int
    navigation_ms: int
    wait_strategy_ms: int
    total_ms: int


@dataclass(slots=True)
class RawFetchResult:
    url: str
    final_url: str
    backend: Literal["http", "playwright", "camoufox", "api"]
    fetch_time: datetime
    content_type: str
    status_code: int
    html: str | None = None
    json_data: dict | None = None
    content_bytes: bytes | None = None
    screenshot: bytes | None = None
    headers: dict[str, str] = field(default_factory=dict)
    extra_data: dict[str, Any] = field(default_factory=dict)
    cookies_updated: bool = False
    wait_strategy_used: str = "none"
    resources_blocked: list[str] = field(default_factory=list)
    timing: FetchTiming = field(default_factory=lambda: FetchTiming(0, 0, 0, 0))
    fetch_error: FetchError | None = None

    @classmethod
    def from_legacy(cls, data: dict, *, backend: str, url: str) -> RawFetchResult:
        """Convert a dict from the old fetch backends into a RawFetchResult."""
        now = datetime.now(UTC)
        html = data.get("html") or data.get("text")
        known_keys = {
            "url",
            "status_code",
            "headers",
            "content_type",
            "text",
            "html",
            "content_bytes",
            "json_data",
            "screenshot_bytes",
            "backend",
        }
        return cls(
            url=url,
            final_url=data.get("url", url),
            backend=backend,  # type: ignore[arg-type]
            fetch_time=now,
            content_type=data.get("content_type", ""),
            status_code=data.get("status_code", 200),
            html=html,
            json_data=data.get("json_data"),
            content_bytes=data.get("content_bytes"),
            screenshot=data.get("screenshot_bytes"),
            headers=data.get("headers", {}),
            extra_data={key: value for key, value in data.items() if key not in known_keys},
        )

    def to_legacy_dict(self) -> dict:
        """Convert back to the dict format expected by PlatformAdapter.fetch_fn callers."""
        result: dict = {
            "url": self.final_url,
            "backend": self.backend,
            "content_type": self.content_type,
            "status_code": self.status_code,
            "headers": self.headers,
        }
        if self.html is not None:
            result["html"] = self.html
            result["text"] = self.html
        if self.json_data is not None:
            result["json_data"] = self.json_data
        if self.content_bytes is not None:
            result["content_bytes"] = self.content_bytes
        if self.screenshot is not None:
            result["screenshot_bytes"] = self.screenshot
        if self.extra_data:
            result.update(self.extra_data)
        return result
