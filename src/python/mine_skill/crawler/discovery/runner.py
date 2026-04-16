from __future__ import annotations

import asyncio
import inspect
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from crawler.core.auth import build_error_from_fetch_error
from crawler.discovery.contracts import CrawlOptions, DiscoveryCandidate, DiscoveryMode
from crawler.discovery.scheduler import DiscoveryScheduler
from crawler.discovery.state.frontier import FrontierEntry
from crawler.discovery.state.checkpoint import Checkpoint
from crawler.discovery.state.visited import VisitRecord
from crawler.discovery.store.checkpoint_store import InMemoryCheckpointStore
from crawler.discovery.store.frontier_store import InMemoryFrontierStore
from crawler.discovery.store.visited_store import InMemoryVisitedStore
from crawler.discovery.throttle import TokenBucketThrottle


def _build_record(candidate: DiscoveryCandidate, fetched: dict[str, Any]) -> dict[str, Any]:
    return {
        "platform": candidate.platform,
        "resource_type": candidate.resource_type,
        "canonical_url": candidate.canonical_url,
        "seed_url": candidate.seed_url,
        "discovery_mode": candidate.discovery_mode.value,
        "hop_depth": candidate.hop_depth,
        "fetched": fetched,
    }


def _put_visit_record(
    visited_store: InMemoryVisitedStore,
    candidate: DiscoveryCandidate,
    *,
    crawl_state: str,
    fetched: dict[str, Any] | None = None,
) -> None:
    final_url = candidate.canonical_url
    http_status = None
    if fetched is not None:
        final_url = str(fetched.get("final_url") or fetched.get("url") or candidate.canonical_url)
        if fetched.get("status_code") is not None:
            http_status = int(fetched["status_code"])
    visited_store.put(
        VisitRecord(
            url_key=_url_key(candidate),
            canonical_url=candidate.canonical_url,
            scope_key=_scope_key(candidate.canonical_url),
            first_seen_at=_now_iso(),
            last_seen_at=_now_iso(),
            best_depth=candidate.hop_depth,
            crawl_state=crawl_state,
            final_url=final_url,
            http_status=http_status,
        )
    )


def _write_checkpoint(
    checkpoint_store: InMemoryCheckpointStore,
    frontier_store: InMemoryFrontierStore,
    visited_store: InMemoryVisitedStore,
) -> None:
    frontier_store.prune_terminal()
    checkpoint_store.put(
        "discover-crawl",
        Checkpoint(
            job_id="discover-crawl",
            checkpoint_id="discover-crawl",
            created_at=_now_iso(),
            frontier_cursor=str(len(frontier_store.list())),
            visited_cursor=str(len(visited_store.list())),
        ),
    )


