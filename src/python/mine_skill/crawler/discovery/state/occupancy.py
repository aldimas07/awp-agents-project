from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class OccupancyLease:
    lease_id: str
    job_id: str
    frontier_id: str
    worker_id: str
    leased_at: str
    expires_at: str | None = None
