from __future__ import annotations

import json
from typing import Any

import httpx

DEFAULT_API_HEADERS = {
    "User-Agent": "mine-runtime/0.1 (contact: crawler@example.com)",
    "Accept": "application/json,application/xml,text/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


def fetch_api_get(
    *,
    canonical_url: str,
    api_endpoint: str,
    headers: dict[str, str] | None = None,
    timeout: float = 30.0,
) -> dict[str, Any]:
    request_headers = dict(DEFAULT_API_HEADERS)
    request_headers.update(headers or {})
    with httpx.Client(timeout=timeout, follow_redirects=True, headers=request_headers) as client:
        response = client.get(api_endpoint)
        response.raise_for_status()
        return _build_api_payload(canonical_url=canonical_url, endpoint=api_endpoint, response=response)


def fetch_api_post(
    *,
    canonical_url: str,
    api_endpoint: str,
    headers: dict[str, str] | None = None,
    json_payload: dict[str, Any] | None = None,
    timeout: float = 30.0,
) -> dict[str, Any]:
    request_headers = dict(DEFAULT_API_HEADERS)
    request_headers.update(headers or {})
    with httpx.Client(timeout=timeout, headers=request_headers) as client:
        response = client.post(api_endpoint, json=json_payload or {})
        response.raise_for_status()
        return _build_api_payload(canonical_url=canonical_url, endpoint=api_endpoint, response=response)


def _build_api_payload(*, canonical_url: str, endpoint: str, response: httpx.Response) -> dict[str, Any]:
    text = response.text
    content_type = response.headers.get("content-type", "")
    json_data = None
    if "json" in content_type:
        try:
            json_data = response.json()
        except Exception:
            json_data = None
    return {
        "url": canonical_url,
        "api_endpoint": endpoint,
        "status_code": response.status_code,
        "headers": dict(response.headers),
        "content_type": content_type,
        "text": text,
        "content_bytes": response.content,
        "json_data": json_data,
        "backend": "api",
    }
