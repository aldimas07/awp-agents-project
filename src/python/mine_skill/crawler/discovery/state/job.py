from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal


@dataclass(frozen=True, slots=True)
class JobSpec:
    job_id: str
    mode: Literal["map", "crawl"]
    adapter: str
    seed_set: list[str]
    limits: dict[str, Any]
    session_ref: str | None
    created_at: str
