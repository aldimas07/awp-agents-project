from __future__ import annotations

from dataclasses import replace
import re
from typing import Any
from urllib.parse import urljoin, urlparse, urlunparse

from bs4 import BeautifulSoup

from crawler.discovery.adapters.base import BaseDiscoveryAdapter
from crawler.discovery.contracts import (
    DiscoveryCandidate,
    DiscoveryMode,
    DiscoveryRecord,
    MapOptions,
)
from crawler.discovery.map_engine import MapResult


class GenericDiscoveryAdapter(BaseDiscoveryAdapter):
    platform = "generic"
    supported_resource_types = ("page", "article", "listing", "document")

    def can_handle_url(self, url: str) -> bool:
        return url.startswith("http://") or url.startswith("https://")

    def build_seed_records(self, input_record: dict[str, object]) -> list[DiscoveryRecord]:
        url = str(input_record.get("url") or input_record.get("canonical_url") or "")
        if not url:
            raise KeyError("url")
        return [
            DiscoveryRecord(
                platform=self.platform,
                resource_type=str(input_record.get("resource_type") or "page"),
                discovery_mode=DiscoveryMode.DIRECT_INPUT,
                canonical_url=url,
                identity={"url": url},
                source_seed=input_record,
                discovered_from=None,
                metadata={},
            )
        ]

    async def map(self, seed: DiscoveryRecord, context: dict[str, object]) -> MapResult:
        html = str(context.get("html") or "")
        options = context.get("options")
        if not isinstance(options, MapOptions):
            options = MapOptions()
        if options.limit <= 0:
            return MapResult(accepted=[], rejected=[], exhausted=True, next_seeds=[])

        soup = BeautifulSoup(html, "html.parser")
        seed_host = urlparse(seed.canonical_url).hostname
        accepted: list[DiscoveryCandidate] = []
        seen_urls: set[str] = set()

        for anchor in soup.find_all("a", href=True):
            href = str(anchor.get("href") or "").strip()
            if not href:
                continue

            candidate_url = urljoin(seed.canonical_url, href)
            parsed = urlparse(candidate_url)
            if parsed.scheme not in {"http", "https"}:
                continue

            candidate_host = parsed.hostname
            is_same_host = candidate_host is not None and candidate_host == seed_host
            is_allowed_subdomain = (
                options.include_subdomains
                and candidate_host is not None
                and seed_host is not None
                and candidate_host.endswith(f".{seed_host}")
            )
            if not options.allow_external_links and not (is_same_host or is_allowed_subdomain):
                continue

            if not _is_allowed_generic_candidate(parsed):
                continue

            normalized_url = candidate_url
            if options.ignore_query_parameters:
                normalized_url = urlunparse(parsed._replace(query="", fragment=""))

            if normalized_url in seen_urls:
                continue
            seen_urls.add(normalized_url)

            accepted.append(
                DiscoveryCandidate(
                    platform=self.platform,
                    resource_type="page",
                    canonical_url=normalized_url,
                    seed_url=seed.canonical_url,
                    fields={},
                    discovery_mode=DiscoveryMode.PAGE_LINKS,
                    score=0.3,
                    score_breakdown={"domain_trust": 0.3},
                    hop_depth=1,
                    parent_url=seed.canonical_url,
                    metadata={"anchor_text": anchor.get_text(" ", strip=True)},
                )
            )

            if len(accepted) >= options.limit:
                break

        return MapResult(accepted=accepted, rejected=[], exhausted=True, next_seeds=[])

    async def crawl(self, candidate: DiscoveryCandidate, context: dict[str, object]) -> Any:
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
            raise TypeError("generic crawl expected fetched payload as dict or to_legacy_dict()")

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
                "html": fetched.get("html", ""),
                "options": context.get("options"),
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


def _is_allowed_generic_candidate(parsed: Any) -> bool:
    host = (parsed.hostname or "").lower()
    path = (parsed.path or "").lower().rstrip("/")
    if host == "arxiv.org" or host.endswith(".arxiv.org"):
        if path.startswith("/abs/") or path.startswith("/pdf/"):
            return True
        if re.match(r"^/list/[^/]+/(recent|new)$", path):
            return True
        return False
    return True
