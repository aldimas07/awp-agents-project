"""Expand a LinkedIn profile page into categorized URLs.

Fetches the profile HTML (and optionally recent-activity), discovers
embedded LinkedIn links via ``discover_from_html_deep``, classifies
them into buckets (company, post, profile, etc.), and returns an
``ExpandResult``.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Awaitable, Callable
from urllib.parse import unquote, urlparse

from crawler.discovery.expand.base import ExpandResult
from crawler.discovery.normalize.linkedin import (
    discover_from_html_deep,
    normalize_linkedin_url,
)

# ---------------------------------------------------------------------------
# URL classification
# ---------------------------------------------------------------------------


def _path_parts(path: str) -> list[str]:
    return [p for p in path.strip().split("/") if p]


def classify_linkedin_url(url: str) -> str:
    """Classify a LinkedIn URL into a bucket category.

    Categories: ``jobs_search``, ``company``, ``company_tab``, ``post``,
    ``profile``, ``profile_activity``, ``profile_subpage``, ``job``, ``other``.
    """
    try:
        p = urlparse(url)
        if p.scheme not in ("http", "https"):
            return "other"
        path = unquote(p.path or "")
        low = path.lower()

        if "/jobs/search" in low:
            return "jobs_search"
        if "/jobs/view/" in low or "/jobs/collections/" in low:
            return "job"
        if "/company/" in low:
            parts = [seg for seg in path.strip("/").split("/") if seg]
            if (
                len(parts) >= 3
                and parts[0].lower() == "company"
                and parts[2].lower() in ("jobs", "people", "posts", "life")
            ):
                return "company_tab"
            return "company"
        if "feed/update" in low and "activity" in low:
            return "post"
        if "/posts/" in low and "activity-" in low:
            return "post"

        parts = _path_parts(path)
        if len(parts) >= 2 and parts[0].lower() == "in":
            if len(parts) == 2:
                return "profile"
            if len(parts) >= 3 and parts[2].lower() == "recent-activity":
                return "profile_activity"
            return "profile_subpage"

        return "other"
    except Exception:
        return "other"


# ---------------------------------------------------------------------------
# Nav / footer filtering
# ---------------------------------------------------------------------------


def filter_global_nav_urls(urls: list[str]) -> list[str]:
    """Remove global navigation / footer / help links to reduce noise."""
    return [u for u in urls if not _is_global_nav_or_footer(u)]


def _is_global_nav_or_footer(url: str) -> bool:
    try:
        p = urlparse(url)
        host = (p.netloc or "").lower()
        path = (p.path or "").lower()
        q = (p.query or "").lower()
        if any(
            sub in host
            for sub in (
                "about.linkedin.com",
                "business.linkedin.com",
                "careers.linkedin.com",
                "mobile.linkedin.com",
                "safety.linkedin.com",
            )
        ):
            return True
        if path in ("/", "/feed", "/feed/") or (path.startswith("/feed") and "nis=" in q):
            return True
        nav_prefixes = (
            "/mynetwork", "/notifications", "/messaging",
            "/help/", "/legal/", "/accessibility",
            "/mypreferences", "/ad/", "/jobs/?",
        )
        if any(path.startswith(pfx) for pfx in nav_prefixes):
            return True
        if path in ("/jobs", "/jobs/"):
            return True
    except Exception:
        return False
    return False


# ---------------------------------------------------------------------------
# Bucketing
# ---------------------------------------------------------------------------


def bucket_urls_by_category(
    urls: list[str],
    seed_vanity: str | None = None,
) -> dict[str, list[str]]:
    """Group URLs by ``classify_linkedin_url`` category.

    When *seed_vanity* is given, splits ``profile`` into
    ``profiles_others`` and ``profiles_self``.
    """
    buckets: dict[str, list[str]] = defaultdict(list)
    profiles_others: list[str] = []
    profiles_self: list[str] = []

    seen: set[str] = set()
    for raw in urls:
        u = raw.split("#", 1)[0].strip()
        if not u or u in seen:
            continue
        seen.add(u)
        cat = classify_linkedin_url(u)
        buckets[cat].append(u)

        if cat == "profile" and seed_vanity:
            r = normalize_linkedin_url(u)
            v = (r.identity.get("vanity") or "").lower()
            if v == seed_vanity.lower():
                profiles_self.append(u)
            else:
                profiles_others.append(u)

    if profiles_others:
        buckets["profiles_others"] = sorted(set(profiles_others))
    if profiles_self:
        buckets["profiles_self"] = sorted(set(profiles_self))

    if seed_vanity:
        buckets.pop("profile", None)

    return {k: sorted(v) for k, v in buckets.items()}


# ---------------------------------------------------------------------------
# Async profile expander
# ---------------------------------------------------------------------------


async def expand_profile(
    url: str,
    fetch_fn: Callable[[str], Awaitable[str]],
    *,
    also_fetch_activity: bool = True,
    filter_nav: bool = True,
) -> ExpandResult:
    """Fetch a profile page and expand discovered URLs into buckets.

    Parameters
    ----------
    url:
        A LinkedIn profile URL (``/in/{vanity}/``).
    fetch_fn:
        Async callable that takes a URL string and returns the page HTML.
    also_fetch_activity:
        If ``True``, also fetches the recent-activity/comments page.
    filter_nav:
        If ``True``, strips global navigation / footer links.
    """
    seed = normalize_linkedin_url(url)
    if seed.entity_type != "profile" or not seed.identity.get("vanity"):
        raise ValueError(f"Not a profile URL: {url}")

    vanity = seed.identity["vanity"]
    all_urls: list[str] = []

    html_main = await fetch_fn(seed.canonical_url)
    all_urls.extend(discover_from_html_deep(html_main, base_url=seed.canonical_url))

    if also_fetch_activity:
        act_url = f"https://www.linkedin.com/in/{vanity}/recent-activity/comments/"
        try:
            html_act = await fetch_fn(act_url)
            all_urls.extend(discover_from_html_deep(html_act, base_url=act_url))
        except Exception:
            pass

    if filter_nav:
        all_urls = filter_global_nav_urls(all_urls)

    buckets = bucket_urls_by_category(all_urls, seed_vanity=vanity)

    return ExpandResult(
        urls=all_urls,
        buckets=buckets,
        metadata={
            "canonical_url": seed.canonical_url,
            "vanity": vanity,
            "also_fetched_activity": also_fetch_activity,
        },
    )
