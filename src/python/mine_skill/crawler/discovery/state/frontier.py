from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class FrontierStatus(str, Enum):
    QUEUED = "queued"
    LEASED = "leased"
    RETRY_WAIT = "retry_wait"
    DONE = "done"
    DEAD = "dead"


@dataclass(slots=True)
class FrontierEntry:
    frontier_id: str
    job_id: str
    url_key: str
    canonical_url: str | None
    adapter: str
    entity_type: str | None
    depth: int
    priority: float
    discovered_from: dict[str, Any] | None
    discovery_reason: str
    status: FrontierStatus = FrontierStatus.QUEUED
    attempt: int = 0
    not_before: str | None = None
    last_error: dict[str, Any] | None = None
