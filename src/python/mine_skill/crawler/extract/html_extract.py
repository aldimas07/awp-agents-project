from __future__ import annotations

from urllib.parse import urljoin

from markdownify import markdownify as to_markdown

from .html_parse import parse_html
from .pipeline import ExtractPipeline


def _is_html_content_type(content_type: str | None) -> bool:
    if content_type is None:
        return True
    content_type = content_type.lower()
    return "html" in content_type or content_type in {"text/xml", "application/xml"}


def extract_html_document(
    html: str,
    url: str,
    content_type: str | None = None,
    *,
    platform: str = "",
    resource_type: str = "",
) -> dict:
    soup = parse_html(html)
    title = soup.title.string.strip() if soup.title and soup.title.string else None
    description_tag = soup.find("meta", attrs={"name": "description"})
    description = description_tag.get("content") if description_tag else None
    icon_tag = soup.find("link", rel=lambda value: value and "icon" in value)
    favicon = urljoin(url, icon_tag.get("href")) if icon_tag and icon_tag.get("href") else None

    markdown = to_markdown(str(soup), heading_style="ATX", bullets="-")
    plain_text = soup.get_text("\n", strip=True)
    if _is_html_content_type(content_type):
        return ExtractPipeline().extract_to_legacy(
            {
                "url": url,
                "text": html,
                "content_type": content_type,
            },
            platform,
            resource_type,
        )

    return {
        "metadata": {
            "title": title,
            "description": description,
            "favicon": favicon,
            "content_type": content_type,
            "source_url": url,
        },
        "markdown": markdown,
        "plain_text": plain_text,
        "extractor": "html",
    }
