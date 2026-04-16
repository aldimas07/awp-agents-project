"""Expand a LinkedIn job page into categorized URLs.

Fetches the job detail HTML, discovers embedded LinkedIn links via
``discover_from_html_deep``, classifies them into buckets, and returns
an ``ExpandResult``.
"""

from __future__ import annotations

from typing import Awaitable, Callable

from crawler.discovery.expand.base import ExpandResult
from crawler.discovery.expand.linkedin_profile import (
    bucket_urls_by_category,
    filter_global_nav_urls,
)
from crawler.discovery.normalize.linkedin import (
    discover_from_html_deep,
    normalize_linkedin_url,
)


def _dedupe_preserve_order(urls: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for u in urls:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


async def expand_job(
    url: str,
    fetch_fn: Callable[[str], Awaitable[str]],
    filter_nav: bool = True,
) -> ExpandResult:
    """Fetch a job detail page and expand discovered URLs into buckets.

    Parameters
    ----------
    url:
        A LinkedIn job URL (``/jobs/view/{id}/``).
    fetch_fn:
        Async callable that takes a URL string and returns the page HTML.
    filter_nav:
        If ``True``, strips global navigation / footer links.
    """
    seed = normalize_linkedin_url(url)
    if seed.entity_type != "job" or not seed.canonical_url:
        raise ValueError(f"Not a recognized job URL: {url}")

    canonical = seed.canonical_url
    html = await fetch_fn(canonical)

    urls = discover_from_html_deep(html, base_url=canonical)
    if filter_nav:
        urls = filter_global_nav_urls(urls)
    urls = _dedupe_preserve_order(urls)
    buckets = bucket_urls_by_category(urls, seed_vanity=None)

    return ExpandResult(
        urls=urls,
        buckets=buckets,
        metadata={
            "canonical_job_url": canonical,
            "job_id": seed.identity.get("job_id", ""),
        },
    )
