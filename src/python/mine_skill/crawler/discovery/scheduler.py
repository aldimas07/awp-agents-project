"""Discovery scheduler with rate limiting and retry."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from crawler.discovery.state.frontier import FrontierEntry, FrontierStatus
from crawler.discovery.state.occupancy import OccupancyLease
from crawler.discovery.store.frontier_store import InMemoryFrontierStore
from crawler.discovery.store.occupancy_store import InMemoryOccupancyStore
from crawler.discovery.throttle import TokenBucketThrottle, load_rate_limit_policy


def _now_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


class DiscoveryScheduler:
    def __init__(
        self,
        frontier_store: InMemoryFrontierStore | None = None,
        occupancy_store: InMemoryOccupancyStore | None = None,
        throttle: TokenBucketThrottle | None = None,
        platform: str = "generic",
    ) -> None:
        self.frontier_store = frontier_store or InMemoryFrontierStore()
        self.occupancy_store = occupancy_store or InMemoryOccupancyStore()
        self._throttle = throttle
        policy = load_rate_limit_policy(platform)
        self._backoff_seconds = policy["backoff_seconds"]
        self._max_retries = policy["max_retries"]

    def enqueue(self, entry: FrontierEntry) -> FrontierEntry:
        return self.frontier_store.put(entry)

    async def lease_next(self, worker_id: str) -> FrontierEntry | None:
        """Lease the highest-priority queued entry.

        Promotes retryable entries first, then applies rate limiting via the
        optional throttle before returning the next entry.
        """
        # Promote retryable entries first
        self.frontier_store.promote_retryable(_now_iso())

        for _retry in range(3):
            queued = self.frontier_store.list_queued()
            if not queued:
                return None

            # Rate limit
            if self._throttle is not None:
                await self._throttle.acquire()

            entry = max(queued, key=lambda item: item.priority)
            leased = self.frontier_store.lease(entry.frontier_id)
            if leased is not None:
                break
        else:
            return None

        lease = OccupancyLease(
            lease_id=f"{leased.frontier_id}:{worker_id}",
            job_id=leased.job_id,
            frontier_id=leased.frontier_id,
            worker_id=worker_id,
            leased_at=_now_iso(),
        )
        self.occupancy_store.put(lease)
        return leased

    def complete(self, frontier_id: str) -> FrontierEntry | None:
        self.occupancy_store.release_by_frontier_id(frontier_id)
        return self.frontier_store.mark_done(frontier_id)

    def report_failure(
        self, frontier_id: str, error: Exception | None = None,
    ) -> FrontierEntry | None:
        """Handle failure with exponential backoff or mark dead."""
        self.occupancy_store.release_by_frontier_id(frontier_id)
        entry = self.frontier_store.get(frontier_id)
        if entry is None:
            return None

        if entry.attempt >= self._max_retries:
            return self.frontier_store.mark_dead(frontier_id)

        # Calculate backoff delay
        idx = min(entry.attempt, len(self._backoff_seconds) - 1)
        delay = self._backoff_seconds[idx] if self._backoff_seconds else 5
        not_before = (
            (datetime.now(timezone.utc) + timedelta(seconds=delay))
            .isoformat(timespec="seconds")
            .replace("+00:00", "Z")
        )

        error_dict = {"message": str(error)} if error else None
        return self.frontier_store.mark_retry(frontier_id, not_before, error_dict)
