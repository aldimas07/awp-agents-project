from __future__ import annotations

from .amazon import ADAPTER as AMAZON
from .arxiv import ADAPTER as ARXIV
from .base import PlatformAdapter
from .base_chain import ADAPTER as BASE
from .generic import ADAPTER as GENERIC
from .linkedin import ADAPTER as LINKEDIN
from .wikipedia import ADAPTER as WIKIPEDIA


REGISTRY: dict[str, PlatformAdapter] = {
    WIKIPEDIA.platform: WIKIPEDIA,
    ARXIV.platform: ARXIV,
    AMAZON.platform: AMAZON,
    BASE.platform: BASE,
    GENERIC.platform: GENERIC,
    LINKEDIN.platform: LINKEDIN,
}


def get_platform_adapter(platform: str) -> PlatformAdapter:
    adapter = REGISTRY.get(platform)
    if adapter is None:
        available = ", ".join(sorted(REGISTRY.keys()))
        raise ValueError(f"unknown platform {platform!r}; available: {available}")
    return adapter


def list_platform_adapters() -> tuple[PlatformAdapter, ...]:
    return tuple(REGISTRY.values())
