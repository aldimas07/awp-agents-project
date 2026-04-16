"""URL canonicalization module.

Provides normalize_url() to standardize URLs before submission.
Supports both basic normalization and custom regex patterns from dataset schemas.
Wraps lib.canonicalize.canonicalize_url for basic normalization and adds regex support.
"""
from __future__ import annotations

import re

from lib.canonicalize import canonicalize_url as _basic_canonicalize


def normalize_url(url: str, regex_pattern: str | None) -> str:
    """Normalize a URL for canonical storage.

    Args:
        url: The URL to normalize.
        regex_pattern: Optional regex pattern from dataset schema. If provided and
            matches, extracts captured groups to build canonical URL. Falls back
            to basic normalization if pattern doesn't match.

    Returns:
        Normalized URL string.
    """
    if not url:
        return url

    # Try regex normalization first if pattern is provided
    if regex_pattern:
        result = _apply_regex_pattern(url, regex_pattern)
        if result is not None:
            return result

    # Fall back to lib's basic canonicalization
    return _basic_canonicalize(url)


def _apply_regex_pattern(url: str, pattern: str) -> str | None:
    """Apply regex pattern to extract canonical URL.

    Returns canonical URL if pattern matches, None otherwise.
    """
    try:
        match = re.match(pattern, url)
        if not match:
            return None

        groups = match.groups()
        if not groups:
            # Pattern matched but no capture groups - return matched portion
            return match.group(0)

        # Build canonical URL from captured groups
        # Use first non-None group as the identifier
        identifier = next((g for g in groups if g is not None), None)
        if identifier is None:
            return match.group(0)

        # Reconstruct URL using matched prefix and first capture group
        full_match = match.group(0)
        first_group = match.group(1)

        # Find where the first group starts in the match and truncate there + group length
        try:
            group_start = full_match.index(first_group)
            return full_match[: group_start + len(first_group)]
        except ValueError:
            return full_match

    except re.error:
        return None
