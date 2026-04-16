from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class DiscoveryEdge:
    edge_id: str
    job_id: str
    parent_url: str
    child_url: str
    reason: str
    observed_at: str
    notes: tuple[str, ...] = field(default_factory=tuple)
