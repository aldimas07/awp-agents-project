"""Data structures for the Extract Pipeline."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class ContentChunk:
    chunk_id: str                       # "{doc_id}#chunk_{index}"
    chunk_index: int
    text: str
    markdown: str
    section_path: list[str]             # ["About", "Company Overview"]
    heading_text: str | None
    heading_level: int | None
    char_offset_start: int
    char_offset_end: int
    source_element: str | None
    token_count_estimate: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "chunk_id": self.chunk_id,
            "chunk_index": self.chunk_index,
            "text": self.text,
            "markdown": self.markdown,
            "section_path": self.section_path,
            "heading_text": self.heading_text,
            "heading_level": self.heading_level,
            "char_offset_start": self.char_offset_start,
            "char_offset_end": self.char_offset_end,
            "source_element": self.source_element,
            "token_count_estimate": self.token_count_estimate,
        }


@dataclass
class StructuredFields:
    platform: str
    resource_type: str
    title: str | None
    description: str | None
    canonical_url: str
    platform_fields: dict[str, Any] = field(default_factory=dict)
    field_sources: dict[str, str] = field(default_factory=dict)


@dataclass
class ExtractionQuality:
    content_ratio: float                # effective content / raw HTML size
    noise_removed: int                  # number of noise elements removed
    chunking_strategy: str


@dataclass
class CleanedContent:
    html: str
    noise_removed: int
    original_size: int
    cleaned_size: int


@dataclass
class MainContent:
    """Result of main content extraction, holding the identified content element."""
    html: str
    text: str
    markdown: str
    sections: list[ContentSection]
    selector_used: str


@dataclass
class ContentSection:
    heading_text: str | None
    heading_level: int | None
    section_path: list[str]
    html: str
    text: str
    markdown: str
    char_offset_start: int
    char_offset_end: int


@dataclass
class ExtractedDocument:
    doc_id: str
    source_url: str
    platform: str
    resource_type: str
    extracted_at: datetime
    chunks: list[ContentChunk]
    total_chunks: int
    full_text: str
    full_markdown: str
    structured: StructuredFields
    quality: ExtractionQuality
    cleaned_html: str = ""
    parser_metadata: dict[str, Any] = field(default_factory=dict)
    binary_artifacts: dict[str, bytes] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "doc_id": self.doc_id,
            "source_url": self.source_url,
            "platform": self.platform,
            "resource_type": self.resource_type,
            "extracted_at": self.extracted_at.isoformat(),
            "chunks": [
                {
                    "chunk_id": c.chunk_id,
                    "chunk_index": c.chunk_index,
                    "text": c.text,
                    "markdown": c.markdown,
                    "section_path": c.section_path,
                    "heading_text": c.heading_text,
                    "heading_level": c.heading_level,
                    "char_offset_start": c.char_offset_start,
                    "char_offset_end": c.char_offset_end,
                    "source_element": c.source_element,
                    "token_count_estimate": c.token_count_estimate,
                }
                for c in self.chunks
            ],
            "total_chunks": self.total_chunks,
            "full_text": self.full_text,
            "full_markdown": self.full_markdown,
            "cleaned_html": self.cleaned_html,
            "parser_metadata": self.parser_metadata,
            "structured": {
                "platform": self.structured.platform,
                "resource_type": self.structured.resource_type,
                "title": self.structured.title,
                "description": self.structured.description,
                "canonical_url": self.structured.canonical_url,
                "platform_fields": self.structured.platform_fields,
                "field_sources": self.structured.field_sources,
            },
            "quality": {
                "content_ratio": self.quality.content_ratio,
                "noise_removed": self.quality.noise_removed,
                "chunking_strategy": self.quality.chunking_strategy,
            },
        }
