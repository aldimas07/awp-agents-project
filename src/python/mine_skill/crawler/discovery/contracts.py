from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Literal


class DiscoveryMode(str, Enum):
    DIRECT_INPUT = "direct_input"
    CANONICALIZED_INPUT = "canonicalized_input"
    TEMPLATE_CONSTRUCTION = "template_construction"
    API_LOOKUP = "api_lookup"
    SEARCH_RESULTS = "search_results"
    GRAPH_TRAVERSAL = "graph_traversal"
    PAGE_LINKS = "page_links"
    ARTIFACT_LINK = "artifact_link"
    PAGINATION = "pagination"
    SITEMAP = "sitemap"


@dataclass(frozen=True, slots=True)
class DiscoveryCandidate:
    platform: str
    resource_type: str
    canonical_url: str | None
    seed_url: str | None
    fields: dict[str, str]
    discovery_mode: DiscoveryMode
    score: float
    score_breakdown: dict[str, float]
    hop_depth: int
    metadata: dict[str, Any]
    parent_url: str | None = None


@dataclass(frozen=True, slots=True)
class DiscoveryRecord:
    platform: str
    resource_type: str
    discovery_mode: DiscoveryMode
    canonical_url: str
    identity: dict[str, str]
    source_seed: dict[str, Any] | None = None
    discovered_from: dict[str, Any] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class MapOptions:
    limit: int = 200
    sitemap_mode: Literal["include", "only", "skip"] = "include"
    include_subdomains: bool = False
    allow_external_links: bool = False
    ignore_query_parameters: bool = True
    include_paths: tuple[str, ...] = ()
    exclude_paths: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CrawlOptions(MapOptions):
    max_depth: int = 2
    max_pages: int = 100
    crawl_entire_domain: bool = False
    max_concurrency: int = 4
    delay_seconds: float = 0.0
