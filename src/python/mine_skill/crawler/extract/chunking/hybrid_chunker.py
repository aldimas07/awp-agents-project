"""Hybrid chunking strategy: heading-based splitting with greedy paragraph merging."""
from __future__ import annotations

from ..models import ContentChunk, ContentSection, MainContent


def _estimate_tokens(text: str) -> int:
    """Rough token estimate: ~4 chars per token for English, ~2 for CJK-heavy."""
    if not text:
        return 0
    # Simple heuristic: count words + CJK characters
    words = len(text.split())
    cjk_chars = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff" or "\u3000" <= ch <= "\u303f")
    return max(1, words + cjk_chars)


class HybridChunker:
    def __init__(
        self,
        max_chunk_tokens: int = 512,
        min_chunk_tokens: int = 100,
        overlap_tokens: int = 50,
    ):
        self.max_chunk_tokens = max_chunk_tokens
        self.min_chunk_tokens = min_chunk_tokens
        self.overlap_tokens = overlap_tokens

    def chunk(self, main_content: MainContent, doc_id: str = "") -> list[ContentChunk]:
        sections = main_content.sections
        if not sections:
            return self._chunk_plain_text(main_content.text, main_content.markdown, doc_id)

        chunks: list[ContentChunk] = []
        for section in sections:
            if not section.text.strip():
                continue
            section_tokens = _estimate_tokens(section.text)
            if section_tokens <= self.max_chunk_tokens:
                # Small section: output as a single chunk
                chunks.append(self._make_chunk(
                    doc_id=doc_id,
                    index=len(chunks),
                    text=section.text,
                    markdown=section.markdown,
                    section_path=section.section_path,
                    heading_text=section.heading_text,
                    heading_level=section.heading_level,
                    char_offset_start=section.char_offset_start,
                    char_offset_end=section.char_offset_end,
                    source_element="section",
                ))
            else:
                # Large section: split by paragraphs and greedily merge
                sub_chunks = self._split_large_section(section, doc_id, len(chunks))
                chunks.extend(sub_chunks)

        # Merge tiny trailing chunks into the previous one
        chunks = self._merge_tiny_chunks(chunks, doc_id)
        # Re-index
        for i, chunk in enumerate(chunks):
            chunk.chunk_id = f"{doc_id}#chunk_{i}"
            chunk.chunk_index = i

        return chunks

    def _split_large_section(
        self,
        section: ContentSection,
        doc_id: str,
        start_index: int,
    ) -> list[ContentChunk]:
        paragraphs = [p.strip() for p in section.text.split("\n") if p.strip()]
        md_paragraphs = [p.strip() for p in section.markdown.split("\n\n") if p.strip()]

        # If only one paragraph and it's too long, split by sentences/words
        if len(paragraphs) == 1 and _estimate_tokens(paragraphs[0]) > self.max_chunk_tokens:
            paragraphs = self._split_by_words(paragraphs[0])
            md_paragraphs = paragraphs

        # If markdown paragraphs don't align with text paragraphs, just use text
        if len(md_paragraphs) != len(paragraphs):
            md_paragraphs = paragraphs

        chunks: list[ContentChunk] = []
        current_text_parts: list[str] = []
        current_md_parts: list[str] = []
        current_tokens = 0
        char_offset = section.char_offset_start

        for i, (para_text, para_md) in enumerate(zip(paragraphs, md_paragraphs)):
            para_tokens = _estimate_tokens(para_text)

            if current_tokens + para_tokens > self.max_chunk_tokens and current_text_parts:
                # Flush current buffer as a chunk
                text = "\n".join(current_text_parts)
                md = "\n\n".join(current_md_parts)
                chunks.append(self._make_chunk(
                    doc_id=doc_id,
                    index=start_index + len(chunks),
                    text=text,
                    markdown=md,
                    section_path=section.section_path,
                    heading_text=section.heading_text,
                    heading_level=section.heading_level,
                    char_offset_start=char_offset,
                    char_offset_end=char_offset + len(text),
                    source_element="paragraph_group",
                ))
                # Overlap: keep last few tokens worth of text
                overlap_parts = self._compute_overlap(current_text_parts, current_md_parts)
                char_offset = char_offset + len(text) - sum(len(p) for p in overlap_parts[0])
                current_text_parts = list(overlap_parts[0])
                current_md_parts = list(overlap_parts[1])
                current_tokens = sum(_estimate_tokens(p) for p in current_text_parts)

            current_text_parts.append(para_text)
            current_md_parts.append(para_md)
            current_tokens += para_tokens

        # Flush remaining
        if current_text_parts:
            text = "\n".join(current_text_parts)
            md = "\n\n".join(current_md_parts)
            chunks.append(self._make_chunk(
                doc_id=doc_id,
                index=start_index + len(chunks),
                text=text,
                markdown=md,
                section_path=section.section_path,
                heading_text=section.heading_text,
                heading_level=section.heading_level,
                char_offset_start=char_offset,
                char_offset_end=char_offset + len(text),
                source_element="paragraph_group",
            ))

        return chunks

    def _compute_overlap(
        self,
        text_parts: list[str],
        md_parts: list[str],
    ) -> tuple[list[str], list[str]]:
        """Return the last N parts that fit within overlap_tokens."""
        overlap_text: list[str] = []
        overlap_md: list[str] = []
        tokens = 0
        for text, md in zip(reversed(text_parts), reversed(md_parts)):
            t = _estimate_tokens(text)
            if tokens + t > self.overlap_tokens:
                break
            overlap_text.insert(0, text)
            overlap_md.insert(0, md)
            tokens += t
        return overlap_text, overlap_md

    def _merge_tiny_chunks(self, chunks: list[ContentChunk], doc_id: str) -> list[ContentChunk]:
        if len(chunks) <= 1:
            return chunks
        merged: list[ContentChunk] = []
        for chunk in chunks:
            if (
                merged
                and chunk.token_count_estimate < self.min_chunk_tokens
                and merged[-1].token_count_estimate + chunk.token_count_estimate <= self.max_chunk_tokens
                and merged[-1].section_path == chunk.section_path
            ):
                prev = merged[-1]
                merged[-1] = ContentChunk(
                    chunk_id=prev.chunk_id,
                    chunk_index=prev.chunk_index,
                    text=prev.text + "\n" + chunk.text,
                    markdown=prev.markdown + "\n\n" + chunk.markdown,
                    section_path=prev.section_path,
                    heading_text=prev.heading_text,
                    heading_level=prev.heading_level,
                    char_offset_start=prev.char_offset_start,
                    char_offset_end=chunk.char_offset_end,
                    source_element=prev.source_element,
                    token_count_estimate=prev.token_count_estimate + chunk.token_count_estimate,
                )
            else:
                merged.append(chunk)
        return merged

    def _chunk_plain_text(self, text: str, markdown: str, doc_id: str) -> list[ContentChunk]:
        """Fallback for content with no sections: split by paragraphs."""
        if not text.strip():
            return []
        paragraphs = [p.strip() for p in text.split("\n") if p.strip()]
        chunks: list[ContentChunk] = []
        current_parts: list[str] = []
        current_tokens = 0
        offset = 0

        for para in paragraphs:
            para_tokens = _estimate_tokens(para)
            if current_tokens + para_tokens > self.max_chunk_tokens and current_parts:
                chunk_text = "\n".join(current_parts)
                chunks.append(self._make_chunk(
                    doc_id=doc_id,
                    index=len(chunks),
                    text=chunk_text,
                    markdown=chunk_text,
                    section_path=[],
                    heading_text=None,
                    heading_level=None,
                    char_offset_start=offset,
                    char_offset_end=offset + len(chunk_text),
                    source_element="paragraph_group",
                ))
                offset += len(chunk_text)
                current_parts = []
                current_tokens = 0
            current_parts.append(para)
            current_tokens += para_tokens

        if current_parts:
            chunk_text = "\n".join(current_parts)
            chunks.append(self._make_chunk(
                doc_id=doc_id,
                index=len(chunks),
                text=chunk_text,
                markdown=chunk_text,
                section_path=[],
                heading_text=None,
                heading_level=None,
                char_offset_start=offset,
                char_offset_end=offset + len(chunk_text),
                source_element="paragraph_group",
            ))
        return chunks

    def _split_by_words(self, text: str) -> list[str]:
        """Split a long text into segments of ~max_chunk_tokens words each."""
        words = text.split()
        segments: list[str] = []
        current: list[str] = []
        current_tokens = 0
        for word in words:
            word_tokens = _estimate_tokens(word)
            if current_tokens + word_tokens > self.max_chunk_tokens and current:
                segments.append(" ".join(current))
                current = []
                current_tokens = 0
            current.append(word)
            current_tokens += word_tokens
        if current:
            segments.append(" ".join(current))
        return segments

    def _make_chunk(
        self,
        *,
        doc_id: str,
        index: int,
        text: str,
        markdown: str,
        section_path: list[str],
        heading_text: str | None,
        heading_level: int | None,
        char_offset_start: int,
        char_offset_end: int,
        source_element: str | None,
    ) -> ContentChunk:
        return ContentChunk(
            chunk_id=f"{doc_id}#chunk_{index}",
            chunk_index=index,
            text=text,
            markdown=markdown,
            section_path=section_path,
            heading_text=heading_text,
            heading_level=heading_level,
            char_offset_start=char_offset_start,
            char_offset_end=char_offset_end,
            source_element=source_element,
            token_count_estimate=_estimate_tokens(text),
        )
