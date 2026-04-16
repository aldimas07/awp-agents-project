"""LLM-ready content compaction for extracted main content."""
from __future__ import annotations

import re

from bs4 import BeautifulSoup, Tag
from markdownify import markdownify as to_markdown

from .main_content import _extract_sections
from .models import ContentSection, MainContent

_BLOCK_TAGS = ("p", "li", "div", "span")
_NOISE_PATTERNS = [
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"^sign in(?:\b| to\b)",
        r"^sign up(?:\b| for\b)",
        r"^share (?:this|the) (?:article|post|page)$",
        r"^all rights reserved\.?$",
        r"^cookie (?:preferences|policy|settings)$",
        r"^accept cookies$",
        r"^subscribe(?: now)?$",
        r"^skip to content$",
    )
]


def _normalize_inline_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _normalize_markdown_block(block: str) -> str:
    lines = [_normalize_inline_text(line) for line in block.splitlines()]
    lines = [line for line in lines if line]
    return "\n".join(lines).strip()


def _markdown_to_text(block: str) -> str:
    lines: list[str] = []
    for line in block.splitlines():
        stripped = line.strip()
        stripped = re.sub(r"^#{1,6}\s+", "", stripped)
        stripped = re.sub(r"^[-*+]\s+", "", stripped)
        stripped = re.sub(r"^\d+\.\s+", "", stripped)
        stripped = stripped.replace("**", "").replace("__", "").replace("`", "")
        if stripped:
            lines.append(stripped)
    return "\n".join(lines).strip()


def _is_noise_text(text: str) -> bool:
    normalized = _normalize_inline_text(text).lower()
    if not normalized:
        return True
    return any(pattern.search(normalized) for pattern in _NOISE_PATTERNS)


def _build_main_content_from_html(html: str, selector_used: str) -> MainContent:
    soup = BeautifulSoup(html, "html.parser")
    container = next((node for node in soup.contents if isinstance(node, Tag)), None)
    if container is None:
        return MainContent(html="", text="", markdown="", sections=[], selector_used=selector_used)
    compact_html = str(container)
    full_text = container.get_text("\n", strip=True)
    full_markdown = to_markdown(compact_html, heading_style="ATX", bullets="-")
    return MainContent(
        html=compact_html,
        text=full_text,
        markdown=full_markdown,
        sections=_extract_sections(container),
        selector_used=selector_used,
    )


class FitContentReducer:
    """Compact extracted content into a denser LLM-ready representation."""

    def reduce(self, main_content: MainContent) -> MainContent:
        if main_content.html.strip():
            return self._reduce_html(main_content)
        return self._reduce_text(main_content)

    def _reduce_html(self, main_content: MainContent) -> MainContent:
        soup = BeautifulSoup(main_content.html, "html.parser")
        container = next((node for node in soup.contents if isinstance(node, Tag)), None)
        if container is None:
            return MainContent(html="", text="", markdown="", sections=[], selector_used=main_content.selector_used)

        seen_blocks: set[str] = set()
        for tag in list(container.find_all(_BLOCK_TAGS)):
            if tag.find(["h1", "h2", "h3", "h4", "h5", "h6", "ul", "ol"]):
                continue
            text = _normalize_inline_text(tag.get_text(" ", strip=True))
            if _is_noise_text(text):
                tag.decompose()
                continue
            if tag.name in {"p", "li"} and len(text) >= 24:
                key = text.lower()
                if key in seen_blocks:
                    tag.decompose()
                    continue
                seen_blocks.add(key)

        for tag in list(container.find_all(_BLOCK_TAGS)):
            if not tag.get_text(" ", strip=True):
                tag.decompose()

        return _build_main_content_from_html(str(container), main_content.selector_used)

    def _reduce_text(self, main_content: MainContent) -> MainContent:
        sections = main_content.sections or [
            ContentSection(
                heading_text=None,
                heading_level=None,
                section_path=[],
                html="",
                text=main_content.text,
                markdown=main_content.markdown,
                char_offset_start=0,
                char_offset_end=len(main_content.text),
            )
        ]
        reduced_sections: list[ContentSection] = []
        offset = 0

        for section in sections:
            markdown_blocks = [
                _normalize_markdown_block(block)
                for block in section.markdown.split("\n\n")
                if _normalize_markdown_block(block)
            ]
            kept_markdown: list[str] = []
            seen_blocks: set[str] = set()
            for block in markdown_blocks:
                block_text = _markdown_to_text(block)
                if _is_noise_text(block_text):
                    continue
                key = block_text.lower()
                if len(block_text) >= 24 and key in seen_blocks:
                    continue
                if len(block_text) >= 24:
                    seen_blocks.add(key)
                kept_markdown.append(block)

            reduced_markdown = "\n\n".join(kept_markdown).strip()
            reduced_text = "\n".join(
                line for line in (_markdown_to_text(block) for block in kept_markdown) if line
            ).strip()
            if not reduced_text:
                continue

            reduced_sections.append(
                ContentSection(
                    heading_text=section.heading_text,
                    heading_level=section.heading_level,
                    section_path=section.section_path,
                    html="",
                    text=reduced_text,
                    markdown=reduced_markdown or reduced_text,
                    char_offset_start=offset,
                    char_offset_end=offset + len(reduced_text),
                )
            )
            offset += len(reduced_text) + 2

        full_text = "\n\n".join(section.text for section in reduced_sections).strip()
        full_markdown = "\n\n".join(section.markdown for section in reduced_sections).strip()
        return MainContent(
            html="",
            text=full_text,
            markdown=full_markdown,
            sections=reduced_sections,
            selector_used=main_content.selector_used,
        )
