"""Generalized BFS graph traversal engine for URL discovery."""

from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from crawler.discovery.adapters.base import BaseDiscoveryAdapter
from crawler.discovery.scheduler import DiscoveryScheduler
from crawler.discovery.state.frontier import FrontierEntry
from crawler.discovery.state.visited import VisitRecord
from crawler.discovery.store.visited_store import InMemoryVisitedStore
from crawler.discovery.throttle import TokenBucketThrottle


@dataclass
class BfsExpandResult:
    """Result of BFS expansion."""

    discovered_by_type: dict[str, list[str]] = field(default_factory=dict)
    expansions_run: int = 0
    max_depth_seen: int = 0
    errors: list[str] = field(default_factory=list)
    stopped_by_time_limit: bool = False
    stopped_by_page_limit: bool = False

    @property
    def total_discovered(self) -> int:
        return sum(len(urls) for urls in self.discovered_by_type.values())


@dataclass
class BfsOptions:
    """Configuration for BFS graph traversal."""

    max_expand_depth: int | None = None
    max_runtime_seconds: float | None = None
    max_pages: int = 100
    expand_options: dict[str, Any] = field(default_factory=dict)


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


async def run_bfs_expand(
    seed_urls: list[str],
    fetch_fn: Callable[[str], Awaitable[str]],
    adapter: BaseDiscoveryAdapter,
    options: BfsOptions | None = None,
    *,
    verbose: bool = False,
    throttle: TokenBucketThrottle | None = None,
) -> tuple[BfsExpandResult, dict[str, Any]]:
    """Run BFS expansion using the adapter's normalize/expand methods.

    Parameters
    ----------
    seed_urls:
        Initial URLs to start BFS from.
    fetch_fn:
        Async callable to fetch URL content.
    adapter:
        Platform adapter with normalize_url() and expand() methods.
    options:
        BFS configuration options.
    verbose:
        Print progress information.

    Returns
    -------
    tuple:
        (BfsExpandResult, stats_dict)
    """
    opts = options or BfsOptions()
    scheduler = DiscoveryScheduler(throttle=throttle, platform=adapter.platform)
    visited = InMemoryVisitedStore()
    discovered_by_type: dict[str, set[str]] = defaultdict(set)
    errors: list[str] = []

    # Initialize seeds
    for i, url in enumerate(seed_urls):
        normalized = adapter.normalize_url(url)
        if normalized.entity_type == "unknown":
            errors.append(f"Cannot normalize seed: {url}")
            continue

        discovered_by_type[normalized.entity_type].add(normalized.canonical_url)
        url_key = f"{adapter.platform}:{normalized.canonical_url}"

        scheduler.enqueue(FrontierEntry(
            frontier_id=f"seed-{i}",
            job_id="bfs-expand",
            url_key=url_key,
            canonical_url=normalized.canonical_url,
            adapter=adapter.platform,
            entity_type=normalized.entity_type,
            depth=0,
            priority=1.0,
            discovered_from=None,
            discovery_reason="seed",
        ))

    # BFS loop
    t_start = time.perf_counter()
    expansions_run = 0
    max_depth_seen = 0
    stopped_by_time = False
    stopped_by_pages = False

    while True:
        # Time limit check
        if opts.max_runtime_seconds is not None:
            elapsed = time.perf_counter() - t_start
            if elapsed >= opts.max_runtime_seconds:
                stopped_by_time = True
                if verbose:
                    print(f"[bfs] Time limit reached ({opts.max_runtime_seconds}s)")
                break

        # Page limit check
        if expansions_run >= opts.max_pages:
            stopped_by_pages = True
            if verbose:
                print(f"[bfs] Page limit reached ({opts.max_pages})")
            break

        # Get next entry
        entry = await scheduler.lease_next("bfs-worker")
        if entry is None:
            break

        # Skip if already visited
        if visited.get(entry.url_key):
            scheduler.complete(entry.frontier_id)
            continue

        # Depth limit check
        if opts.max_expand_depth is not None and entry.depth >= opts.max_expand_depth:
            scheduler.complete(entry.frontier_id)
            continue

        max_depth_seen = max(max_depth_seen, entry.depth)

        if verbose:
            print(f"[bfs] Expanding depth={entry.depth} type={entry.entity_type} url={entry.canonical_url[:80]}...")

        try:
            # Build candidate for expand
            from crawler.discovery.contracts import DiscoveryCandidate, DiscoveryMode

            candidate = DiscoveryCandidate(
                platform=adapter.platform,
                resource_type=entry.entity_type or "unknown",
                canonical_url=entry.canonical_url,
                seed_url=None,
                fields={},
                discovery_mode=DiscoveryMode.GRAPH_TRAVERSAL,
                score=entry.priority,
                score_breakdown={},
                hop_depth=entry.depth,
                parent_url=entry.discovered_from.get("parent_url") if entry.discovered_from else None,
                metadata={},
            )

            # Call adapter's expand method
            result = await adapter.expand(candidate, fetch_fn, opts.expand_options)
            expansions_run += 1

            # Process discovered URLs
            for url in result.urls:
                normalized = adapter.normalize_url(url)
                if normalized.entity_type == "unknown":
                    continue

                discovered_by_type[normalized.entity_type].add(normalized.canonical_url)
                child_url_key = f"{adapter.platform}:{normalized.canonical_url}"

                if not visited.get(child_url_key):
                    scheduler.enqueue(FrontierEntry(
                        frontier_id=f"expand-{expansions_run}-{child_url_key}",
                        job_id="bfs-expand",
                        url_key=child_url_key,
                        canonical_url=normalized.canonical_url,
                        adapter=adapter.platform,
                        entity_type=normalized.entity_type,
                        depth=entry.depth + 1,
                        priority=0.8,
                        discovered_from={"parent_url": entry.canonical_url},
                        discovery_reason="expansion",
                    ))

            # Mark visited and complete in scheduler
            visited.put(VisitRecord(
                url_key=entry.url_key,
                canonical_url=entry.canonical_url or "",
                scope_key=adapter.platform,
                first_seen_at=_now_iso(),
                last_seen_at=_now_iso(),
                best_depth=entry.depth,
                crawl_state="done",
            ))
            scheduler.complete(entry.frontier_id)

        except Exception as e:
            errors.append(f"{entry.canonical_url}: {e!r}")
            scheduler.report_failure(entry.frontier_id, e)
            # Mark as visited with error state to prevent infinite retry
            visited.put(VisitRecord(
                url_key=entry.url_key,
                canonical_url=entry.canonical_url or "",
                scope_key=adapter.platform,
                first_seen_at=_now_iso(),
                last_seen_at=_now_iso(),
                best_depth=entry.depth,
                crawl_state="error",
            ))
            if verbose:
                print(f"[bfs] Error: {e!r}")

    elapsed = time.perf_counter() - t_start

    result = BfsExpandResult(
        discovered_by_type={k: sorted(v) for k, v in discovered_by_type.items()},
        expansions_run=expansions_run,
        max_depth_seen=max_depth_seen,
        errors=errors,
        stopped_by_time_limit=stopped_by_time,
        stopped_by_page_limit=stopped_by_pages,
    )

    stats = {
        "expansions_run": expansions_run,
        "elapsed_seconds": round(elapsed, 3),
        "total_discovered": result.total_discovered,
        "max_depth_seen": max_depth_seen,
        "stopped_by_time_limit": stopped_by_time,
        "stopped_by_page_limit": stopped_by_pages,
        "errors_count": len(errors),
    }

    return result, stats
