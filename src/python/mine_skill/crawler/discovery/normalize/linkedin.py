"""LinkedIn URL normalization and discovery.

Normalizes arbitrary LinkedIn URLs into canonical forms for four entity types
(profile, company, job, post) and provides HTML-based link discovery.
"""

from __future__ import annotations

import re
from urllib.parse import quote, unquote, urljoin, urlparse

from crawler.discovery.normalize.base import NormalizeResult

# ---------------------------------------------------------------------------
# Host allowlist
# ---------------------------------------------------------------------------

_LINKEDIN_HOSTS = frozenset({
    "linkedin.com",
    "www.linkedin.com",
    "cn.linkedin.com",
    "www.cn.linkedin.com",
})

# ---------------------------------------------------------------------------
# Path patterns
# ---------------------------------------------------------------------------

_RE_PROFILE = re.compile(r"^/in/([^/]+)/?(?:.*)?$", re.IGNORECASE)
_RE_COMPANY = re.compile(r"^/company/([^/]+)/?(?:.*)?$", re.IGNORECASE)
_RE_JOB = re.compile(r"^/jobs/view/(\d+)/?(?:.*)?$", re.IGNORECASE)
_RE_FEED_ACTIVITY = re.compile(r"^/feed/update/urn:li:activity:(\d+)/?$", re.IGNORECASE)
_RE_FEED_ACTIVITY_ENCODED = re.compile(r"feed/update/.*?activity[:%3A]+(\d+)", re.IGNORECASE)
_RE_POSTS_ACTIVITY = re.compile(r"activity-(\d+)(?:$|[-_/])", re.IGNORECASE)

# Broad pattern for extracting LinkedIn URLs from arbitrary text.
_RE_ANY_LINKEDIN_URL = re.compile(
    r"https?://(?:[\w-]+\.)*linkedin\.com[^\s)\"'<>]*",
    re.IGNORECASE,
)

_CANONICAL_HOST = "www.linkedin.com"

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _host_ok(netloc: str) -> bool:
    host = netloc.lower().split(":")[0]
    return host in _LINKEDIN_HOSTS or host.endswith(".linkedin.com")


def _clean_vanity(segment: str) -> str:
    """Decode and strip a vanity / slug path segment."""
    return unquote(segment.strip())


def _build_url(path: str) -> str:
    return f"https://{_CANONICAL_HOST}{path}"


