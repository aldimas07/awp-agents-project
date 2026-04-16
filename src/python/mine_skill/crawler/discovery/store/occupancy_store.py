from __future__ import annotations

from crawler.discovery.state.occupancy import OccupancyLease


class InMemoryOccupancyStore:
    def __init__(self) -> None:
        self.leases: dict[str, OccupancyLease] = {}

    def put(self, lease: OccupancyLease) -> OccupancyLease:
        self.leases[lease.lease_id] = lease
        return lease

    def get(self, lease_id: str) -> OccupancyLease | None:
        return self.leases.get(lease_id)

    def release_by_frontier_id(self, frontier_id: str) -> None:
        """Remove all leases for a given frontier entry."""
        to_remove = [lid for lid, lease in self.leases.items() if lease.frontier_id == frontier_id]
        for lid in to_remove:
            del self.leases[lid]

    def list(self) -> list[OccupancyLease]:
        return list(self.leases.values())
