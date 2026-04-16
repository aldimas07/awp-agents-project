"""Extract Pipeline — main entry point for content extraction.

Routes fetch results through cleaning, main content extraction, chunking,
and structured field extraction to produce LLM-ready ExtractedDocument output.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

import httpx
from bs4 import Tag
from markdownify import markdownify as to_markdown

from .chunking.hybrid_chunker import HybridChunker, _estimate_tokens
from .crawl4ai_extract import extract_html_with_crawl4ai
from .pre_llm_optimizer import optimize_for_llm
from .trafilatura_extract import extract_with_trafilatura
from .html_parse import parse_html
from .fit_content import FitContentReducer
from .main_content import _extract_sections
from .models import (
    ContentChunk,
    ContentSection,
    ExtractedDocument,
    ExtractionQuality,
    MainContent,
    StructuredFields,
)
from .pymupdf4llm_extract import extract_pdf_with_pymupdf4llm
from .structured.css_extractor import CssExtractionStrategy
from .structured.json_extractor import JsonExtractor
from .structured.llm_schema_extractor import LLMSchemaExtractor


def fetch_binary_content(url: str) -> bytes:
    with httpx.Client(follow_redirects=True, timeout=60.0) as client:
        response = client.get(url)
        response.raise_for_status()
        return response.content


def _strip_latex(text: str | None) -> str | None:
    if text is None:
        return None
    cleaned = re.sub(r"\\[a-zA-Z]+\{([^{}]+)\}", r"\1", text)
    cleaned = re.sub(r"[${}]", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned or None


def _split_author_name(name: str) -> tuple[str, str]:
    parts = [part for part in re.split(r"\s+", name.strip()) if part]
    if not parts:
        return "", ""
    if len(parts) == 1:
        return parts[0], ""
    return parts[0], parts[-1]


def _category_to_plain_english(category: str | None) -> str | None:
    if not category:
        return None
    mapping = {
        "cs.CL": "Natural language processing",
        "cs.AI": "Artificial intelligence",
        "cs.LG": "Machine learning",
        "stat.ML": "Statistical machine learning",
    }
    return mapping.get(category, category)


def _category_to_hierarchy(categories: list[str], primary_category: str | None) -> list[str]:
    if not categories and not primary_category:
        return []
    seed = primary_category or (categories[0] if categories else "")
    top = seed.split(".", 1)[0] if seed else ""
    plain = _category_to_plain_english(seed)
    return [value for value in [top, seed, plain] if value]


def _extract_sections_from_markdown(markdown: str) -> list[dict[str, Any]]:
    sections: list[dict[str, Any]] = []
    matches = list(re.finditer(r"(?m)^(#{1,6})\s+(.+)$", markdown))
    if not matches:
        if markdown.strip():
            sections.append({
                "heading": "Main",
                "content_summary": markdown.strip().split("\n", 1)[0][:240],
                "section_type": "body",
            })
        return sections
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(markdown)
        heading = match.group(2).strip()
        body = markdown[start:end].strip()
        heading_lower = heading.lower()
        section_type = "body"
        for key, value in (
            ("introduction", "introduction"),
            ("related work", "related_work"),
            ("method", "methodology"),
            ("experiment", "experiment"),
            ("result", "results"),
            ("discussion", "discussion"),
            ("conclusion", "conclusion"),
            ("reference", "references"),
        ):
            if key in heading_lower:
                section_type = value
                break
        sections.append({
            "heading": heading,
            "content_summary": body.split("\n", 1)[0][:240] if body else "",
            "section_type": section_type,
        })
    return sections


def _extract_references(markdown: str) -> list[str]:
    ref_match = re.search(r"(?ims)^##?\s*references\s*$([\s\S]+)$", markdown)
    if not ref_match:
        return []
    block = ref_match.group(1)
    refs = []
    for line in block.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("[") or re.match(r"^\d+\.", stripped):
            refs.append(stripped)
    return refs


def _extract_urls(text: str) -> list[str]:
    return sorted(set(re.findall(r"https?://[^\s)>\]]+", text)))


def _extract_arxiv_ids(text: str) -> list[str]:
    return sorted(set(re.findall(r"\b\d{4}\.\d{4,5}(?:v\d+)?\b", text)))


def _extract_arxiv_versions(entry_id: str | None) -> list[str]:
    if not entry_id:
        return []
    match = re.search(r"v(\d+)$", entry_id)
    if match is None:
        return ["v1"]
    latest_version = int(match.group(1))
    if latest_version <= 0:
        return []
    return [f"v{index}" for index in range(1, latest_version + 1)]


def _estimate_figure_count(markdown: str, plain_text: str) -> int:
    numbered_figures: set[str] = set()
    for source in (markdown, plain_text):
        for match in re.findall(r"(?im)\b(?:figure|fig\.?)\s*(\d+)\b", source):
            numbered_figures.add(match)
    if numbered_figures:
        return len(numbered_figures)
    image_markers = re.findall(r"!\[[^\]]*\]\([^)]+\)", markdown)
    return len(image_markers)


def _generate_doc_id(url: str, platform: str) -> str:
    """Generate a deterministic doc_id from URL and platform."""
    hash_input = f"{platform}:{url}".encode("utf-8")
    return hashlib.sha256(hash_input).hexdigest()[:16]


def _extract_sections_from_main_content(text: str) -> list[ContentSection]:
    """Build sections from plain text extracted by Trafilatura."""
    sections: list[ContentSection] = []
    if not text.strip():
        return sections
    # Split on double newlines as paragraph boundaries
    paragraphs = [p.strip() for p in re.split(r"\n{2,}", text) if p.strip()]
    if not paragraphs:
        return sections
    # Single section for the whole content
    sections.append(ContentSection(
        heading_text="Main",
        heading_level=1,
        section_path=["Main"],
        html="",
        text=text,
        markdown="",
        char_offset_start=0,
        char_offset_end=len(text),
    ))
    return sections


def _build_main_content_from_html(html: str, selector_used: str) -> MainContent:
    soup = parse_html(html)
    container = next((node for node in soup.contents if isinstance(node, Tag)), None)
    if container is None:
        return MainContent(html="", text="", markdown="", sections=[], selector_used=selector_used)

    container_html = str(container)
    return MainContent(
        html=container_html,
        text=container.get_text("\n", strip=True),
        markdown=to_markdown(container_html, heading_style="ATX", bullets="-"),
        sections=_extract_sections(container),
        selector_used=selector_used,
    )


class ExtractPipeline:
    def __init__(
        self,
        max_chunk_tokens: int = 512,
        min_chunk_tokens: int = 100,
        overlap_tokens: int = 50,
        css_schema_path: Path | None = None,
        extract_llm_schema_path: Path | None = None,
        model_config: dict[str, Any] | None = None,
    ):
        self.reducer = FitContentReducer()
        self.chunker = HybridChunker(
            max_chunk_tokens=max_chunk_tokens,
            min_chunk_tokens=min_chunk_tokens,
            overlap_tokens=overlap_tokens,
        )
        self.json_extractor = JsonExtractor()
        self.css_extractor = CssExtractionStrategy(css_schema_path) if css_schema_path is not None else None
        self.llm_schema_extractor = LLMSchemaExtractor(extract_llm_schema_path, model_config or {}) if extract_llm_schema_path is not None else None

    def extract(
        self,
        fetch_result: dict[str, Any],
        platform: str,
        resource_type: str,
    ) -> ExtractedDocument:
        """Extract structured content from a fetch result.

        Handles two branches:
        - API JSON: structured extraction + text generation + chunking
        - HTML: cleaning -> main content identification -> chunking -> structured extraction
        """
        url = fetch_result.get("url", "")
        doc_id = _generate_doc_id(url, platform)
        json_data = fetch_result.get("json_data")
        content_type = str(fetch_result.get("content_type") or "").lower()

        if json_data is not None:
            return self._extract_from_json(
                json_data=json_data,
                fetch_result=fetch_result,
                platform=platform,
                resource_type=resource_type,
                url=url,
                doc_id=doc_id,
            )
        if "xml" in content_type:
            return self._extract_from_xml(
                fetch_result=fetch_result,
                platform=platform,
                resource_type=resource_type,
                url=url,
                doc_id=doc_id,
            )

        return self._extract_from_html(
            fetch_result=fetch_result,
            platform=platform,
            resource_type=resource_type,
            url=url,
            doc_id=doc_id,
        )

    def _extract_from_json(
        self,
        *,
        json_data: dict[str, Any],
        fetch_result: dict[str, Any],
        platform: str,
        resource_type: str,
        url: str,
        doc_id: str,
    ) -> ExtractedDocument:
        """Branch 1: API JSON -> structured extraction + text generation + chunking."""
        extracted = self.json_extractor.extract_document_from_json(
            json_data=json_data,
            platform=platform,
            resource_type=resource_type,
            canonical_url=url,
            content_type=fetch_result.get("content_type"),
        )
        structured = extracted["structured"]
        full_text = extracted["plain_text"]
        full_markdown = extracted["markdown"]

        # Create sections from structured data for chunking
        sections: list[ContentSection] = []
        if full_text or full_markdown or structured.title or structured.description:
            sections.append(ContentSection(
                heading_text=structured.title,
                heading_level=1,
                section_path=[structured.title or "Main"],
                html="",
                text=full_text,
                markdown=full_markdown,
                char_offset_start=0,
                char_offset_end=len(full_text),
            ))

        main_content = MainContent(
            html="",
            text=full_text,
            markdown=full_markdown,
            sections=sections,
            selector_used="api_json",
        )
        reduced_content = self.reducer.reduce(main_content)

        chunks = self.chunker.chunk(reduced_content, doc_id=doc_id)

        # Quality metrics for JSON extraction
        raw_size = len(json.dumps(json_data, default=str))
        content_size = len(reduced_content.text)
        quality = ExtractionQuality(
            content_ratio=content_size / max(raw_size, 1),
            noise_removed=0,
            chunking_strategy="json_structured",
        )

        return ExtractedDocument(
            doc_id=doc_id,
            source_url=url,
            platform=platform,
            resource_type=resource_type,
            extracted_at=datetime.now(timezone.utc),
            chunks=chunks,
            total_chunks=len(chunks),
            full_text=reduced_content.text,
            full_markdown=reduced_content.markdown,
            structured=structured,
            quality=quality,
            cleaned_html="",
        )

    def _extract_from_xml(
        self,
        *,
        fetch_result: dict[str, Any],
        platform: str,
        resource_type: str,
        url: str,
        doc_id: str,
    ) -> ExtractedDocument:
        xml_text = (
            fetch_result.get("text")
            or fetch_result.get("html")
            or (fetch_result.get("content_bytes", b"") or b"").decode("utf-8", "ignore")
        )
        if platform != "arxiv":
            return self._extract_from_html(
                fetch_result=fetch_result,
                platform=platform,
                resource_type=resource_type,
                url=url,
                doc_id=doc_id,
            )

        root = ET.fromstring(xml_text.encode("utf-8"))
        ns = {
            "atom": "http://www.w3.org/2005/Atom",
            "arxiv": "http://arxiv.org/schemas/atom",
        }
        entry = root.find("atom:entry", ns)
        if entry is None:
            return self._extract_from_html(
                fetch_result=fetch_result,
                platform=platform,
                resource_type=resource_type,
                url=url,
                doc_id=doc_id,
            )

        def text_or_none(path: str) -> str | None:
            node = entry.find(path, ns)
            if node is None or node.text is None:
                return None
            text = " ".join(node.text.split()).strip()
            return text or None

        title = text_or_none("atom:title")
        summary = text_or_none("atom:summary")
        authors = [
            " ".join((node.text or "").split()).strip()
            for node in entry.findall("atom:author/atom:name", ns)
            if (node.text or "").strip()
        ]
        doi = text_or_none("arxiv:doi")
        categories = [
            term.strip()
            for node in entry.findall("atom:category", ns)
            for term in [node.attrib.get("term", "")]
            if term.strip()
        ]
        primary_category = None
        primary_category_node = entry.find("arxiv:primary_category", ns)
        if primary_category_node is not None:
            primary_category = (primary_category_node.attrib.get("term") or "").strip() or None
        pdf_url = None
        for link in entry.findall("atom:link", ns):
            if (link.attrib.get("type") or "").strip() == "application/pdf":
                pdf_url = (link.attrib.get("href") or "").strip() or None
                break

        pdf_markdown = ""
        pdf_text = ""
        pdf_document_blocks: list[dict[str, Any]] = []
        parser_metadata: dict[str, Any] = {}
        page_count = None
        num_figures = None
        pdf_bytes = None
        if pdf_url:
            try:
                pdf_bytes = fetch_binary_content(pdf_url)
            except Exception as pdf_exc:
                parser_metadata = {"pdf_fetch_error": str(pdf_exc)}
        if pdf_bytes:
            import tempfile

            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                tmp.write(pdf_bytes)
                tmp_path = Path(tmp.name)
            try:
                pdf_result = extract_pdf_with_pymupdf4llm(str(tmp_path), title=title)
            except Exception as exc:
                pdf_result = {}
                parser_metadata = {"pdf_extraction_error": str(exc)}
            finally:
                tmp_path.unlink(missing_ok=True)
            pdf_markdown = str(pdf_result.get("markdown") or "")
            pdf_text = str(pdf_result.get("plain_text") or "")
            pdf_document_blocks = list(pdf_result.get("document_blocks") or [])
            parser_metadata.update(dict(pdf_result.get("parser_metadata") or {}))
            page_count = pdf_result.get("page_count")
            num_figures = _estimate_figure_count(pdf_markdown, pdf_text)
        full_text = pdf_text or summary or ""
        preamble = f"# {title}\n\n## Abstract\n\n{summary}".strip() if title or summary else ""
        body_markdown = pdf_markdown.strip()
        full_markdown = "\n\n".join(part for part in [preamble, body_markdown] if part).strip()
        sections_structured = _extract_sections_from_markdown(full_markdown)
        references = _extract_references(full_markdown)
        project_urls = _extract_urls(full_markdown)
        github_urls = [url for url in project_urls if "github.com" in url.lower()]
        dataset_urls = [url for url in project_urls if "github.com" not in url.lower()]
        normalized_title = _strip_latex(title)
        normalized_abstract = _strip_latex(summary)
        authors_structured = []
        for author in authors:
            first_name, last_name = _split_author_name(author)
            authors_structured.append({
                "full_name": author,
                "first_name": first_name,
                "last_name": last_name,
                "affiliation_standardized": None,
                "affiliation_type": None,
                "affiliation_country": None,
                "author_id_crossref": None,
                "h_index_estimated": None,
                "career_stage_inferred": None,
            })
        current_arxiv_id = (url.rstrip("/").split("/")[-1] if url else "").split("v", 1)[0]
        related_arxiv_ids = []
        for paper_id in _extract_arxiv_ids(full_markdown):
            normalized_id = paper_id.split("v", 1)[0]
            if normalized_id != current_arxiv_id:
                related_arxiv_ids.append(paper_id)
        entry_id = text_or_none("atom:id")
        versions = _extract_arxiv_versions(entry_id)
        structured = StructuredFields(
            platform=platform,
            resource_type=resource_type,
            title=title,
            description=summary,
            canonical_url=url,
            platform_fields={
                "doi": doi,
                "authors": authors,
                "authors_structured": authors_structured,
                "categories": categories,
                "primary_category": primary_category,
                "published": text_or_none("atom:published"),
                "updated": text_or_none("atom:updated"),
                "entry_id": entry_id,
                "versions": versions,
                "pdf_url": pdf_url,
                "raw_text": full_text,
                "title_normalized": normalized_title,
                "abstract_plain_text": normalized_abstract,
                "topic_hierarchy": _category_to_hierarchy(categories, primary_category),
                "research_area_plain_english": _category_to_plain_english(primary_category),
                "sections_structured": sections_structured,
                "references": references,
                "references_structured": [{"title": ref, "authors": [], "year": None, "venue": None} for ref in references],
                "total_citation_count": len(references),
                "code_available": bool(github_urls),
                "code_url": github_urls[0] if github_urls else None,
                "dataset_released": bool(dataset_urls),
                "dataset_url": dataset_urls[0] if dataset_urls else None,
                "open_access_status": "open_access",
                "linkable_identifiers": {
                    "github_repos_mentioned": github_urls,
                    "project_urls_mentioned": project_urls,
                    "dataset_source_urls": dataset_urls,
                    "related_arxiv_ids_mentioned": related_arxiv_ids,
                },
                "pdf_document_blocks": pdf_document_blocks,
                "pdf_extractor": "pymupdf4llm" if pdf_text else None,
                "page_count": page_count,
                "num_figures": num_figures,
            },
            field_sources={
                "doi": "xml:doi",
                "authors": "xml:author/name",
                "authors_structured": "xml:author/name+derived",
                "categories": "xml:category@term",
                "primary_category": "xml:primary_category@term",
                "published": "xml:published",
                "updated": "xml:updated",
                "entry_id": "xml:id",
                "versions": "xml:id+derived",
                "pdf_url": "xml:link[type=application/pdf]@href",
                "raw_text": "pdf:pymupdf4llm",
                "title_normalized": "xml:title+derived",
                "abstract_plain_text": "xml:summary+derived",
                "topic_hierarchy": "xml:category+derived",
                "research_area_plain_english": "xml:primary_category+derived",
                "sections_structured": "pdf:pymupdf4llm+derived",
                "references": "pdf:pymupdf4llm+derived",
                "references_structured": "pdf:pymupdf4llm+derived",
                "total_citation_count": "pdf:pymupdf4llm+derived",
                "code_available": "pdf:pymupdf4llm+derived",
                "code_url": "pdf:pymupdf4llm+derived",
                "dataset_released": "pdf:pymupdf4llm+derived",
                "dataset_url": "pdf:pymupdf4llm+derived",
                "open_access_status": "arxiv:derived",
                "linkable_identifiers": "pdf:pymupdf4llm+derived",
                "pdf_document_blocks": "pdf:pymupdf4llm",
                "pdf_extractor": "pdf:pymupdf4llm",
                "page_count": "pdf:pymupdf4llm",
                "num_figures": "pdf:pymupdf4llm+derived",
            },
        )

        sections: list[ContentSection] = []
        if full_text or full_markdown or title:
            sections.append(ContentSection(
                heading_text=title,
                heading_level=1,
                section_path=[title or "Main"],
                html="",
                text=full_text,
                markdown=full_markdown,
                char_offset_start=0,
                char_offset_end=len(full_text),
            ))

        main_content = MainContent(
            html="",
            text=full_text,
            markdown=full_markdown,
            sections=sections,
            selector_used="xml_structured",
        )
        reduced_content = self.reducer.reduce(main_content)
        chunks = self.chunker.chunk(reduced_content, doc_id=doc_id)
        quality = ExtractionQuality(
            content_ratio=len(reduced_content.text) / max(len(xml_text), 1),
            noise_removed=0,
            chunking_strategy="xml_structured",
        )

        return ExtractedDocument(
            doc_id=doc_id,
            source_url=url,
            platform=platform,
            resource_type=resource_type,
            extracted_at=datetime.now(timezone.utc),
            chunks=chunks,
            total_chunks=len(chunks),
            full_text=reduced_content.text,
            full_markdown=reduced_content.markdown,
            structured=structured,
            quality=quality,
            cleaned_html="",
            parser_metadata=parser_metadata,
            binary_artifacts={"raw_pdf": pdf_bytes} if pdf_bytes else {},
        )

    def _extract_from_html(
        self,
        *,
        fetch_result: dict[str, Any],
        platform: str,
        resource_type: str,
        url: str,
        doc_id: str,
    ) -> ExtractedDocument:
        """Branch 2: HTML content extraction.

        Strategy: Trafilatura (SOTA) first for article/wiki/blog content,
        then crawl4ai fallback for structured sites or when Trafilatura yields nothing.
        """
        html = (
            fetch_result.get("text")
            or fetch_result.get("html")
            or (fetch_result.get("content_bytes", b"") or b"").decode("utf-8", "ignore")
        )
        original_size = len(html)

        # Step 1a: Try Trafilatura for high-quality content extraction.
        # Best for articles, wiki pages, blogs, news — extracts only the main body.
        traf_result = extract_with_trafilatura(html, url)
        extracted_html = None  # set in crawl4ai fallback branch

        if traf_result and traf_result.text and len(traf_result.text) > 100:
            main_content = MainContent(
                html=traf_result.html or "",
                text=traf_result.text,
                markdown=traf_result.markdown,
                sections=_extract_sections_from_main_content(traf_result.text),
                selector_used="trafilatura",
            )
            reduced_content = self.reducer.reduce(main_content)
        else:
            # Step 1b: Fallback to crawl4ai for structured sites (Amazon, LinkedIn, etc.)
            extracted_html = extract_html_with_crawl4ai(
                html, url, platform=platform, resource_type=resource_type,
            )
            main_content = _build_main_content_from_html(
                extracted_html.html or extracted_html.cleaned_html,
                extracted_html.selector_used,
            )
            reduced_content = self.reducer.reduce(main_content)
            if not reduced_content.text and (extracted_html.text or extracted_html.markdown):
                reduced_content = MainContent(
                    html=extracted_html.html,
                    text=extracted_html.text,
                    markdown=extracted_html.markdown,
                    sections=main_content.sections,
                    selector_used=extracted_html.selector_used,
                )

        # Step 2.5: Pre-LLM optimization — reduce token cost
        pre_extracted: dict[str, Any] = {}
        optimized_text, pre_extracted = optimize_for_llm(
            reduced_content.text, pre_extracted=pre_extracted,
        )
        optimized_markdown, pre_extracted = optimize_for_llm(
            reduced_content.markdown, pre_extracted=pre_extracted,
        )
        reduced_content = MainContent(
            html=reduced_content.html,
            text=optimized_text,
            markdown=optimized_markdown,
            sections=reduced_content.sections,
            selector_used=reduced_content.selector_used,
        )

        # Step 3: Chunk content
        chunks = self.chunker.chunk(reduced_content, doc_id=doc_id)

        # Step 4: Extract structured fields from HTML meta
        structured = self.json_extractor.extract_from_html(
            html=html,  # Use original HTML for meta extraction
            platform=platform,
            resource_type=resource_type,
            url=url,
        )
        # Merge pre-extracted fields (title, date, language) from regex
        if pre_extracted.get("title") and not structured.title:
            structured.title = pre_extracted["title"]

        if self.css_extractor is not None:
            css_structured = self.css_extractor.extract(
                html=(extracted_html.cleaned_html if extracted_html else "") or reduced_content.html,
                canonical_url=url,
                platform=platform,
                resource_type=resource_type,
            )
            structured = self._merge_structured_fields(structured, css_structured)
        if self.llm_schema_extractor is not None:
            llm_structured, llm_error = self.llm_schema_extractor.extract(
                plain_text=reduced_content.text,
                markdown=reduced_content.markdown,
                cleaned_html=reduced_content.html,
                metadata={"title": structured.title, "description": structured.description},
                platform=platform,
                resource_type=resource_type,
                canonical_url=url,
            )
            if llm_structured is not None:
                structured = self._merge_structured_fields(structured, llm_structured)
            elif llm_error is not None:
                structured.platform_fields.setdefault("_schema_errors", []).append(llm_error)

        # Quality metrics
        content_size = len(reduced_content.text)
        cleaned_size = len((extracted_html.cleaned_html if extracted_html else "") or "")
        quality = ExtractionQuality(
            content_ratio=content_size / max(original_size, 1),
            noise_removed=max(original_size - cleaned_size, 0),
            chunking_strategy=f"hybrid:{extracted_html.selector_used if extracted_html else 'trafilatura'}",
        )

        return ExtractedDocument(
            doc_id=doc_id,
            source_url=url,
            platform=platform,
            resource_type=resource_type,
            extracted_at=datetime.now(timezone.utc),
            chunks=chunks,
            total_chunks=len(chunks),
            full_text=reduced_content.text,
            full_markdown=reduced_content.markdown,
            structured=structured,
            quality=quality,
            cleaned_html=(extracted_html.cleaned_html if extracted_html else "") or reduced_content.html,
        )

    def _merge_structured_fields(
        self,
        base: StructuredFields,
        override: StructuredFields,
    ) -> StructuredFields:
        merged_fields = dict(base.platform_fields)
        merged_fields.update(override.platform_fields)
        merged_sources = dict(base.field_sources)
        merged_sources.update(override.field_sources)
        return StructuredFields(
            platform=base.platform,
            resource_type=base.resource_type,
            title=override.title or base.title,
            description=override.description or base.description,
            canonical_url=base.canonical_url,
            platform_fields=merged_fields,
            field_sources=merged_sources,
        )

    def extract_to_legacy(
        self,
        fetch_result: dict[str, Any],
        platform: str,
        resource_type: str,
    ) -> dict[str, Any]:
        """Extract and return in the legacy dict format for backward compatibility
        with PlatformAdapter.extract_content interface."""
        doc = self.extract(fetch_result, platform, resource_type)
        return {
            "metadata": {
                "title": doc.structured.title,
                "description": doc.structured.description,
                "content_type": fetch_result.get("content_type"),
                "source_url": doc.source_url,
            },
            "markdown": doc.full_markdown,
            "plain_text": doc.full_text,
            "document_blocks": [],
            "structured": doc.structured.platform_fields,
            "extractor": "crawl4ai" if "crawl4ai:" in doc.quality.chunking_strategy else "extract_pipeline",
            "extract_document": doc.to_dict(),
        }