def _encode_vanity(vanity: str) -> str:
    return quote(vanity, safe="-_.~")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def normalize_linkedin_url(url: str) -> NormalizeResult:
    """Normalize any LinkedIn URL into one of four canonical forms.

    Entity types: ``profile``, ``company``, ``job``, ``post``, ``unknown``.

    Strips tracking query parameters. Normalizes ``/posts/...activity-{id}``
    to the canonical ``/feed/update/urn:li:activity:{id}/`` form.
    """
    raw = (url or "").strip()
    if not raw:
        return NormalizeResult(
            entity_type="unknown", canonical_url="", original_url=raw,
            notes=("empty_input",),
        )

    parsed = urlparse(raw)
    if not parsed.scheme:
        parsed = urlparse("https://" + raw)

    if parsed.scheme not in ("http", "https"):
        return NormalizeResult(
            entity_type="unknown", canonical_url="", original_url=raw,
            notes=("unsupported_scheme",),
        )

    netloc = parsed.netloc.lower().replace(":443", "").split(":")[0]
    if not _host_ok(netloc):
        return NormalizeResult(
            entity_type="unknown", canonical_url="", original_url=raw,
            notes=("not_linkedin_host",),
        )

    path = unquote(parsed.path) or "/"
    path = "/" + path.lstrip("/")
    if path != "/" and not path.endswith("/"):
        path += "/"

    notes: list[str] = []
    if parsed.query:
        notes.append("stripped_query")

    # --- Profile: /in/{vanity} ---
    m = _RE_PROFILE.match(path)
    if m:
        vanity = _clean_vanity(m.group(1))
        if vanity:
            canonical = _build_url(f"/in/{_encode_vanity(vanity)}/")
            return NormalizeResult(
                entity_type="profile", canonical_url=canonical,
                identity={"vanity": vanity},
                original_url=raw, notes=tuple(notes),
            )

    # --- Company: /company/{slug} ---
    m = _RE_COMPANY.match(path)
    if m:
        slug = _clean_vanity(m.group(1))
        if slug:
            canonical = _build_url(f"/company/{_encode_vanity(slug)}/")
            return NormalizeResult(
                entity_type="company", canonical_url=canonical,
                identity={"vanity": slug},
                original_url=raw, notes=tuple(notes),
            )

    # --- Job: /jobs/view/{id} ---
    m = _RE_JOB.match(path)
    if m:
        job_id = m.group(1)
        canonical = _build_url(f"/jobs/view/{job_id}/")
        return NormalizeResult(
            entity_type="job", canonical_url=canonical,
            identity={"job_id": job_id},
            original_url=raw, notes=tuple(notes),
        )

    # --- Post: /feed/update/urn:li:activity:{id} ---
    m = _RE_FEED_ACTIVITY.match(path)
    if m:
        activity_id = m.group(1)
        canonical = _build_url(f"/feed/update/urn:li:activity:{activity_id}/")
        return NormalizeResult(
            entity_type="post", canonical_url=canonical,
            identity={"activity_id": activity_id},
            original_url=raw, notes=tuple(notes),
        )

    # --- Post: encoded activity URN in path ---
    if "feed" in path.lower() and "activity" in path.lower():
        m2 = _RE_FEED_ACTIVITY_ENCODED.search(path)
        if m2:
            activity_id = m2.group(1)
            canonical = _build_url(f"/feed/update/urn:li:activity:{activity_id}/")
            return NormalizeResult(
                entity_type="post", canonical_url=canonical,
                identity={"activity_id": activity_id},
                original_url=raw,
                notes=tuple(notes + ["decoded_embedded_activity_path"]),
            )

    # --- Post: /posts/...activity-{id}... ---
    if "/posts/" in path:
        m3 = _RE_POSTS_ACTIVITY.search(path)
        if m3:
            activity_id = m3.group(1)
            canonical = _build_url(f"/feed/update/urn:li:activity:{activity_id}/")
            return NormalizeResult(
                entity_type="post", canonical_url=canonical,
                identity={"activity_id": activity_id},
                original_url=raw,
                notes=tuple(notes + ["normalized_from_posts_path"]),
            )

    return NormalizeResult(
        entity_type="unknown", canonical_url="", original_url=raw,
        notes=tuple(notes + ["unrecognized_path"]),
    )


def discover_from_html(
    html: str,
    base_url: str = "https://www.linkedin.com/",
) -> list[str]:
    """Extract deduplicated LinkedIn URLs from HTML anchor tags.

    Resolves relative hrefs against *base_url*, strips fragments,
    and keeps only ``http(s)`` links pointing to ``linkedin.com``.
    """
    try:
        from bs4 import BeautifulSoup
    except ImportError as exc:
        raise ImportError(
            "discover_from_html requires beautifulsoup4: pip install beautifulsoup4 lxml"
        ) from exc

    if not html or not html.strip():
        return []

    soup = BeautifulSoup(html, "lxml")
    base = base_url if base_url.endswith("/") else base_url + "/"
    seen: set[str] = set()
    out: list[str] = []

    for tag in soup.find_all(href=True):
        href = (tag.get("href") or "").strip()
        if not href or href.startswith("#") or href.lower().startswith("javascript:"):
            continue
        if "/linkedin.com" not in href and "linkedin.com" not in href and not href.startswith("/"):
            continue

        full = urljoin(base, href) if href.startswith("/") else href
        if "linkedin.com" not in full.lower():
            continue

        p = urlparse(full)
        if p.scheme not in ("http", "https"):
            continue

        no_frag = full.split("#", 1)[0]
        if no_frag not in seen:
            seen.add(no_frag)
            out.append(no_frag)

    return out


def discover_from_html_deep(
    html: str,
    base_url: str = "https://www.linkedin.com/",
) -> list[str]:
    """Deep extraction: anchors + regex over raw HTML (catches embedded JSON URLs).

    LinkedIn pages embed many links only inside serialized JSON or ``<code>``
    blocks. This function unions anchor-based discovery with a broad regex
    sweep so that company, profile, and post links in those payloads are not
    missed.
    """
    anchor_urls = discover_from_html(html, base_url=base_url)

    embedded: list[str] = []
    for m in _RE_ANY_LINKEDIN_URL.finditer(html):
        raw = m.group(0).rstrip(".,;]")
        cleaned = raw.split("#", 1)[0].strip()
        if cleaned:
            embedded.append(cleaned)

    seen: set[str] = set()
    out: list[str] = []
    for u in anchor_urls + embedded:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out
