"""Base discovery adapter for basescan entities."""
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

_ADDRESS_RE = re.compile(r"https?://(?:www\.)?basescan\.org/address/(0x[a-fA-F0-9]{40}|0x[a-fA-F0-9]+)", re.I)
_TX_RE = re.compile(r"https?://(?:www\.)?basescan\.org/tx/(0x[a-fA-F0-9]{64}|0x[a-fA-F0-9]+)", re.I)
_TOKEN_RE = re.compile(r"https?://(?:www\.)?basescan\.org/token/(0x[a-fA-F0-9]{40}|0x[a-fA-F0-9]+)", re.I)
_CONTRACT_RE = re.compile(r"https?://(?:www\.)?basescan\.org/address/(0x[a-fA-F0-9]{40}|0x[a-fA-F0-9]+)/#code", re.I)


class BaseChainDiscoveryAdapter(BaseDiscoveryAdapter):
    platform = "base"
    supported_resource_types = ("address", "transaction", "token", "contract")

    def can_handle_url(self, url: str) -> bool:
        return "basescan.org/" in url

    def build_seed_records(self, input_record: dict[str, Any]) -> list[DiscoveryRecord]:
        from crawler.discovery.url_builder import build_seed_records

        return build_seed_records(input_record)

    async def map(self, seed: DiscoveryRecord, context: dict[str, Any]) -> MapResult:
        accepted: list[DiscoveryCandidate] = []
        seen: set[str] = set()

        for discovered_url in context.get("entity_urls", []) or []:
            normalized = self.normalize_url(str(discovered_url))
            if not normalized.canonical_url or normalized.canonical_url in seen:
                continue
            seen.add(normalized.canonical_url)
            accepted.append(
                DiscoveryCandidate(
                    platform=self.platform,
                    resource_type=normalized.entity_type,
                    canonical_url=normalized.canonical_url,
                    seed_url=seed.canonical_url,
                    fields=normalized.identity,
                    discovery_mode=DiscoveryMode.PAGE_LINKS,
                    score=0.6,
                    score_breakdown={"entity_links": 0.6},
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
            raise TypeError("base crawl expected fetched payload as dict or to_legacy_dict()")

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
        map_result = await self.map(seed, {"entity_urls": self.discover_from_html(html, candidate.canonical_url)})
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
        for entity_type, pattern, key in (
            ("contract", _CONTRACT_RE, "contract_address"),
            ("token", _TOKEN_RE, "contract_address"),
            ("transaction", _TX_RE, "tx_hash"),
            ("address", _ADDRESS_RE, "address"),
        ):
            match = pattern.match(raw)
            if match:
                value = match.group(1)
                canonical = f"https://basescan.org/{'tx' if entity_type == 'transaction' else ('token' if entity_type == 'token' else 'address')}/{value}"
                if entity_type == "contract":
                    canonical += "/#code"
                return NormalizeResult(
                    entity_type=entity_type,
                    canonical_url=canonical,
                    identity={key: value},
                    original_url=raw,
                )
        return NormalizeResult(entity_type="unknown", canonical_url="", original_url=raw)

    def discover_from_html(self, html: str, base_url: str) -> list[str]:
        patterns = (
            r"https?://(?:www\.)?basescan\.org/address/0x[a-fA-F0-9]+(?:/#code|#code)?",
            r"https?://(?:www\.)?basescan\.org/tx/0x[a-fA-F0-9]+",
            r"https?://(?:www\.)?basescan\.org/token/0x[a-fA-F0-9]+",
        )
        seen: set[str] = set()
        urls: list[str] = []
        for pattern in patterns:
            for match in re.finditer(pattern, html or "", re.I):
                discovered_url = match.group(0)
                if discovered_url in seen:
                    continue
                seen.add(discovered_url)
                urls.append(discovered_url)
        return urls
