from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class Checkpoint:
    job_id: str
    checkpoint_id: str | None = None
    created_at: str | None = None
    frontier_cursor: str | None = None
    visited_cursor: str | None = None
    notes: tuple[str, ...] = field(default_factory=tuple)
