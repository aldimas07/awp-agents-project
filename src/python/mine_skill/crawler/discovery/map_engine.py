from __future__ import annotations

from dataclasses import dataclass, field

from crawler.discovery.contracts import DiscoveryCandidate, DiscoveryRecord


@dataclass(slots=True)
class MapResult:
    accepted: list[DiscoveryCandidate]
    rejected: list[DiscoveryCandidate]
    exhausted: bool = True
    next_seeds: list[DiscoveryRecord] = field(default_factory=list)
