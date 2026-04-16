from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any

from markdownify import markdownify as to_markdown

from .content_cleaner import ContentCleaner
from .fit_content import FitContentReducer
from .html_parse import parse_html
from .main_content import MainContentExtractor

try:  # pragma: no cover - exercised via integration environments
    from crawl4ai import AsyncWebCrawler, CrawlerRunConfig
    from crawl4ai.content_filter_strategy import PruningContentFilter
    from crawl4ai.markdown_generation_strategy import DefaultMarkdownGenerator
except ModuleNotFoundError:  # pragma: no cover - optional import for tests/bootstrap
    AsyncWebCrawler = None
    CrawlerRunConfig = None
    DefaultMarkdownGenerator = None
    PruningContentFilter = None

try:  # pragma: no cover - API shape differs across versions
    from crawl4ai import CacheMode
except ModuleNotFoundError:  # pragma: no cover
    CacheMode = None


@dataclass(frozen=True, slots=True)
class Crawl4AIExtractionResult:
    html: str
    cleaned_html: str
    markdown: str
    text: str
    selector_used: str
    extractor: str


def _build_run_config() -> Any:
    if CrawlerRunConfig is None or DefaultMarkdownGenerator is None or PruningContentFilter is None:
        raise RuntimeError("crawl4ai is not available")

    markdown_generator = DefaultMarkdownGenerator(
        content_filter=PruningContentFilter(
            threshold=0.45,
            threshold_type="dynamic",
            min_word_threshold=12,
        ),
        options={
            "body_width": 0,
        },
    )
    kwargs: dict[str, Any] = {
        "markdown_generator": markdown_generator,
    }
    if CacheMode is not None:
        kwargs["cache_mode"] = CacheMode.BYPASS
    else:
        kwargs["bypass_cache"] = True
    return CrawlerRunConfig(**kwargs)


async def _extract_with_crawl4ai_async(html: str) -> Any:
    if AsyncWebCrawler is None:
        raise RuntimeError("crawl4ai is not available")

    config = _build_run_config()
    async with AsyncWebCrawler() as crawler:
        return await crawler.arun(url=f"raw:{html}", config=config)


def _run_async_compatible(coro: Any) -> Any:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    with ThreadPoolExecutor(max_workers=1) as executor:
        return executor.submit(lambda: asyncio.run(coro)).result()


def _coerce_markdown_payload(payload: Any) -> tuple[str, str, str]:
    if payload is None:
        return "", "", ""
    fit_markdown = getattr(payload, "fit_markdown", "") or ""
    fit_html = getattr(payload, "fit_html", "") or ""
    raw_markdown = getattr(payload, "raw_markdown", "") or ""
    if isinstance(payload, str):
        raw_markdown = payload
    markdown = fit_markdown or raw_markdown
    return markdown, fit_html, raw_markdown


def _text_from_html(html: str, fallback_markdown: str = "") -> str:
    if html.strip():
        return parse_html(html).get_text("\n", strip=True)
    return fallback_markdown.strip()


def _has_heading(html: str) -> bool:
    if not html.strip():
        return False
    return parse_html(html).find(["h1", "h2", "h3", "h4", "h5", "h6"]) is not None


def _fallback_extract_html(
    html: str,
    *,
    platform: str = "",
    resource_type: str = "",
) -> Crawl4AIExtractionResult:
    cleaned = ContentCleaner().clean(html, platform=platform)
    cleaned_soup = parse_html(cleaned.html)
    main_content = MainContentExtractor().extract(cleaned_soup, platform, resource_type)
    reduced_content = FitContentReducer().reduce(main_content)
    final_html = reduced_content.html or cleaned.html
    final_markdown = reduced_content.markdown or to_markdown(final_html, heading_style="ATX", bullets="-")
    final_text = reduced_content.text or _text_from_html(final_html, final_markdown)
    return Crawl4AIExtractionResult(
        html=final_html,
        cleaned_html=final_html,
        markdown=final_markdown,
        text=final_text,
        selector_used=f"fallback:{main_content.selector_used}",
        extractor="fallback_html",
    )


def extract_html_with_crawl4ai(
    html: str,
    url: str,
    *,
    platform: str = "",
    resource_type: str = "",
) -> Crawl4AIExtractionResult:
    del url  # Signature parity; raw HTML path does not use the URL.

    if not html.strip():
        return Crawl4AIExtractionResult(
            html="",
            cleaned_html="",
            markdown="",
            text="",
            selector_used="crawl4ai:empty",
            extractor="crawl4ai",
        )

    if AsyncWebCrawler is None or CrawlerRunConfig is None or DefaultMarkdownGenerator is None or PruningContentFilter is None:
        return _fallback_extract_html(html, platform=platform, resource_type=resource_type)

    fallback_result = _fallback_extract_html(html, platform=platform, resource_type=resource_type)
    try:
        result = _run_async_compatible(_extract_with_crawl4ai_async(html))
        markdown, fit_html, raw_markdown = _coerce_markdown_payload(getattr(result, "markdown", None))
        cleaned_html = getattr(result, "cleaned_html", "") or ""
        content_html = fit_html or cleaned_html or html
        selector_used = (
            "crawl4ai:fit_html"
            if fit_html
            else "crawl4ai:cleaned_html"
            if cleaned_html
            else "crawl4ai:raw_html"
        )
        text = _text_from_html(content_html, markdown or raw_markdown)
        if not markdown and content_html:
            markdown = to_markdown(content_html, heading_style="ATX", bullets="-")
        if text or markdown:
            post_processed = _fallback_extract_html(
                content_html,
                platform=platform,
                resource_type=resource_type,
            )
            if not fit_html and not cleaned_html:
                return fallback_result
            if _has_heading(fallback_result.html) and not _has_heading(post_processed.html):
                return fallback_result
            return Crawl4AIExtractionResult(
                html=post_processed.html or content_html,
                cleaned_html=post_processed.cleaned_html or cleaned_html or content_html,
                markdown=post_processed.markdown or markdown,
                text=post_processed.text or text,
                selector_used=selector_used,
                extractor="crawl4ai",
            )
    except Exception:
        pass

    return fallback_result