async def run_discover_crawl(
    *,
    seeds: list[DiscoveryCandidate],
    fetch_fn: Any,
    options: CrawlOptions,
    adapter_resolver: Any | None = None,
    state_dir: Path | None = None,
    resume: bool = False,
    errors: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    if options.max_pages <= 0:
        return records

    if adapter_resolver is not None:
        return await _run_discover_crawl_graph(
            seeds=seeds,
            fetch_fn=fetch_fn,
            options=options,
            adapter_resolver=adapter_resolver,
            state_dir=state_dir,
            resume=resume,
            errors=errors,
        )

    for candidate in seeds:
        if len(records) >= options.max_pages:
            break
        if candidate.hop_depth > options.max_depth:
            continue
        if not candidate.canonical_url:
            continue

        fetched = fetch_fn(candidate.canonical_url)
        if inspect.isawaitable(fetched):
            fetched = await fetched

        records.append(_build_record(candidate, _normalize_fetched_payload(fetched)))

    return records


async def _run_discover_crawl_graph(
    *,
    seeds: list[DiscoveryCandidate],
    fetch_fn: Any,
    options: CrawlOptions,
    adapter_resolver: Any,
    state_dir: Path | None = None,
    resume: bool = False,
    errors: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    if state_dir is not None:
        state_dir.mkdir(parents=True, exist_ok=True)
    frontier_path = state_dir / "frontier.json" if state_dir is not None else None
    visited_path = state_dir / "visited.json" if state_dir is not None else None
    checkpoint_path = state_dir / "checkpoints.json" if state_dir is not None else None
    candidates_path = state_dir / "candidates.json" if state_dir is not None else None

    if state_dir is not None and not resume:
        for path in (frontier_path, visited_path, checkpoint_path, candidates_path):
            if path is not None and path.exists():
                path.unlink()

    frontier_store = InMemoryFrontierStore(frontier_path)
    visited_store = InMemoryVisitedStore(visited_path)
    checkpoint_store = InMemoryCheckpointStore(checkpoint_path)
    platform = seeds[0].platform if seeds else "generic"
    throttle = TokenBucketThrottle.for_platform(platform)
    scheduler = DiscoveryScheduler(
        frontier_store=frontier_store, throttle=throttle, platform=platform,
    )
    candidates_by_frontier_id = _load_candidates(candidates_path) if resume else {}
    records: list[dict[str, Any]] = []
    page_lock = asyncio.Lock()
    claimed_pages = 0

    if not resume or not candidates_by_frontier_id:
        for index, seed in enumerate(seeds):
            if not seed.canonical_url:
                continue
            frontier_id = f"seed-{index}"
            candidates_by_frontier_id[frontier_id] = seed
            scheduler.enqueue(
                FrontierEntry(
                    frontier_id=frontier_id,
                    job_id="discover-crawl",
                    url_key=_url_key(seed),
                    canonical_url=seed.canonical_url,
                    adapter=seed.platform,
                    entity_type=seed.resource_type,
                    depth=seed.hop_depth,
                    priority=seed.score,
                    discovered_from={"parent_url": seed.parent_url} if seed.parent_url else None,
                    discovery_reason=seed.discovery_mode.value,
                )
            )
        _save_candidates(candidates_path, candidates_by_frontier_id)

    async def _claim_page_slot() -> bool:
        nonlocal claimed_pages
        async with page_lock:
            if claimed_pages >= options.max_pages:
                return False
            claimed_pages += 1
            return True

    async def _release_page_slot() -> None:
        nonlocal claimed_pages
        async with page_lock:
            claimed_pages -= 1

    empty_streak_limit = 3

    async def _worker(worker_index: int) -> None:
        empty_streak = 0
        while await _claim_page_slot():
            leased = await scheduler.lease_next(f"worker-{worker_index}")
            if leased is None:
                await _release_page_slot()
                empty_streak += 1
                if empty_streak >= empty_streak_limit:
                    break
                # Other workers may spawn new entries; wait briefly and retry
                await asyncio.sleep(0.2)
                continue
            empty_streak = 0

            candidate = candidates_by_frontier_id.get(leased.frontier_id)
            if candidate is None or not candidate.canonical_url:
                scheduler.complete(leased.frontier_id)
                await _release_page_slot()
                continue
            if candidate.hop_depth > options.max_depth:
                _put_visit_record(visited_store, candidate, crawl_state="depth_exceeded")
                scheduler.complete(leased.frontier_id)
                await _release_page_slot()
                continue
            if visited_store.get(_url_key(candidate)) is not None:
                scheduler.complete(leased.frontier_id)
                await _release_page_slot()
                continue

            try:
                adapter = adapter_resolver(candidate.platform)
                crawl_result = await adapter.crawl(
                    candidate,
                    {
                        "fetch_fn": lambda _ignored=None, _candidate=candidate: _call_fetch(fetch_fn, _candidate),
                        "options": options,
                        "query": candidate.metadata.get("query", ""),
                        "search_type": candidate.metadata.get("search_type", ""),
                    },
                )
            except Exception as exc:
                if errors is not None:
                    fetch_error = getattr(exc, "fetch_error", None)
                    if fetch_error is not None:
                        error = build_error_from_fetch_error(
                            platform=candidate.platform,
                            resource_type=candidate.resource_type,
                            fetch_error=fetch_error,
                            stage="discovery_crawl",
                            message=str(exc),
                            exception=exc,
                        )
                    else:
                        error = {
                            "platform": candidate.platform,
                            "resource_type": candidate.resource_type,
                            "stage": "discovery_crawl",
                            "status": "failed",
                            "error_code": "DISCOVERY_CRAWL_FAILED",
                            "retryable": False,
                            "next_action": "inspect error and retry",
                            "message": str(exc),
                        }
                    error["canonical_url"] = candidate.canonical_url
                    error["seed_url"] = candidate.seed_url
                    error["hop_depth"] = candidate.hop_depth
                    errors.append(error)
                scheduler.report_failure(leased.frontier_id, exc)
                _put_visit_record(visited_store, candidate, crawl_state="failed")
                _write_checkpoint(checkpoint_store, frontier_store, visited_store)
                await _release_page_slot()
                continue
            try:
                fetched = _normalize_fetched_payload(crawl_result.get("fetched", {}))
            except TypeError:
                scheduler.report_failure(leased.frontier_id, TypeError("invalid fetched payload"))
                _put_visit_record(visited_store, candidate, crawl_state="failed")
                await _release_page_slot()
                continue
            async with page_lock:
                records.append(_build_record(candidate, fetched))
            _put_visit_record(visited_store, candidate, crawl_state="done", fetched=fetched)
            scheduler.complete(leased.frontier_id)
            _write_checkpoint(checkpoint_store, frontier_store, visited_store)

            for spawned in crawl_result.get("spawned_candidates", []):
                if not spawned.canonical_url or spawned.hop_depth > options.max_depth:
                    continue
                if visited_store.get(_url_key(spawned)) is not None:
                    continue
                if _candidate_exists(candidates_by_frontier_id, spawned):
                    continue
                frontier_id = f"{leased.frontier_id}:{_url_key(spawned)}"
                candidates_by_frontier_id[frontier_id] = spawned
                scheduler.enqueue(
                    FrontierEntry(
                        frontier_id=frontier_id,
                        job_id="discover-crawl",
                        url_key=_url_key(spawned),
                        canonical_url=spawned.canonical_url,
                        adapter=spawned.platform,
                        entity_type=spawned.resource_type,
                        depth=spawned.hop_depth,
                        priority=spawned.score,
                        discovered_from={"parent_url": spawned.parent_url} if spawned.parent_url else None,
                        discovery_reason=spawned.discovery_mode.value,
                    )
                )
                _save_candidates(candidates_path, candidates_by_frontier_id)

    await asyncio.gather(
        *[_worker(i) for i in range(max(1, options.max_concurrency))]
    )

    return records


async def _call_fetch(fetch_fn: Any, candidate: DiscoveryCandidate) -> dict[str, Any]:
    try:
        fetched = fetch_fn(candidate)
    except TypeError:
        fetched = fetch_fn(candidate.canonical_url)
    if inspect.isawaitable(fetched):
        fetched = await fetched
    return _normalize_fetched_payload(fetched)


def _url_key(candidate: DiscoveryCandidate) -> str:
    return f"{candidate.platform}:{candidate.canonical_url}"


def _scope_key(url: str) -> str:
    if "//" in url:
        return url.split("//", 1)[1].split("/", 1)[0]
    return url


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _normalize_fetched_payload(fetched: Any) -> dict[str, Any]:
    if isinstance(fetched, dict):
        return fetched

    to_legacy_dict = getattr(fetched, "to_legacy_dict", None)
    if callable(to_legacy_dict):
        payload = to_legacy_dict()
        if isinstance(payload, dict):
            return payload

    raise TypeError(
        "run_discover_crawl expected fetch_fn to return a dict or an object with to_legacy_dict()"
    )


def _candidate_exists(candidates_by_frontier_id: dict[str, DiscoveryCandidate], candidate: DiscoveryCandidate) -> bool:
    return any(
        existing.platform == candidate.platform
        and existing.canonical_url == candidate.canonical_url
        for existing in candidates_by_frontier_id.values()
    )


def _load_candidates(path: Path | None) -> dict[str, DiscoveryCandidate]:
    if path is None or not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {
        frontier_id: DiscoveryCandidate(
            platform=item["platform"],
            resource_type=item["resource_type"],
            canonical_url=item["canonical_url"],
            seed_url=item["seed_url"],
            fields=dict(item.get("fields", {})),
            discovery_mode=DiscoveryMode(item["discovery_mode"]),
            score=float(item["score"]),
            score_breakdown=dict(item.get("score_breakdown", {})),
            hop_depth=int(item["hop_depth"]),
            metadata=dict(item.get("metadata", {})),
            parent_url=item.get("parent_url"),
        )
        for frontier_id, item in payload.items()
    }


def _save_candidates(path: Path | None, candidates_by_frontier_id: dict[str, DiscoveryCandidate]) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        frontier_id: {
            "platform": candidate.platform,
            "resource_type": candidate.resource_type,
            "canonical_url": candidate.canonical_url,
            "seed_url": candidate.seed_url,
            "fields": candidate.fields,
            "discovery_mode": candidate.discovery_mode.value,
            "score": candidate.score,
            "score_breakdown": candidate.score_breakdown,
            "hop_depth": candidate.hop_depth,
            "metadata": candidate.metadata,
            "parent_url": candidate.parent_url,
        }
        for frontier_id, candidate in candidates_by_frontier_id.items()
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
