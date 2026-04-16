from __future__ import annotations

import re

import httpx

DEFAULT_HEADERS = {
    "User-Agent": "mine-runtime/0.1 (contact: crawler@example.com)",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


def _build_fetch_payload(response: httpx.Response, backend: str) -> dict:
    headers = dict(response.headers)
    content_type = headers.get("content-type")
    encoding = _resolve_text_encoding(response)
    return {
        "url": str(response.url),
        "status_code": response.status_code,
        "headers": headers,
        "content_type": content_type,
        "encoding": encoding,
        "text": _decode_response_text(response, encoding),
        "content_bytes": response.content,
        "backend": backend,
    }


def _decode_response_text(response: httpx.Response, encoding: str | None) -> str:
    content = response.content or b""
    if not content:
        return ""
    if encoding:
        try:
            return content.decode(encoding, errors="replace")
        except LookupError:
            pass
    fallback = response.encoding or "utf-8"
    return content.decode(fallback, errors="replace")


def _resolve_text_encoding(response: httpx.Response) -> str | None:
    content = response.content or b""
    header = response.headers.get("content-type", "")

    header_match = re.search(r"charset=([^\s;]+)", header, flags=re.I)
    if header_match:
        return header_match.group(1).strip("\"' ")

    if content.startswith(b"\xef\xbb\xbf"):
        return "utf-8-sig"
    if content.startswith(b"\xff\xfe"):
        return "utf-16-le"
    if content.startswith(b"\xfe\xff"):
        return "utf-16-be"

    head = content[:4096]
    meta_match = re.search(
        br"<meta[^>]+charset=[\"']?\s*([A-Za-z0-9._:-]+)",
        head,
        flags=re.I,
    )
    if meta_match:
        return meta_match.group(1).decode("ascii", errors="ignore").lower()

    meta_content_match = re.search(
        br"<meta[^>]+content=[\"'][^\"']*charset=([A-Za-z0-9._:-]+)[^\"']*[\"']",
        head,
        flags=re.I,
    )
    if meta_content_match:
        return meta_content_match.group(1).decode("ascii", errors="ignore").lower()

    if response.encoding:
        return response.encoding
    return "utf-8"


def fetch_http(url: str, timeout: float = 20.0) -> dict:
    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        response = client.get(url, headers=DEFAULT_HEADERS)
        response.raise_for_status()
        return _build_fetch_payload(response, backend="http")
