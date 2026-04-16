from __future__ import annotations

from crawler.discovery.adapters.amazon import AmazonDiscoveryAdapter
from crawler.discovery.adapters.arxiv import ArxivDiscoveryAdapter
from crawler.discovery.adapters.base import BaseDiscoveryAdapter
from crawler.discovery.adapters.base_chain import BaseChainDiscoveryAdapter
from crawler.discovery.adapters.generic import GenericDiscoveryAdapter
from crawler.discovery.adapters.linkedin import LinkedInDiscoveryAdapter
from crawler.discovery.adapters.wikipedia import WikipediaDiscoveryAdapter


_REGISTRY: dict[str, BaseDiscoveryAdapter] = {
    "generic": GenericDiscoveryAdapter(),
    "wikipedia": WikipediaDiscoveryAdapter(),
    "arxiv": ArxivDiscoveryAdapter(),
    "amazon": AmazonDiscoveryAdapter(),
    "base": BaseChainDiscoveryAdapter(),
    "linkedin": LinkedInDiscoveryAdapter(),
}


def get_discovery_adapter(platform: str | None) -> BaseDiscoveryAdapter:
    if platform and platform in _REGISTRY:
        return _REGISTRY[platform]
    return _REGISTRY["generic"]


def list_discovery_adapters() -> tuple[BaseDiscoveryAdapter, ...]:
    return tuple(_REGISTRY.values())
