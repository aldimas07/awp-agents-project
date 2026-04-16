"""Main content identification — finds the primary content area in cleaned HTML."""
from __future__ import annotations

import json
import re
from pathlib import Path

from bs4 import BeautifulSoup, Tag
from markdownify import markdownify as to_markdown

from .models import ContentSection, MainContent

_REFERENCES_DIR = Path(__file__).resolve().parents[1].parent / "references"

_SEMANTIC_TAGS = ["article", "main", "[role=main]"]

_main_content_selectors_cache: dict[str, dict[str, str]] | None = None


def _load_main_content_selectors() -> dict[str, dict[str, str]]:
    global _main_content_selectors_cache
    if _main_content_selectors_cache is not None:
        return _main_content_selectors_cache
    path = _REFERENCES_DIR / "main_content_selectors.json"
    if path.exists():
        _main_content_selectors_cache = json.loads(path.read_text(encoding="utf-8"))
    else:
        _main_content_selectors_cache = {}
    return _main_content_selectors_cache


def _text_density(tag: Tag) -> float:
    """Compute text density = len(text) / len(html). Higher = more content."""
    html_len = len(str(tag))
    if html_len == 0:
        return 0.0
    text_len = len(tag.get_text(strip=True))
    return text_len / html_len


def _find_by_density(soup: BeautifulSoup) -> tuple[Tag | None, str]:
    """Find the element with highest text density among block containers."""
    candidates: list[tuple[float, int, Tag]] = []
    for tag in soup.find_all(["div", "section", "article", "main", "td"]):
        text = tag.get_text(strip=True)
        if len(text) < 100:
            continue
        density = _text_density(tag)
        text_len = len(text)
        # Score: density weighted by text length (prefer larger, denser blocks)
        score = density * text_len
        candidates.append((score, text_len, tag))

    if not candidates:
        return None, "density_fallback"
    candidates.sort(key=lambda x: x[0], reverse=True)
    return candidates[0][2], "density_analysis"


def _extract_sections(container: Tag) -> list[ContentSection]:
    """Split a container into sections by heading tags, preserving hierarchy."""
    headings = container.find_all(re.compile(r"^h[1-6]$"))
    if not headings:
        full_text = container.get_text("\n", strip=True)
        full_md = to_markdown(str(container), heading_style="ATX", bullets="-")
        return [
            ContentSection(
                heading_text=None,
                heading_level=None,
                section_path=[],
                html=str(container),
                text=full_text,
                markdown=full_md,
                char_offset_start=0,
                char_offset_end=len(full_text),
            )
        ]

    sections: list[ContentSection] = []
    full_text = container.get_text("\n", strip=True)
    heading_stack: list[tuple[int, str]] = []

    # Collect text before the first heading as a preamble section
    preamble_parts: list[str] = []
    for sibling in container.children:
        if isinstance(sibling, Tag) and re.match(r"^h[1-6]$", sibling.name or ""):
            break
        if isinstance(sibling, Tag):
            preamble_parts.append(sibling.get_text("\n", strip=True))
        elif isinstance(sibling, str) and sibling.strip():
            preamble_parts.append(sibling.strip())
    preamble_text = "\n".join(part for part in preamble_parts if part)
    if preamble_text:
        preamble_md = to_markdown(
            "".join(str(s) for s in container.children if not (isinstance(s, Tag) and re.match(r"^h[1-6]$", s.name or ""))),
            heading_style="ATX", bullets="-",
        ).split("\n# ")[0]  # Cut at first heading in markdown
        sections.append(
            ContentSection(
                heading_text=None,
                heading_level=None,
                section_path=[],
                html="",
                text=preamble_text,
                markdown=preamble_md.strip(),
                char_offset_start=0,
                char_offset_end=len(preamble_text),
            )
        )

    last_search_offset = 0
    for heading in headings:
        level = int(heading.name[1])
        heading_text = heading.get_text(strip=True)

        # Update heading stack for section_path
        while heading_stack and heading_stack[-1][0] >= level:
            heading_stack.pop()
        heading_stack.append((level, heading_text))
        section_path = [h[1] for h in heading_stack]

        # Gather content after this heading until the next heading of same or higher level
        content_parts: list[str] = []
        content_html_parts: list[str] = []
        sibling = heading.next_sibling
        while sibling is not None:
            if isinstance(sibling, Tag):
                if re.match(r"^h[1-6]$", sibling.name or ""):
                    sibling_level = int(sibling.name[1])
                    if sibling_level <= level:
                        break
                content_parts.append(sibling.get_text("\n", strip=True))
                content_html_parts.append(str(sibling))
            elif isinstance(sibling, str) and sibling.strip():
                content_parts.append(sibling.strip())
                content_html_parts.append(sibling)
            sibling = sibling.next_sibling

        section_text = "\n".join(part for part in content_parts if part)
        section_html = "".join(content_html_parts)
        section_md = to_markdown(
            f"{'#' * level} {heading_text}\n{section_html}",
            heading_style="ATX", bullets="-",
        )

        # Compute char offsets in full_text (search from last known position to handle duplicates)
        offset_start = full_text.find(heading_text, last_search_offset)
        if offset_start < 0:
            offset_start = last_search_offset
        offset_end = offset_start + len(heading_text) + len(section_text)
        last_search_offset = offset_end

        sections.append(
            ContentSection(
                heading_text=heading_text,
                heading_level=level,
                section_path=section_path,
                html=section_html,
                text=section_text,
                markdown=section_md.strip(),
                char_offset_start=offset_start,
                char_offset_end=min(offset_end, len(full_text)),
            )
        )

    return sections


