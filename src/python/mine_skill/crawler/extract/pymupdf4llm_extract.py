from __future__ import annotations

import re
from pathlib import Path
from typing import Any

try:
    from pymupdf4llm import to_markdown

    _HAS_PYMUPDF4LLM = True
except ModuleNotFoundError:  # pragma: no cover - exercised through import guard behavior
    to_markdown = None
    _HAS_PYMUPDF4LLM = False


def require_pymupdf4llm() -> None:
    if not _HAS_PYMUPDF4LLM:
        raise RuntimeError(
            "PyMuPDF4LLM is required for arXiv PDF extraction. Install core dependencies including pymupdf4llm."
        )


def clean_scientific_markdown(markdown: str, title: str | None = None) -> str:
    text = markdown.replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.rstrip() for line in text.split("\n")]

    cleaned: list[str] = []
    previous_non_empty = ""
    title_seen = False
    for line in lines:
        stripped = line.strip()
        if re.fullmatch(r"Page\s+\d+", stripped):
            continue
        if title and stripped == title and title_seen:
            continue
        if title and stripped == title:
            title_seen = True
        if stripped == previous_non_empty and stripped and stripped == title:
            continue
        cleaned.append(line)
        if stripped:
            previous_non_empty = stripped

    normalized = "\n".join(cleaned)
    normalized = re.sub(r"\n{3,}", "\n\n", normalized)
    return normalized.strip()


def markdown_to_plain_text(markdown: str) -> str:
    text = re.sub(r"```.*?```", "", markdown, flags=re.S)
    text = re.sub(r"!\[[^\]]*\]\([^)]+\)", "", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"^[#>\-\*\d\.\s]+", "", text, flags=re.M)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def extract_pdf_with_pymupdf4llm(content_path: str, title: str | None = None) -> dict[str, Any]:
    path = Path(content_path)
    if not path.exists():
        return {
            "document_blocks": [],
            "plain_text": "",
            "markdown": "",
            "extractor": "none",
            "content_type": "application/pdf",
            "extraction_skipped_reason": "file_not_found",
        }

    require_pymupdf4llm()
    markdown = str(to_markdown(str(path), page_chunks=True, write_images=False, ignore_images=True))
    cleaned_markdown = clean_scientific_markdown(markdown, title=title)
    plain_text = markdown_to_plain_text(cleaned_markdown)
    page_count = len(re.findall(r"(?m)^\\s*#?\\s*Page\\b", markdown)) or max(cleaned_markdown.count("\f") + 1, 1)
    return {
        "document_blocks": [{"type": "markdown", "text": cleaned_markdown}],
        "plain_text": plain_text,
        "markdown": cleaned_markdown,
        "extractor": "pymupdf4llm",
        "content_type": "application/pdf",
        "page_count": page_count,
        "parser_metadata": {"parser": "pymupdf4llm"},
    }
