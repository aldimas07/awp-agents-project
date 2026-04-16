from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class VisitRecord:
    url_key: str
    canonical_url: str
    scope_key: str
    first_seen_at: str
    last_seen_at: str
    best_depth: int
    map_state: str | None = None
    crawl_state: str | None = None
    fetch_fingerprint: str | None = None
    final_url: str | None = None
    http_status: int | None = None
    adapter_state: dict[str, Any] = field(default_factory=dict)
