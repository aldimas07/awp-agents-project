"""Amazon product page expander — discovers related ASINs.

Fetches an Amazon product page and extracts related ASINs from
"frequently bought together", "customers also viewed", "compare
with similar items", and sponsored products sections.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from crawler.discovery.normalize.amazon import (
    build_product_url,
    extract_asin,
    extract_asins_from_html,
)

from .base import ExpandResult


async def expand_product(
    url: str,
    fetch_fn: Callable[[str], Awaitable[str]],
) -> ExpandResult:
    """Expand Amazon product page to discover related ASINs.

    Extracts ASINs from:
    - Frequently bought together
    - Customers who viewed this also viewed
    - Compare with similar items
    - Sponsored products

    Parameters
    ----------
    url:
        Amazon product URL (any recognized format: ``/dp/``,
        ``/gp/product/``, ``/exec/obidos/ASIN/``, etc.).
    fetch_fn:
        Async callable ``(url) -> html``.  The caller is responsible
        for rate-limiting and retries.

    Returns
    -------
    ExpandResult
        ``urls``  – canonical ``/dp/{ASIN}`` URLs for every discovered product.
        ``buckets`` – ``{"products": [...]}``.
        ``metadata`` – ``{"source_asin": ..., "discovered_count": ...}``.
    """
    source_asin = extract_asin(url)
    if source_asin is None:
        return ExpandResult(
            metadata={"source_asin": None, "discovered_count": 0, "error": "no_asin_in_url"},
        )

    canonical = build_product_url(source_asin)
    html = await fetch_fn(canonical)

    if not html:
        return ExpandResult(
            metadata={"source_asin": source_asin, "discovered_count": 0, "error": "empty_response"},
        )

    found_asins = extract_asins_from_html(html)
    found_asins.discard(source_asin)

    product_urls = sorted(build_product_url(asin) for asin in found_asins)

    return ExpandResult(
        urls=product_urls,
        buckets={"products": product_urls},
        metadata={"source_asin": source_asin, "discovered_count": len(product_urls)},
    )
