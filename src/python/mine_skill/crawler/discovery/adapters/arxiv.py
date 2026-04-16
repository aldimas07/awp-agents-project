"""arXiv discovery adapter for paper records and related links."""
from __future__ import annotations

import re
from dataclasses import replace
from typing import Any

from crawler.discovery.adapters.base import BaseDiscoveryAdapter
from crawler.discovery.contracts import (
    DiscoveryCandidate,
    DiscoveryMode,
    DiscoveryRecord,
)
from crawler.discovery.map_engine import MapResult
from crawler.discovery.normalize.base import NormalizeResult

_ARXIV_ABS_RE = re.compile(r"https?://(?:www\.)?arxiv\.org/abs/([a-z\-]+/\d{7}|\d{4}\.\d{4,5})(?:v\d+)?/?", re.I)
_ARXIV_LINK_RE = re.compile(r"/abs/([a-z\-]+/\d{7}|\d{4}\.\d{4,5})(?:v\d+)?", re.I)


class ArxivDiscoveryAdapter(BaseDiscoveryAdapter):
    platform = "arxiv"
    supported_resource_types = ("paper",)

    def can_handle_url(self, url: str) -> bool:
        return "arxiv.org/abs/" in url or "arxiv.org/pdf/" in url

    def build_seed_records(self, input_record: dict[str, Any]) -> list[DiscoveryRecord]:
        from crawler.discovery.url_builder import build_seed_records

        return build_seed_records(input_record)

    async def map(self, seed: DiscoveryRecord, context: dict[str, Any]) -> MapResult:
        accepted: list[DiscoveryCandidate] = []
        seen: set[str] = set()

        for paper_url in context.get("paper_urls", []) or []:
            normalized = self.normalize_url(str(paper_url))
            if not normalized.canonical_url or normalized.canonical_url in seen:
                continue
            seen.add(normalized.canonical_url)
            accepted.append(
                DiscoveryCandidate(
                    platform=self.platform,
                    resource_type="paper",
                    canonical_url=normalized.canonical_url,
                    seed_url=seed.canonical_url,
                    fields=normalized.identity,
                    discovery_mode=DiscoveryMode.PAGE_LINKS,
                    score=0.7,
                    score_breakdown={"paper_links": 0.7},
                    hop_depth=1,
                    parent_url=seed.canonical_url,
                    metadata={},
                )
            )

        return MapResult(accepted=accepted, rejected=[], exhausted=True, next_seeds=[])

    async def crawl(self, candidate: DiscoveryCandidate, context: dict[str, Any]) -> Any:
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
            raise TypeError("arxiv crawl expected fetched payload as dict or to_legacy_dict()")

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
        html = str(fetched.get("html") or fetched.get("text") or "")
        map_result = await self.map(seed, {"paper_urls": self.discover_from_html(html, candidate.canonical_url)})
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

    def normalize_url(self, url: str) -> NormalizeResult:
        raw = (url or "").strip()
        match = _ARXIV_ABS_RE.match(raw)
        if not match:
            return NormalizeResult(entity_type="unknown", canonical_url="", original_url=raw)
        arxiv_id = match.group(1)
        return NormalizeResult(
            entity_type="paper",
            canonical_url=f"https://arxiv.org/abs/{arxiv_id}",
            identity={"arxiv_id": arxiv_id},
            original_url=raw,
        )

    def discover_from_html(self, html: str, base_url: str) -> list[str]:
        seen: set[str] = set()
        urls: list[str] = []
        for match in _ARXIV_LINK_RE.finditer(html or ""):
            paper_url = f"https://arxiv.org/abs/{match.group(1)}"
            if paper_url in seen:
                continue
            seen.add(paper_url)
            urls.append(paper_url)
        return urls
