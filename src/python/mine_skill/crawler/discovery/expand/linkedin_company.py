"""Expand a LinkedIn company page by fetching Overview, Jobs, People, and Posts tabs.

Extracts job IDs from HTML and jobs/search URLs, discovers linked profiles,
companies, and posts via deep HTML link extraction.
"""

from __future__ import annotations

import re
from typing import Awaitable, Callable
from urllib.parse import parse_qs, unquote, urlparse

from crawler.discovery.expand.base import ExpandResult
from crawler.discovery.expand.linkedin_profile import (
    bucket_urls_by_category,
    filter_global_nav_urls,
)
from crawler.discovery.normalize.linkedin import (
    discover_from_html_deep,
    normalize_linkedin_url,
)

# ---------------------------------------------------------------------------
# Fetch function type: async callable returning HTML string
# ---------------------------------------------------------------------------

FetchFn = Callable[[str], Awaitable[str]]

# ---------------------------------------------------------------------------
# Job-ID extraction regexes
# ---------------------------------------------------------------------------

_RE_JOB_VIEW = re.compile(r"/jobs/view/(\d{6,})", re.IGNORECASE)
_RE_CURRENT_JOB = re.compile(r"currentJobId=(\d+)", re.IGNORECASE)
_RE_ORIGIN_POSTINGS = re.compile(
    r'originToLandingJobPostings=([^&"\s<>]+)', re.IGNORECASE
)


# ---------------------------------------------------------------------------
# Job ID helpers
# ---------------------------------------------------------------------------


def _job_ids_from_jobs_search_url(url: str) -> list[str]:
    """Parse ``currentJobId`` and ``originToLandingJobPostings`` from a jobs/search URL."""
    q = parse_qs(urlparse(url).query)
    out: list[str] = []
    for v in q.get("currentJobId") or []:
        if v.isdigit():
            out.append(v)
    for v in q.get("originToLandingJobPostings") or []:
        blob = unquote(v)
        for part in blob.split(","):
            p = part.strip()
            if p.isdigit():
                out.append(p)
    # dedupe preserving order
    seen: set[str] = set()
    uniq: list[str] = []
    for x in out:
        if x not in seen:
            seen.add(x)
            uniq.append(x)
    return uniq


def _extract_job_ids_from_html(html: str | None) -> set[str]:
    """Extract job IDs from raw HTML (hrefs, embedded JSON, query strings)."""
    if not html:
        return set()
    ids: set[str] = set()
    for m in _RE_JOB_VIEW.finditer(html):
        ids.add(m.group(1))
    for m in _RE_CURRENT_JOB.finditer(html):
        ids.add(m.group(1))
    for m in _RE_ORIGIN_POSTINGS.finditer(html):
        blob = unquote(m.group(1))
        for part in blob.split(","):
            p = part.strip()
            if p.isdigit():
                ids.add(p)
    return ids


def _canonical_job_view_urls(job_ids: set[str]) -> list[str]:
    return sorted(f"https://www.linkedin.com/jobs/view/{jid}/" for jid in job_ids)


# ---------------------------------------------------------------------------
# Main async expander
# ---------------------------------------------------------------------------


async def expand_company(
    url: str,
    fetch_fn: FetchFn,
    fetch_jobs_tab: bool = True,
    fetch_people_tab: bool = True,
    fetch_posts_tab: bool = True,
    fetch_jobs_search_pages: bool = True,
    max_jobs_search_fetch: int = 5,
    filter_nav: bool = True,
) -> ExpandResult:
    """Fetch company Overview + Jobs/People/Posts tabs, merge discovered links and job IDs.

    Args:
        url: Any LinkedIn company URL (will be normalized).
        fetch_fn: Async callable ``(url) -> html_str``.
        fetch_jobs_tab: Whether to fetch the ``/jobs/`` sub-page.
        fetch_people_tab: Whether to fetch the ``/people/`` sub-page.
        fetch_posts_tab: Whether to fetch the ``/posts/`` sub-page.
        fetch_jobs_search_pages: Whether to follow discovered ``/jobs/search/`` links.
        max_jobs_search_fetch: Maximum number of jobs/search pages to fetch.
        filter_nav: Strip global navigation links from results.

    Returns:
        ExpandResult with discovered URLs bucketed by entity type, plus
        job_ids and company metadata in ``metadata``.
    """
    seed = normalize_linkedin_url(url)
    if seed.entity_type != "company" or not seed.identity.get("vanity"):
        raise ValueError(f"Not a company URL: {url}")

    slug = seed.identity["vanity"]
    base = seed.canonical_url.rstrip("/") + "/"

    urls: list[str] = []
    combined_html: list[str] = []
    jobs_search_pages_fetched = 0

    # Build tab list
    pages: list[tuple[str, str]] = [(base, "overview")]
    if fetch_jobs_tab:
        pages.append((f"{base}jobs/", "jobs"))
    if fetch_people_tab:
        pages.append((f"{base}people/", "people"))
    if fetch_posts_tab:
        pages.append((f"{base}posts/", "posts"))

    # Fetch each tab
    for page_url, _label in pages:
        try:
            html = await fetch_fn(page_url)
            combined_html.append(html)
            urls.extend(discover_from_html_deep(html, base_url=page_url))
        except Exception:
            continue

    # Follow jobs/search links discovered in tab HTML
    if fetch_jobs_search_pages:
        seen_search: set[str] = set()
        for u in list(dict.fromkeys(urls)):
            if "/jobs/search" not in u:
                continue
            nu = u.split("#", 1)[0].strip()
            if nu in seen_search or len(seen_search) >= max_jobs_search_fetch:
                continue
            seen_search.add(nu)
            try:
                html = await fetch_fn(nu)
                combined_html.append(html)
                urls.extend(discover_from_html_deep(html, base_url=nu))
                jobs_search_pages_fetched += 1
            except Exception:
                continue

    # Extract job IDs from all collected HTML
    job_ids = _extract_job_ids_from_html("\n".join(combined_html))
    for u in list(dict.fromkeys(urls)):
        if "/jobs/search" in u:
            job_ids.update(_job_ids_from_jobs_search_url(u))

    # Add canonical job view URLs
    for jid in job_ids:
        urls.append(f"https://www.linkedin.com/jobs/view/{jid}/")

    if filter_nav:
        urls = filter_global_nav_urls(urls)

    buckets = bucket_urls_by_category(urls, seed_vanity=None)
    job_view_urls = _canonical_job_view_urls(job_ids)

    return ExpandResult(
        urls=list(dict.fromkeys(urls)),
        buckets=buckets,
        metadata={
            "company_slug": slug,
            "canonical_company_url": base,
            "job_ids": sorted(job_ids, key=int),
            "job_view_urls": job_view_urls,
            "jobs_search_pages_fetched": jobs_search_pages_fetched,
        },
    )
