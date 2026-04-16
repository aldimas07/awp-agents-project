"""LinkedIn discovery adapter for profile, company, and job discovery."""
from __future__ import annotations

import re
from dataclasses import replace
from typing import Any, Awaitable, Callable
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from crawler.discovery.adapters.base import BaseDiscoveryAdapter
from crawler.discovery.contracts import (
    DiscoveryCandidate,
    DiscoveryMode,
    DiscoveryRecord,
)
from crawler.discovery.expand.base import ExpandResult
from crawler.discovery.map_engine import MapResult
from crawler.discovery.normalize.base import NormalizeResult
from crawler.discovery.normalize.linkedin import (
    discover_from_html_deep,
    normalize_linkedin_url,
)


class LinkedInDiscoveryAdapter(BaseDiscoveryAdapter):
    """Discovery adapter for LinkedIn entities.

    Handles discovery of profiles, companies, posts, and jobs from search results.
    """

    platform = "linkedin"
    supported_resource_types = ("search", "profile", "company", "post", "job")

    def can_handle_url(self, url: str) -> bool:
        return "linkedin.com" in url

    def build_seed_records(self, input_record: dict[str, Any]) -> list[DiscoveryRecord]:
        from crawler.discovery.url_builder import build_seed_records

        return build_seed_records(input_record)

    async def map_search_candidates(
        self,
        query: str,
        search_type: str,
        candidates: list[dict[str, Any]],
    ) -> MapResult:
        """Promote search candidates to entity candidates.

        Args:
            query: The search query used
            search_type: Type of search (profile, company, job, etc.)
            candidates: List of candidate dicts with canonical_url and resource_type

        Returns:
            MapResult with accepted entity candidates
        """
        accepted: list[DiscoveryCandidate] = []

        for item in candidates:
            accepted.append(
                DiscoveryCandidate(
                    platform="linkedin",
                    resource_type=item["resource_type"],
                    canonical_url=item["canonical_url"],
                    seed_url=None,
                    fields={},
                    discovery_mode=DiscoveryMode.SEARCH_RESULTS,
                    score=0.85,
                    score_breakdown={"search_results": 0.85},
                    hop_depth=1,
                    parent_url=None,
                    metadata={"query": query, "search_type": search_type},
                )
            )

        return MapResult(accepted=accepted, rejected=[], exhausted=True, next_seeds=[])

    async def map(
        self, seed: DiscoveryRecord, context: dict[str, Any]
    ) -> MapResult:
        """Extract entity candidates from a LinkedIn page."""
        search_candidates = list(context.get("search_candidates", []))
        if not search_candidates:
            html = str(context.get("html") or "")
            soup = BeautifulSoup(html, "html.parser")
            for anchor in soup.find_all("a", href=True):
                href = str(anchor.get("href") or "")
                absolute = urljoin(seed.canonical_url, href)
                if "/company/" in absolute:
                    search_candidates.append({"canonical_url": absolute.rstrip("/").split("?")[0] + "/", "resource_type": "company"})
                elif "/in/" in absolute:
                    search_candidates.append({"canonical_url": absolute.rstrip("/").split("?")[0] + "/", "resource_type": "profile"})
                elif "/jobs/view/" in absolute:
                    search_candidates.append({"canonical_url": absolute.split("?")[0], "resource_type": "job"})

            for match in re.findall(r'https://www\.linkedin\.com/(company/[^"\']+|in/[^"\']+|jobs/view/\d+)', html):
                canonical_url = f"https://www.linkedin.com/{match}".split("?")[0]
                resource_type = "company" if match.startswith("company/") else "profile" if match.startswith("in/") else "job"
                if resource_type in {"company", "profile"} and not canonical_url.endswith("/"):
                    canonical_url += "/"
                search_candidates.append({"canonical_url": canonical_url, "resource_type": resource_type})

        # For now, delegate to search candidates if available
        if search_candidates:
            return await self.map_search_candidates(
                query=context.get("query", ""),
                search_type=context.get("search_type", ""),
                candidates=list({
                    (item["canonical_url"], item["resource_type"]): item
                    for item in search_candidates
                }.values()),
            )
        return MapResult(accepted=[], rejected=[], exhausted=True, next_seeds=[])

    async def crawl(
        self, candidate: DiscoveryCandidate, context: dict[str, Any]
    ) -> Any:
        fetch_fn = context.get("fetch_fn")
        if not callable(fetch_fn) or not candidate.canonical_url:
            return {"candidate": candidate, "fetched": {}, "spawned_candidates": []}

        fetched = fetch_fn(candidate.canonical_url)
        if hasattr(fetched, "__await__"):
            fetched = await fetched
        if not isinstance(fetched, dict):
            to_legacy_dict = getattr(fetched, "to_legacy_dict", None)
            if callable(to_legacy_dict):
                fetched = to_legacy_dict()
        if not isinstance(fetched, dict):
            raise TypeError("linkedin crawl expected fetched payload as dict or to_legacy_dict()")

        seed = DiscoveryRecord(
            platform=candidate.platform,
            resource_type=candidate.resource_type,
            discovery_mode=candidate.discovery_mode,
            canonical_url=candidate.canonical_url,
            identity=dict(candidate.fields),
            source_seed=None,
            discovered_from={"parent_url": candidate.parent_url},
            metadata=dict(candidate.metadata),
        )
        map_result = await self.map(
            seed,
            {
                "query": context.get("query", ""),
                "search_type": context.get("search_type", ""),
                "html": fetched.get("html", ""),
            },
        )
        spawned_candidates = [
            replace(
                spawned,
                seed_url=candidate.seed_url or candidate.canonical_url,
                hop_depth=candidate.hop_depth + 1,
                parent_url=candidate.canonical_url,
            )
            for spawned in map_result.accepted
        ]
        return {
            "candidate": candidate,
            "fetched": fetched,
            "spawned_candidates": spawned_candidates,
        }

    # --- BFS support methods ---

    def normalize_url(self, url: str) -> NormalizeResult:
        """Normalize a LinkedIn URL using the migrated normalizer."""
        return normalize_linkedin_url(url)

    def discover_from_html(self, html: str, base_url: str) -> list[str]:
        """Extract LinkedIn URLs from HTML using deep discovery."""
        return discover_from_html_deep(html, base_url=base_url)

    async def expand(
        self,
        candidate: DiscoveryCandidate,
        fetch_fn: Callable[[str], Awaitable[str]],
        options: dict[str, Any] | None = None,
    ) -> ExpandResult:
        """Expand a LinkedIn entity to discover related URLs.

        Dispatches to entity-specific expanders based on resource_type.
        """
        opts = options or {}
        entity_type = candidate.resource_type

        if entity_type == "profile":
            from crawler.discovery.expand.linkedin_profile import expand_profile
            return await expand_profile(
                candidate.canonical_url,
                fetch_fn,
                also_fetch_activity=opts.get("also_fetch_activity", True),
                filter_nav=opts.get("filter_nav", True),
            )

        if entity_type == "company":
            from crawler.discovery.expand.linkedin_company import expand_company
            return await expand_company(
                candidate.canonical_url,
                fetch_fn,
                fetch_jobs_tab=opts.get("fetch_jobs_tab", True),
                fetch_people_tab=opts.get("fetch_people_tab", True),
                fetch_posts_tab=opts.get("fetch_posts_tab", True),
                filter_nav=opts.get("filter_nav", True),
            )

        if entity_type == "post":
            from crawler.discovery.expand.linkedin_post import expand_post
            return await expand_post(
                candidate.canonical_url,
                fetch_fn,
                filter_nav=opts.get("filter_nav", True),
            )

        if entity_type == "job":
            from crawler.discovery.expand.linkedin_job import expand_job
            return await expand_job(
                candidate.canonical_url,
                fetch_fn,
                filter_nav=opts.get("filter_nav", True),
            )

        # Fallback: just fetch and discover
        html = await fetch_fn(candidate.canonical_url)
        urls = self.discover_from_html(html, candidate.canonical_url)
        return ExpandResult(urls=urls, buckets={}, metadata={})
