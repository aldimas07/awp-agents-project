"""Expand a LinkedIn post/activity page into categorized URLs.

Fetches the post detail HTML, discovers embedded LinkedIn links via
``discover_from_html_deep``, classifies them into buckets (commenter
profiles, companies, related posts, etc.), and returns an ``ExpandResult``.
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


async def expand_post(
    url: str,
    fetch_fn: Callable[[str], Awaitable[str]],
    *,
    filter_nav: bool = True,
) -> ExpandResult:
    """Fetch a post detail page and expand discovered URLs into buckets.

    Parameters
    ----------
    url:
        A LinkedIn post URL (``/feed/update/urn:li:activity:…`` or
        ``/posts/…activity-…``).
    fetch_fn:
        Async callable that takes a URL string and returns the page HTML.
    filter_nav:
        If ``True``, strips global navigation / footer links.
    """
    seed = normalize_linkedin_url(url)
    if seed.entity_type != "post" or not seed.canonical_url:
        raise ValueError(f"Not a recognized post URL: {url}")

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
            "canonical_post_url": canonical,
            "activity_id": seed.identity.get("activity_id", ""),
            "original_input_url": url.strip(),
        },
    )
