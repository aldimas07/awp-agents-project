"""URL normalization for discovered links."""

from .base import NormalizeResult
from .amazon import extract_asin, normalize_amazon_url
from .linkedin import discover_from_html, discover_from_html_deep, normalize_linkedin_url

__all__ = [
    "NormalizeResult",
    "normalize_linkedin_url",
    "normalize_amazon_url",
    "extract_asin",
    "discover_from_html",
    "discover_from_html_deep",
]
