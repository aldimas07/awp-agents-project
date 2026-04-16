"""Multi-layer SOTA content extraction.

Four extraction layers, each CPU-only and < 50ms per page:
1. Trafilatura — statistical heuristics, best for articles/wiki/blogs
2. Readability — DOM weight scoring, Mozilla's "reader mode" algorithm
3. jusText — language-aware paragraph classifier, removes boilerplate
4. Fallback to crawl4ai (handled by the caller in pipeline.py)

Each layer returns None on failure, letting the next layer try.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

log = logging.getLogger("crawler.extract.trafilatura")

# === Layer 1: Trafilatura ===
try:
    import trafilatura
    from trafilatura.settings import use_config

    _traf_config = use_config()
    _traf_config.set("DEFAULT", "MIN_OUTPUT_SIZE", "100")
    _traf_config.set("DEFAULT", "MIN_EXTRACTED_SIZE", "100")
    _TRAFILATURA_AVAILABLE = True
except ImportError:
    trafilatura = None  # type: ignore[assignment]
    _traf_config = None
    _TRAFILATURA_AVAILABLE = False

# === Layer 2: Readability ===
try:
    from readability import Document as ReadabilityDocument
    _READABILITY_AVAILABLE = True
except ImportError:
    ReadabilityDocument = None  # type: ignore[assignment,misc]
    _READABILITY_AVAILABLE = False

# === Layer 3: jusText ===
try:
    import justext
    _JUSTEXT_AVAILABLE = True
except ImportError:
    justext = None  # type: ignore[assignment]
    _JUSTEXT_AVAILABLE = False


@dataclass(frozen=True, slots=True)
class TrafilaturaResult:
    text: str
    html: str
    markdown: str
    title: str
    author: str
    date: str
    extractor: str


def extract_with_trafilatura(
    html: str,
    url: str,
) -> TrafilaturaResult | None:
    """Multi-layer content extraction. Tries Trafilatura -> Readability -> jusText.

    Returns None only if ALL layers fail.
    """
    if not html or len(html) < 50:
        return None

    # Layer 1: Trafilatura
    result = _try_trafilatura(html, url)
    if result and len(result.text) > 100:
        return result

    # Layer 2: Readability
    result = _try_readability(html, url)
    if result and len(result.text) > 100:
        return result

    # Layer 3: jusText
    result = _try_justext(html, url)
    if result and len(result.text) > 100:
        return result

    # All layers failed — return whatever we got (even if short)
    return result


def _try_trafilatura(html: str, url: str) -> TrafilaturaResult | None:
    """Layer 1: Trafilatura — statistical heuristics."""
    if not _TRAFILATURA_AVAILABLE:
        return None
    try:
        text = trafilatura.extract(
            html, url=url,
            include_comments=False, include_tables=True,
            include_links=False, include_images=False,
            favor_recall=True, config=_traf_config,
        )
        if not text:
            return None

        metadata = trafilatura.extract_metadata(html, default_url=url)
        title = metadata.title or "" if metadata else ""
        author = metadata.author or "" if metadata else ""
        date = str(metadata.date or "") if metadata else ""

        return _build_result(text, title, author, date, "trafilatura")
    except Exception as exc:
        log.debug("Trafilatura failed for %s: %s", url, exc)
        return None


def _try_readability(html: str, url: str) -> TrafilaturaResult | None:
    """Layer 2: Readability — Mozilla's reader mode DOM scoring."""
    if not _READABILITY_AVAILABLE:
        return None
    try:
        doc = ReadabilityDocument(html, url=url)
        title = doc.short_title() or ""
        content_html = doc.summary()
        if not content_html:
            return None

        # Strip HTML tags for plain text
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(content_html, "html.parser")
        text = soup.get_text("\n", strip=True)
        if not text:
            return None

        return _build_result(text, title, "", "", "readability")
    except Exception as exc:
        log.debug("Readability failed for %s: %s", url, exc)
        return None


def _try_justext(html: str, url: str) -> TrafilaturaResult | None:
    """Layer 3: jusText — language-aware paragraph classifier."""
    if not _JUSTEXT_AVAILABLE:
        return None
    try:
        paragraphs = justext.justext(html, justext.get_stoplist("English"))
        good_paragraphs = [p.text for p in paragraphs if not p.is_boilerplate]
        if not good_paragraphs:
            return None

        text = "\n\n".join(good_paragraphs)
        return _build_result(text, "", "", "", "justext")
    except Exception as exc:
        log.debug("jusText failed for %s: %s", url, exc)
        return None


def _build_result(
    text: str, title: str, author: str, date: str, extractor: str,
) -> TrafilaturaResult:
    """Build a TrafilaturaResult from extracted text and metadata."""
    lines = []
    if title:
        lines.append(f"# {title}")
        lines.append("")
    lines.append(text)

    return TrafilaturaResult(
        text=text,
        html="",
        markdown="\n".join(lines),
        title=title,
        author=author,
        date=date,
        extractor=extractor,
    )
