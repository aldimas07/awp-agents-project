from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Awaitable, Callable

from crawler.discovery.contracts import DiscoveryCandidate, DiscoveryRecord
from crawler.discovery.expand.base import ExpandResult
from crawler.discovery.normalize.base import NormalizeResult


class BaseDiscoveryAdapter(ABC):
    platform: str
    supported_resource_types: tuple[str, ...]

    @abstractmethod
    def can_handle_url(self, url: str) -> bool:
        raise NotImplementedError

    @abstractmethod
    def build_seed_records(self, input_record: dict[str, Any]) -> list[DiscoveryRecord]:
        raise NotImplementedError

    @abstractmethod
    async def map(self, seed: DiscoveryRecord, context: dict[str, Any]) -> Any:
        raise NotImplementedError

    @abstractmethod
    async def crawl(self, candidate: DiscoveryCandidate, context: dict[str, Any]) -> Any:
        raise NotImplementedError

    # --- Optional methods for BFS graph traversal ---

    def normalize_url(self, url: str) -> NormalizeResult:
        """Normalize URL to canonical form. Override for platform-specific logic."""
        return NormalizeResult(
            entity_type="unknown",
            canonical_url=url,
            original_url=url,
        )

    def discover_from_html(self, html: str, base_url: str) -> list[str]:
        """Extract platform-specific URLs from HTML. Override for deep discovery."""
        return []

    async def expand(
        self,
        candidate: DiscoveryCandidate,
        fetch_fn: Callable[[str], Awaitable[str]],
        options: dict[str, Any] | None = None,
    ) -> ExpandResult:
        """Expand a candidate to discover related URLs. Override for BFS support."""
        return ExpandResult(urls=[], buckets={}, metadata={})
