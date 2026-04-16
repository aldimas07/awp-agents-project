"""URL discovery helpers for supported platforms."""

from crawler.discovery.bfs_engine import BfsExpandResult, BfsOptions, run_bfs_expand
from crawler.discovery.contracts import CrawlOptions, DiscoveryCandidate, DiscoveryMode

__all__ = [
    "BfsExpandResult",
    "BfsOptions",
    "run_bfs_expand",
    "CrawlOptions",
    "DiscoveryCandidate",
    "DiscoveryMode",
]
