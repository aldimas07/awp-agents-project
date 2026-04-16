"""Amazon discovery adapter for product and search discovery."""
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
from crawler.discovery.normalize.amazon import (
    build_review_url,
    build_seller_url,
    build_product_url,
    extract_asins_from_html,
    extract_review_id,
    extract_seller_id,
    normalize_amazon_url,
)
from crawler.discovery.normalize.base import NormalizeResult


class AmazonDiscoveryAdapter(BaseDiscoveryAdapter):
    """Discovery adapter for Amazon products.

    Handles product discovery from search results and product page links.
    """

    platform = "amazon"
    supported_resource_types = ("product", "seller", "review", "search")

    def can_handle_url(self, url: str) -> bool:
        return "amazon.com" in url or "amazon.co" in url

    def build_seed_records(self, input_record: dict[str, Any]) -> list[DiscoveryRecord]:
        from crawler.discovery.url_builder import build_seed_records

        return build_seed_records(input_record)

    async def map_search_results(
        self, query: str, urls: list[str]
    ) -> MapResult:
        """Promote search result URLs to product candidates.

        Args:
            query: The search query used
            urls: List of product URLs from search results

        Returns:
            MapResult with accepted product candidates
        """
        accepted: list[DiscoveryCandidate] = []

        for url in urls:
            # Extract ASIN from URL (last path segment)
            asin = url.rstrip("/").split("/")[-1]
            accepted.append(
                DiscoveryCandidate(
                    platform="amazon",
                    resource_type="product",
                    canonical_url=url,
                    seed_url=None,
                    fields={"asin": asin},
                    discovery_mode=DiscoveryMode.SEARCH_RESULTS,
                    score=0.7,
                    score_breakdown={"search_results": 0.7},
                    hop_depth=1,
                    parent_url=None,
                    metadata={"query": query},
                )
            )

        return MapResult(accepted=accepted, rejected=[], exhausted=True, next_seeds=[])

    async def map(
        self, seed: DiscoveryRecord, context: dict[str, Any]
    ) -> MapResult:
        """Extract product candidates from an Amazon page."""
        search_urls = list(context.get("search_urls", []))
        seller_urls: list[str] = []
        review_urls: list[str] = []
        if not search_urls:
            html = str(context.get("html") or "")
            soup = BeautifulSoup(html, "html.parser")
            for anchor in soup.find_all("a", href=True):
                href = str(anchor.get("href") or "")
                absolute = urljoin(seed.canonical_url, href)
                if "/dp/" in href or "/gp/product/" in href:
                    search_urls.append(absolute.split("?")[0].rstrip("/"))
                    continue
                if "seller=" in href or "/sp?" in href:
                    seller_urls.append(absolute)
                    continue
                if "/gp/customer-reviews/" in href:
                    review_urls.append(absolute)

            for asin in re.findall(r'"asin"\s*:\s*"([A-Z0-9]{10})"', html):
                search_urls.append(f"https://www.amazon.com/dp/{asin}")

        accepted: list[DiscoveryCandidate] = []
        if search_urls:
            search_result = await self.map_search_results(
                query=context.get("query", ""),
                urls=list(dict.fromkeys(search_urls)),
            )
            accepted.extend(search_result.accepted)

        for seller_url in dict.fromkeys(seller_urls):
            seller_id = extract_seller_id(seller_url)
            if not seller_id:
                continue
            accepted.append(
                DiscoveryCandidate(
                    platform="amazon",
                    resource_type="seller",
                    canonical_url=build_seller_url(seller_id),
                    seed_url=None,
                    fields={"seller_id": seller_id},
                    discovery_mode=DiscoveryMode.PAGE_LINKS,
                    score=0.65,
                    score_breakdown={"page_links": 0.65},
                    hop_depth=1,
                    parent_url=None,
                    metadata={},
                )
            )

        for review_url in dict.fromkeys(review_urls):
            review_id = extract_review_id(review_url)
            if not review_id:
                continue
            accepted.append(
                DiscoveryCandidate(
                    platform="amazon",
                    resource_type="review",
                    canonical_url=build_review_url(review_id),
                    seed_url=None,
                    fields={"review_id": review_id},
                    discovery_mode=DiscoveryMode.PAGE_LINKS,
                    score=0.65,
                    score_breakdown={"page_links": 0.65},
                    hop_depth=1,
                    parent_url=None,
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
            raise TypeError("amazon crawl expected fetched payload as dict or to_legacy_dict()")

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
        """Normalize an Amazon URL using the migrated normalizer."""
        return normalize_amazon_url(url)

    def discover_from_html(self, html: str, base_url: str) -> list[str]:
        """Extract Amazon product URLs from HTML."""
        asins = extract_asins_from_html(html)
        return [build_product_url(asin) for asin in asins]

    async def expand(
        self,
        candidate: DiscoveryCandidate,
        fetch_fn: Callable[[str], Awaitable[str]],
        options: dict[str, Any] | None = None,
    ) -> ExpandResult:
        """Expand an Amazon product page to discover related products."""
        from crawler.discovery.expand.amazon_product import expand_product
        return await expand_product(candidate.canonical_url, fetch_fn)
