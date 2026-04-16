"""Document extraction module.

Lightweight implementation that replaces the heavy unstructured[all-docs] dependency.
For PDF extraction, optionally install pypdf: pip install pypdf
"""
from __future__ import annotations

from pathlib import Path

# Optional lightweight PDF support
try:
    from pypdf import PdfReader
    _HAS_PYPDF = True
except ModuleNotFoundError:
    _HAS_PYPDF = False


def _is_document_content_type(content_type: str | None) -> bool:
    """Check if content type indicates a document (PDF, Word, etc.)."""
    if content_type is None:
        return False
    content_type = content_type.lower()
    return any(
        content_type.startswith(prefix)
        for prefix in (
            "application/pdf",
            "application/msword",
            "application/vnd.openxmlformats-officedocument",
            "application/vnd.ms-",
        )
    )


def extract_document_blocks(content_path: str, content_type: str | None = None) -> dict:
    """Extract text blocks from a document file.

    Currently supports PDF (if pypdf is installed).
    Returns empty result for unsupported formats.
    """
    path = Path(content_path)

    if not path.exists():
        return _empty_result(content_type, "file_not_found")

    if not _is_document_content_type(content_type):
        return _empty_result(content_type, "unsupported_content_type")

    # PDF extraction with pypdf
    if content_type and content_type.lower().startswith("application/pdf"):
        if _HAS_PYPDF:
            return _extract_pdf(path, content_type)
        return _empty_result(content_type, "pypdf_not_installed")

    # Other document types not supported in lightweight mode
    return _empty_result(content_type, "document_type_not_supported")


def _extract_pdf(path: Path, content_type: str | None) -> dict:
    """Extract text from PDF using pypdf."""
    try:
        reader = PdfReader(path)
        blocks = []
        plain_parts = []

        for i, page in enumerate(reader.pages):
            text = page.extract_text() or ""
            text = text.strip()
            if text:
                blocks.append({"type": "Page", "page": i + 1, "text": text})
                plain_parts.append(text)

        return {
            "document_blocks": blocks,
            "sections": blocks,
            "plain_text": "\n\n".join(plain_parts),
            "extractor": "pypdf",
            "content_type": content_type,
            "page_count": len(reader.pages),
        }
    except Exception as exc:
        return _empty_result(content_type, f"pdf_extraction_failed: {exc}")


def _empty_result(content_type: str | None, reason: str = "not_supported") -> dict:
    """Return empty extraction result."""
    return {
        "document_blocks": [],
        "sections": [],
        "plain_text": "",
        "extractor": "none",
        "content_type": content_type,
        "extraction_skipped_reason": reason,
    }
