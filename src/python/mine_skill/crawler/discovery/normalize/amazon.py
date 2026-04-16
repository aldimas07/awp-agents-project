"""Amazon URL normalization and identity extraction."""

from __future__ import annotations

import re
from urllib.parse import parse_qs, urlparse

from .base import NormalizeResult

# ------------------------------------------------------------------
# ASIN patterns
# ------------------------------------------------------------------

# Bare ASIN: 10 uppercase-alphanumeric characters
ASIN_PATTERN = re.compile(r"\b([A-Z0-9]{10})\b")

# Product URL variants (capture group = ASIN)
PRODUCT_URL_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"amazon\.[a-z.]+/dp/([A-Z0-9]{10})", re.IGNORECASE),
    re.compile(r"amazon\.[a-z.]+/gp/product/([A-Z0-9]{10})", re.IGNORECASE),
    re.compile(r"amazon\.[a-z.]+/[^/]+/dp/([A-Z0-9]{10})", re.IGNORECASE),
    re.compile(r"amazon\.[a-z.]+/exec/obidos/ASIN/([A-Z0-9]{10})", re.IGNORECASE),
]

SELLER_ID_PATTERN = re.compile(r"\b([A-Z0-9]{10,20})\b")
REVIEW_ID_PATTERN = re.compile(r"/gp/customer-reviews/([A-Z0-9]+)", re.IGNORECASE)

# data-asin HTML attribute
DATA_ASIN_PATTERN = re.compile(
    r'data-asin=["\']([A-Z0-9]{10})["\']', re.IGNORECASE
)

# ------------------------------------------------------------------
# Utility functions
# ------------------------------------------------------------------


def extract_asin(url: str) -> str | None:
    """Return the ASIN embedded in *url*, or ``None``."""
    for pattern in PRODUCT_URL_PATTERNS:
        m = pattern.search(url)
        if m:
            return m.group(1).upper()
    return None


def build_product_url(asin: str) -> str:
    """Build the canonical ``/dp/{ASIN}`` product URL."""
    return f"https://www.amazon.com/dp/{asin.upper()}"


def build_seller_url(seller_id: str) -> str:
    """Build the canonical ``/sp?seller={SELLER_ID}`` seller URL."""
    return f"https://www.amazon.com/sp?seller={seller_id.upper()}"


def build_review_url(review_id: str) -> str:
    """Build the canonical ``/gp/customer-reviews/{REVIEW_ID}`` review URL."""
    return f"https://www.amazon.com/gp/customer-reviews/{review_id.upper()}"


def is_valid_asin(asin: str) -> bool:
    """Check whether *asin* looks like a valid 10-char ASIN."""
    if not asin or len(asin) != 10:
        return False
    return bool(re.match(r"^[A-Z0-9]{10}$", asin.upper()))


def _extract_marketplace(raw: str) -> str | None:
    hostname = (urlparse(raw).hostname or "").lower()
    match = re.search(r"amazon\.([a-z.]+)$", hostname)
    if not match:
        return None
    return match.group(1)


def extract_seller_id(url: str) -> str | None:
    """Return the Amazon seller ID embedded in *url*, or ``None``."""
    parsed = urlparse(url)
    for key in ("seller", "merchant", "me"):
        candidate = parse_qs(parsed.query).get(key, [None])[0]
        if candidate and SELLER_ID_PATTERN.fullmatch(candidate):
            return candidate.upper()
    return None


def extract_review_id(url: str) -> str | None:
    """Return the Amazon review ID embedded in *url*, or ``None``."""
    match = REVIEW_ID_PATTERN.search(url)
    if not match:
        return None
    return match.group(1).upper()


def extract_asins_from_html(html: str) -> set[str]:
    """Extract every valid ASIN found in *html* (URLs + ``data-asin`` attrs)."""
    asins: set[str] = set()

    for pattern in PRODUCT_URL_PATTERNS:
        for m in pattern.finditer(html):
            asins.add(m.group(1).upper())

    for m in DATA_ASIN_PATTERN.finditer(html):
        asins.add(m.group(1).upper())

    return {a for a in asins if is_valid_asin(a)}


# ------------------------------------------------------------------
# URL normalization
# ------------------------------------------------------------------


def normalize_amazon_url(url: str) -> NormalizeResult:
    """Normalize an Amazon product URL into a canonical ``/dp/{ASIN}`` form.

    Returns a :class:`NormalizeResult` with ``entity_type="product"`` when
    an ASIN can be extracted, or ``entity_type="unknown"`` otherwise.
    """
    raw = (url or "").strip()
    if not raw:
        return NormalizeResult(
            entity_type="unknown",
            canonical_url="",
            original_url=raw,
            notes=("empty_input",),
        )

    marketplace = _extract_marketplace(raw)

    seller_id = extract_seller_id(raw)
    if seller_id is not None:
        identity = {"seller_id": seller_id}
        if marketplace:
            identity["marketplace"] = marketplace
        return NormalizeResult(
            entity_type="seller",
            canonical_url=build_seller_url(seller_id),
            identity=identity,
            original_url=raw,
        )

    review_id = extract_review_id(raw)
    if review_id is not None:
        identity = {"review_id": review_id}
        if marketplace:
            identity["marketplace"] = marketplace
        return NormalizeResult(
            entity_type="review",
            canonical_url=build_review_url(review_id),
            identity=identity,
            original_url=raw,
        )

    asin = extract_asin(raw)
    if asin is not None:
        identity = {"asin": asin}
        if marketplace:
            identity["marketplace"] = marketplace
        return NormalizeResult(
            entity_type="product",
            canonical_url=build_product_url(asin),
            identity=identity,
            original_url=raw,
        )

    return NormalizeResult(
        entity_type="unknown",
        canonical_url="",
        original_url=raw,
        notes=("no_supported_identity_found",),
    )
