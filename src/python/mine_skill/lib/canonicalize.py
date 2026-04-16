from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


TRACKING_QUERY_KEYS = {"fbclid", "gclid", "igshid", "mc_cid", "mc_eid", "ref", "ref_src"}


def canonicalize_url(url: str) -> str:
    raw = url.strip()
    if not raw:
        return ""

    parsed = urlsplit(raw)
    scheme = parsed.scheme.lower() or "https"
    host = parsed.hostname.lower() if parsed.hostname else ""
    port = parsed.port
    if port and not ((scheme == "https" and port == 443) or (scheme == "http" and port == 80)):
        netloc = f"{host}:{port}"
    else:
        netloc = host

    path = parsed.path or "/"
    query_pairs = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if not key.lower().startswith("utm_") and key.lower() not in TRACKING_QUERY_KEYS
    ]

    # Wikipedia: all language subdomains (xx.wikipedia.org) — strip query, preserve host+path
    if host.endswith(".wikipedia.org") and "." not in host.removesuffix(".wikipedia.org") and path.startswith("/wiki/"):
        return urlunsplit(("https", host, path, "", ""))
    # arXiv: strip version suffix (v1, v2, ...) for consistent dedup
    if (host == "arxiv.org" or host.endswith(".arxiv.org")) and path.startswith("/abs/"):
        import re as _re
        clean_path = _re.sub(r"v\d+/?$", "", "/" + path.strip("/"))
        return urlunsplit(("https", "arxiv.org", clean_path, "", ""))
    if host == "www.linkedin.com":
        normalized = "/" + path.strip("/")
        if normalized.startswith(("/in/", "/company/")) and not normalized.endswith("/"):
            normalized += "/"
        return urlunsplit(("https", "www.linkedin.com", normalized or "/", "", ""))
    # Amazon: normalize all regional domains to canonical /dp/ASIN form
    amazon_hosts = ("www.amazon.com", "www.amazon.co.uk", "www.amazon.de",
                    "www.amazon.fr", "www.amazon.it", "www.amazon.es",
                    "www.amazon.co.jp", "www.amazon.ca", "www.amazon.com.au",
                    "www.amazon.in", "www.amazon.com.br", "www.amazon.com.mx",
                    "amazon.com", "amazon.co.uk", "amazon.de")
    if host in amazon_hosts or host.endswith(".amazon.com") or host.endswith(".amazon.co.uk") or host.endswith(".amazon.de"):
        segments = [segment for segment in path.split("/") if segment]
        if "dp" in segments:
            dp_index = segments.index("dp")
            if dp_index + 1 < len(segments):
                asin = segments[dp_index + 1].upper()
                # Normalize to www.amazon.com for consistent dedup
                return urlunsplit(("https", "www.amazon.com", f"/dp/{asin}", "", ""))
        if "gp" in segments and "product" in segments:
            product_index = segments.index("product")
            if product_index + 1 < len(segments):
                asin = segments[product_index + 1].upper()
                return urlunsplit(("https", "www.amazon.com", f"/dp/{asin}", "", ""))

    normalized_path = path if path == "/" else path.rstrip("/") or "/"
    normalized_query = urlencode(sorted(query_pairs))
    return urlunsplit((scheme, netloc, normalized_path, normalized_query, ""))
