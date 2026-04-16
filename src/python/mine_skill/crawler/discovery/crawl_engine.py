from __future__ import annotations

from typing import Any

from crawler.discovery.contracts import CrawlOptions, DiscoveryCandidate


async def crawl_generic(
    *,
    seeds: list[DiscoveryCandidate],
    fetch_fn: Any,
    options: CrawlOptions,
) -> list[dict[str, Any]]:
    from crawler.discovery.runner import run_discover_crawl

    return await run_discover_crawl(seeds=seeds, fetch_fn=fetch_fn, options=options)