class MainContentExtractor:
    def extract(self, soup: BeautifulSoup, platform: str = "", resource_type: str = "") -> MainContent:
        # Strategy 1: Platform-specific selectors
        selectors = _load_main_content_selectors()
        platform_selectors = selectors.get(platform, {})
        selector = platform_selectors.get(resource_type) or platform_selectors.get("default")

        if selector:
            container = soup.select_one(selector)
            if container:
                return self._build_result(container, f"platform:{selector}")

        # Strategy 2: Semantic HTML tags
        for semantic_selector in _SEMANTIC_TAGS:
            container = soup.select_one(semantic_selector)
            if container and len(container.get_text(strip=True)) > 50:
                return self._build_result(container, f"semantic:{semantic_selector}")

        # Strategy 3: Content density analysis
        container, strategy_name = _find_by_density(soup)
        if container:
            return self._build_result(container, strategy_name)

        # Strategy 4: Fallback to body
        body = soup.find("body")
        if body and isinstance(body, Tag):
            return self._build_result(body, "fallback:body")

        # Last resort: entire soup
        return self._build_result_from_soup(soup)

    def _build_result(self, container: Tag, selector_used: str) -> MainContent:
        full_text = container.get_text("\n", strip=True)
        full_md = to_markdown(str(container), heading_style="ATX", bullets="-")
        sections = _extract_sections(container)
        return MainContent(
            html=str(container),
            text=full_text,
            markdown=full_md,
            sections=sections,
            selector_used=selector_used,
        )

    def _build_result_from_soup(self, soup: BeautifulSoup) -> MainContent:
        full_text = soup.get_text("\n", strip=True)
        full_md = to_markdown(str(soup), heading_style="ATX", bullets="-")
        return MainContent(
            html=str(soup),
            text=full_text,
            markdown=full_md,
            sections=[
                ContentSection(
                    heading_text=None,
                    heading_level=None,
                    section_path=[],
                    html=str(soup),
                    text=full_text,
                    markdown=full_md,
                    char_offset_start=0,
                    char_offset_end=len(full_text),
                )
            ],
            selector_used="fallback:full_document",
        )
