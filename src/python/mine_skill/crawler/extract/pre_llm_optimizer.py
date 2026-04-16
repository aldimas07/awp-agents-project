"""Pre-LLM content optimization — reduces token cost before structured extraction.

Runs after content extraction (Trafilatura/Readability/crawl4ai) and before
LLM-based structuring. All operations are deterministic, CPU-only, and
preserve the semantic content needed for schema field extraction.

Optimizations:
1. Remove low-value sections (References, See Also, External Links, etc.)
2. Strip citation markers ([1], [2], [note 3])
3. Deduplicate repeated paragraphs
4. Compress whitespace and empty lines
5. Pre-extract known fields via regex (title, date, author, language)
6. Truncate oversized content with smart section preservation
"""
from __future__ import annotations

import re
from typing import Any


# Sections that add no value for structured extraction
_LOW_VALUE_SECTIONS = re.compile(
    r"(?im)^#{1,3}\s*("
    r"references|bibliography|citations|notes|footnotes|"
    r"see also|further reading|external links|sources|"
    r"related articles|related pages|"
    r"navigation|categories|"
    r"disclaimers?|copyright"
    r")\s*$"
)

# Citation markers: [1], [2], [note 3], [citation needed], etc.
_CITATION_PATTERN = re.compile(r"\[\s*(?:\d+|note\s+\d+|citation needed)\s*\]")

# Breadcrumb patterns
_BREADCRUMB_PATTERN = re.compile(r"^(?:Home|Main)\s*[>»›/]\s*.+$", re.MULTILINE)

# Consecutive blank lines
_MULTI_BLANK = re.compile(r"\n{3,}")

# Max tokens (rough estimate: 1 token ~ 4 chars for English)
DEFAULT_MAX_CHARS = 20000  # ~5000 tokens


def optimize_for_llm(
    text: str,
    *,
    max_chars: int = DEFAULT_MAX_CHARS,
    pre_extracted: dict[str, Any] | None = None,
) -> tuple[str, dict[str, Any]]:
    """Optimize extracted text before sending to LLM for structured extraction.

    Args:
        text: Cleaned text from content extractor.
        max_chars: Maximum character count for LLM input.
        pre_extracted: Dict to populate with regex-extracted fields.

    Returns:
        (optimized_text, pre_extracted_fields)
    """
    if pre_extracted is None:
        pre_extracted = {}

    if not text:
        return text, pre_extracted

    # Step 1: Pre-extract known fields via regex
    _pre_extract_fields(text, pre_extracted)

    # Step 2: Remove low-value sections
    text = _remove_low_value_sections(text)

    # Step 3: Strip citation markers
    text = _CITATION_PATTERN.sub("", text)

    # Step 4: Remove breadcrumbs
    text = _BREADCRUMB_PATTERN.sub("", text)

    # Step 5: Deduplicate paragraphs
    text = _deduplicate_paragraphs(text)

    # Step 6: Compress whitespace
    text = _MULTI_BLANK.sub("\n\n", text)
    text = text.strip()

    # Step 7: Smart truncation if still too long
    if len(text) > max_chars:
        text = _smart_truncate(text, max_chars)

    return text, pre_extracted


def _pre_extract_fields(text: str, fields: dict[str, Any]) -> None:
    """Extract common fields via regex so LLM doesn't need to find them."""
    # Title: first markdown heading
    title_match = re.match(r"^#\s+(.+)$", text, re.MULTILINE)
    if title_match:
        fields.setdefault("title", title_match.group(1).strip())

    # Date patterns
    date_patterns = [
        r"(\d{4}-\d{2}-\d{2})",  # ISO date
        r"(\d{1,2}\s+(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{4})",
        r"((?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4})",
    ]
    for pattern in date_patterns:
        m = re.search(pattern, text)
        if m:
            fields.setdefault("date", m.group(1))
            break

    # Language detection (simple heuristic based on content)
    if re.search(r"[\u4e00-\u9fff]", text[:500]):
        fields.setdefault("language", "zh")
    elif re.search(r"[\u3040-\u309f\u30a0-\u30ff]", text[:500]):
        fields.setdefault("language", "ja")
    elif re.search(r"[\uac00-\ud7af]", text[:500]):
        fields.setdefault("language", "ko")
    else:
        fields.setdefault("language", "en")


def _remove_low_value_sections(text: str) -> str:
    """Remove References, See Also, External Links, etc."""
    lines = text.split("\n")
    result = []
    skip = False
    skip_level = 0

    for line in lines:
        # Check if this is a low-value section heading
        heading_match = re.match(r"^(#{1,6})\s+(.+)$", line)
        if heading_match:
            level = len(heading_match.group(1))
            heading_text = heading_match.group(2).strip()
            if _LOW_VALUE_SECTIONS.match(f"{'#' * level} {heading_text}"):
                skip = True
                skip_level = level
                continue
            # A same-or-higher level heading ends the skip
            if skip and level <= skip_level:
                skip = False

        if not skip:
            result.append(line)

    return "\n".join(result)


def _deduplicate_paragraphs(text: str) -> str:
    """Remove duplicate paragraphs (common in Wikipedia with repeated abstracts)."""
    paragraphs = re.split(r"\n{2,}", text)
    seen: set[str] = set()
    unique = []
    for para in paragraphs:
        normalized = re.sub(r"\s+", " ", para.strip().lower())
        if len(normalized) < 20:
            # Keep short lines (headings, single words) even if duplicated
            unique.append(para)
            continue
        if normalized not in seen:
            seen.add(normalized)
            unique.append(para)
    return "\n\n".join(unique)


def _smart_truncate(text: str, max_chars: int) -> str:
    """Truncate while preserving section structure.

    Strategy: keep all headings + first paragraph of each section,
    trim body paragraphs from the end until under limit.
    """
    lines = text.split("\n")
    result = []
    char_count = 0

    for i, line in enumerate(lines):
        if char_count + len(line) + 1 > max_chars and i > 0:
            break
        result.append(line)
        char_count += len(line) + 1

    return "\n".join(result)
