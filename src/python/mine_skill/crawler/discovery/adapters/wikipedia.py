"""Wikipedia discovery adapter for article link traversal."""
from __future__ import annotations

from dataclasses import replace
from typing import Any
from urllib.parse import unquote, urljoin, urlparse

from bs4 import BeautifulSoup

from crawler.discovery.adapters.base import BaseDiscoveryAdapter
from crawler.discovery.contracts import (
    DiscoveryCandidate,
    DiscoveryMode,
    DiscoveryRecord,
)
from crawler.discovery.map_engine import MapResult
from crawler.discovery.normalize.base import NormalizeResult


class WikipediaDiscoveryAdapter(BaseDiscoveryAdapter):
    """Discovery adapter for Wikipedia articles.

    Handles article-to-article link discovery via MediaWiki API page links.
    """

    platform = "wikipedia"
    supported_resource_types = ("article",)

    def can_handle_url(self, url: str) -> bool:
        return "wikipedia.org/wiki/" in url

    def build_seed_records(self, input_record: dict[str, Any]) -> list[DiscoveryRecord]:
        from crawler.discovery.url_builder import build_seed_records

        return build_seed_records(input_record)

    def normalize_url(self, url: str) -> NormalizeResult:
        raw = (url or "").strip()
        parsed = urlparse(raw)
        path = unquote(parsed.path or "")
        if "wikipedia.org" not in parsed.netloc or not path.startswith("/wiki/"):
            return NormalizeResult(entity_type="unknown", canonical_url="", original_url=raw)
        title = path.removeprefix("/wiki/").strip().replace(" ", "_")
        if not title or ":" in title:
            return NormalizeResult(entity_type="unknown", canonical_url="", original_url=raw)
        return NormalizeResult(
            entity_type="article",
            canonical_url=f"https://en.wikipedia.org/wiki/{title}",
            identity={"title": title},
            original_url=raw,
        )

    async def map(
        self, seed: DiscoveryRecord, context: dict[str, Any]
    ) -> MapResult:
        """Extract article candidates from MediaWiki API page links.

        Args:
            seed: The seed article record
            context: Must contain 'page_links' list of article titles

        Returns:
            MapResult with accepted article candidates
        """
        accepted: list[DiscoveryCandidate] = []
        page_links = list(context.get("page_links", []))
        if not page_links:
            html = str(context.get("html") or "")
            soup = BeautifulSoup(html, "html.parser")
            for anchor in soup.find_all("a", href=True):
                href = str(anchor.get("href") or "")
                if not href.startswith("/wiki/"):
                    continue
                title = href.removeprefix("/wiki/")
                if ":" in title:
                    continue
                page_links.append(title.replace("_", " "))

        for title in page_links:
            slug = title.replace(" ", "_")
            accepted.append(
                DiscoveryCandidate(
                    platform="wikipedia",
                    resource_type="article",
                    canonical_url=f"https://en.wikipedia.org/wiki/{slug}",
                    seed_url=seed.canonical_url,
                    fields={"title": slug},
                    discovery_mode=DiscoveryMode.API_LOOKUP,
                    score=0.8,
                    score_breakdown={"api_lookup": 0.8},
                    hop_depth=1,
                    parent_url=seed.canonical_url,
                    metadata={},
                )
            )

        return MapResult(accepted=accepted, rejected=[], exhausted=True, next_seeds=[])

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
            raise TypeError("wikipedia crawl expected fetched payload as dict or to_legacy_dict()")

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
                "page_links": context.get("page_links", []),
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
            if spawned.canonical_url
            and urlparse(spawned.canonical_url).hostname == urlparse(candidate.canonical_url).hostname
        ]
        return {
            "candidate": candidate,
            "fetched": fetched,
            "spawned_candidates": spawned_candidates,
        }
