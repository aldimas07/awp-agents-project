from __future__ import annotations

import re
from urllib.parse import quote, urlparse

from bs4 import BeautifulSoup

from crawler.fetch.api_backend import fetch_api_get

from .base import (
    PlatformAdapter,
    PlatformDiscoveryPlan,
    PlatformEnrichmentPlan,
    PlatformErrorPlan,
    PlatformExtractPlan,
    PlatformFetchPlan,
    PlatformNormalizePlan,
    default_fetch_executor,
    default_backend_resolver,
    hook_normalizer,
    route_enrichment_groups,
    strategy_extractor,
)

FETCH_PLAN = PlatformFetchPlan(default_backend="api", fallback_backends=("http",))
EXTRACT_PLAN = PlatformExtractPlan(strategy="article_html")
NORMALIZE_PLAN = PlatformNormalizePlan(hook_name="wikipedia")
ENRICH_PLAN = PlatformEnrichmentPlan(
    route="knowledge_base",
    field_groups=(
        # Passthrough fields (no transform)
        "wikipedia_base_dedup_key",
        "wikipedia_base_canonical_url",
        "wikipedia_base_url",
        "wikipedia_base_page_id",
        "wikipedia_base_title",
        "wikipedia_base_language",
        "wikipedia_base_article_creation_date",
        "wikipedia_base_protection_level",
        "wikipedia_base_raw_text",
        "wikipedia_base_html",
        "wikipedia_base_word_count",
        "wikipedia_base_number_of_sections",
        "wikipedia_base_has_infobox",
        "wikipedia_base_infobox_raw",
        "wikipedia_base_categories",
        "wikipedia_base_references_count",
        "wikipedia_base_external_links_count",
        "wikipedia_base_references",
        "wikipedia_base_see_also",
        "wikipedia_base_images",
        # ── generative（LLM enrichment）──
        "summaries",
        "wikipedia_identity",
        "wikipedia_multi_level_summary",
        "wikipedia_entities",
        "wikipedia_facts",
        "wikipedia_timeline",
        "wikipedia_relations",
        "wikipedia_quality",
        "wikipedia_categories",
        "wikipedia_infobox",
        "wikipedia_content",
        "wikipedia_educational",
        "wikipedia_bias_and_neutrality",
        "wikipedia_content_freshness",
        "wikipedia_cross_dataset_linkable_ids",
    ),
)


def _extract_wiki_host(canonical_url: str) -> str:
    """Extract the wiki host from a canonical URL (e.g. en.wikipedia.org from https://en.wikipedia.org/wiki/Cat)."""
    from urllib.parse import urlparse
    parsed = urlparse(canonical_url)
    host = parsed.netloc or "en.wikipedia.org"
    return host if "wikipedia.org" in host else "en.wikipedia.org"


def _fetch_wikipedia_api(record: dict, discovered: dict, storage_state_path: str | None) -> dict:
    title = discovered.get("fields", {}).get("title", "")
    canonical_url = discovered.get("canonical_url", "")
    if not title:
        raise ValueError(f"Wikipedia record missing title field: {list(discovered.get('fields', {}).keys())}")
    wiki_host = _extract_wiki_host(canonical_url)
    endpoint = (
        f"https://{wiki_host}/w/api.php"
        f"?action=query&titles={quote(title)}"
        "&prop=extracts|categories|pageprops|info|images|extlinks|links|langlinks|revisions"
        "&explaintext=1"
        "&inprop=url|protection"
        "&cllimit=50&ellimit=50&imlimit=20&pllimit=50&lllimit=50&llprop=url"
        "&rvlimit=1&rvdir=newer&rvslots=main&rvprop=timestamp|content"
        "&format=json&redirects=1"
    )
    payload = fetch_api_get(
        canonical_url=canonical_url,
        api_endpoint=endpoint,
        headers={"Accept": "application/json"},
    )
    try:
        parse_payload = fetch_api_get(
            canonical_url=canonical_url,
            api_endpoint=(
                f"https://{wiki_host}/w/api.php"
                f"?action=parse&page={quote(title)}&prop=text|wikitext&format=json&redirects=1"
            ),
            headers={"Accept": "application/json"},
        )
        payload["parse_json_data"] = parse_payload.get("json_data") or {}
    except Exception:
        payload["parse_json_data"] = {}
    try:
        html_payload = fetch_api_get(
            canonical_url=canonical_url,
            api_endpoint=canonical_url,
            headers={"Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8"},
        )
    except Exception:
        return payload
    payload["html_fallback_text"] = html_payload.get("text") or ""
    return payload


def _extract_revision_wikitext(page: dict) -> str:
    revisions = page.get("revisions", [])
    if not revisions or not isinstance(revisions[0], dict):
        return ""
    revision = revisions[0]
    slots = revision.get("slots")
    if isinstance(slots, dict):
        main = slots.get("main")
        if isinstance(main, dict):
            for key in ("*", "content"):
                value = main.get(key)
                if isinstance(value, str) and value.strip():
                    return value
    for key in ("*", "content"):
        value = revision.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return ""


def _extract_balanced_template(source: str, template_name: str) -> str:
    match = re.search(r"\{\{\s*" + re.escape(template_name) + r"\b", source, flags=re.I)
    if match is None:
        return ""
    depth = 0
    start = match.start()
    idx = start
    while idx < len(source) - 1:
        pair = source[idx:idx + 2]
        if pair == "{{":
            depth += 1
            idx += 2
            continue
        if pair == "}}":
            depth -= 1
            idx += 2
            if depth == 0:
                return source[start:idx].strip()
            continue
        idx += 1
    return ""


def _clean_wikitext_value(value: str) -> str:
    cleaned = re.sub(r"<ref[^>]*>.*?</ref>", "", value, flags=re.I | re.S)
    cleaned = re.sub(r"<ref[^>]*/\s*>", "", cleaned, flags=re.I)
    cleaned = re.sub(r"\[\[(?:[^|\]]+\|)?([^\]]+)\]\]", r"\1", cleaned)
    cleaned = re.sub(r"\{\{[^{}]*\}\}", "", cleaned)
    cleaned = re.sub(r"''+", "", cleaned)
    cleaned = re.sub(r"<[^>]+>", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip()


def _normalize_protection_level(levels: list[str]) -> str:
    normalized_levels = {str(level).strip().lower() for level in levels if str(level).strip()}
    if not normalized_levels:
        return "unprotected"
    if normalized_levels & {"sysop", "templateeditor", "extendedconfirmed"}:
        return "fully-protected"
    if normalized_levels & {"autoconfirmed", "editsemiprotected"}:
        return "semi-protected"
    return "fully-protected"


def _derive_title_metadata(title: str) -> tuple[str | None, str | None]:
    text = str(title or "").strip()
    if not text:
        return None, None
    match = re.match(r"^(?P<base>.+?)\s*\((?P<suffix>[^()]+)\)\s*$", text)
    if match is None:
        return None, text
    return text, match.group("base").strip()


def _parse_infobox_structured(infobox_raw: str) -> dict[str, str]:
    structured: dict[str, str] = {}
    if not infobox_raw:
        return structured
    for line in infobox_raw.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith(("{{", "}}")) or "=" not in stripped:
            continue
        if stripped.startswith("|"):
            stripped = stripped[1:].strip()
        key, value = stripped.split("=", 1)
        normalized_key = re.sub(r"\s+", "_", key.strip()).strip("_").lower()
        normalized_value = _clean_wikitext_value(value)
        if normalized_key and normalized_value:
            structured[normalized_key] = normalized_value
    return structured


def _extract_article_summary(plain_text: str) -> str:
    if not plain_text:
        return ""
    lead = re.split(r"(?m)^==[^=].*?==\s*$", plain_text, maxsplit=1)[0]
    for paragraph in re.split(r"\n\s*\n", lead):
        cleaned = paragraph.strip()
        if cleaned:
            return cleaned
    return ""


def _classify_section_type(heading: str) -> str:
    heading_lower = heading.strip().lower()
    for key, value in (
        ("history", "history"),
        ("background", "background"),
        ("career", "career"),
        ("biography", "biography"),
        ("plot", "plot"),
        ("legacy", "legacy"),
        ("reception", "reception"),
        ("see also", "see_also"),
        ("references", "references"),
        ("external links", "external_links"),
    ):
        if key in heading_lower:
            return value
    return "body"


def _extract_sections_from_plain_text(plain_text: str) -> tuple[list[dict[str, str]], list[str]]:
    if not plain_text:
        return [], []
    matches = list(re.finditer(r"(?m)^==\s*([^=\n]+?)\s*==\s*$", plain_text))
    if not matches:
        return [], []
    sections: list[dict[str, str]] = []
    toc: list[str] = []
    for index, match in enumerate(matches):
        heading = match.group(1).strip()
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(plain_text)
        content = plain_text[start:end].strip()
        toc.append(heading)
        sections.append({
            "heading": heading,
            "content": content,
            "section_type": _classify_section_type(heading),
        })
    return sections, toc


def _extract_tables_from_html(html: str) -> list[dict[str, object]]:
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")
    tables: list[dict[str, object]] = []
    for table in soup.select("table.wikitable"):
        headers = [cell.get_text(" ", strip=True) for cell in table.select("tr th")]
        rows: list[list[str]] = []
        for row in table.select("tr"):
            cells = row.find_all("td")
            if not cells:
                continue
            values = [cell.get_text(" ", strip=True) for cell in cells]
            if any(values):
                rows.append(values)
        if not headers and not rows:
            continue
        caption = table.find("caption")
        table_title = caption.get_text(" ", strip=True) if caption is not None else None
        tables.append({
            "table_title": table_title,
            "headers": headers,
            "rows": rows,
            "table_topic": table_title,
            "data_type": "table",
        })
    return tables


def _clean_categories(categories: list[str]) -> list[str]:
    cleaned: list[str] = []
    ignore_patterns = (
        r"^All ",
        r"^Articles with ",
        r"^Wikipedia articles ",
        r"^Use ",
        r"^CS1 ",
        r"^Commons category link ",
        r"^Short description ",
        r"^Webarchive template ",
        r"^(Featured|Good) articles$",
        r"^[A-Z]-?Class articles$",
        r".* stub(s)?$",
    )
    for category in categories:
        text = str(category).strip()
        if not text:
            continue
        if any(re.match(pattern, text, flags=re.I) for pattern in ignore_patterns):
            continue
        if text not in cleaned:
            cleaned.append(text)
    return cleaned


def _derive_article_quality_class(categories: list[str]) -> str | None:
    category_text = " | ".join(categories).lower()
    if "featured articles" in category_text:
        return "featured_article"
    if "good articles" in category_text:
        return "good_article"
    if re.search(r"\bb-?class\b", category_text):
        return "b_class"
    if re.search(r"\bc-?class\b", category_text):
        return "c_class"
    if "stub" in category_text:
        return "stub"
    return None


def _derive_domain(categories_cleaned: list[str]) -> str | None:
    category_text = " | ".join(categories_cleaned).lower()
    mapping = (
        ("artificial intelligence", "artificial_intelligence"),
        ("machine learning", "machine_learning"),
        ("computer science", "computer_science"),
        ("software", "software"),
        ("organization", "organization"),
        ("company", "business"),
        ("institute", "research"),
        ("laborator", "research"),
        ("science", "science"),
        ("technology", "technology"),
        ("history", "history"),
        ("politics", "politics"),
        ("geography", "geography"),
    )
    for needle, domain in mapping:
        if needle in category_text:
            return domain
    return None


def _derive_topic_hierarchy(categories_cleaned: list[str], domain: str | None) -> list[str]:
    hierarchy: list[str] = []
    if domain:
        hierarchy.append(domain)
    category_text = " | ".join(categories_cleaned).lower()
    if any(token in category_text for token in ("artificial intelligence", "machine learning", "computer science", "software", "technology")):
        if "technology" not in hierarchy:
            hierarchy.append("technology")
    elif any(token in category_text for token in ("organization", "company", "association", "institute", "laborator")):
        if "organization" not in hierarchy:
            hierarchy.append("organization")
    return hierarchy


def _derive_subject_tags(categories_cleaned: list[str], canonical_entity_name: str | None) -> list[str]:
    tags: list[str] = []
    canonical_lower = str(canonical_entity_name or "").strip().lower()
    for category in categories_cleaned:
        text = str(category).strip()
        if not text:
            continue
        lowered = text.lower()
        if canonical_lower and lowered == canonical_lower:
            continue
        if re.match(r"^\d{4}\b", text):
            continue
        if " in " in lowered or " based in " in lowered:
            continue
        if text not in tags:
            tags.append(text)
    if not tags and canonical_entity_name:
        tags.append(str(canonical_entity_name))
    return tags[:12]


def _classify_external_link(url: str, canonical_entity_name: str | None) -> dict[str, str | None]:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    canonical_name = re.sub(r"[^a-z0-9]+", "", str(canonical_entity_name or "").lower())
    compact_host = re.sub(r"[^a-z0-9]+", "", host)

    source_type = "other"
    reliability_tier = "low"

    if host.endswith((".gov", ".gov.uk", ".mil")):
        source_type = "government"
        reliability_tier = "high"
    elif host.endswith(".edu") or any(token in host for token in ("arxiv.org", "doi.org", "acm.org", "ieee.org", "springer.com", "nature.com", "science.org")):
        source_type = "academic"
        reliability_tier = "high"
    elif any(token in host for token in ("nytimes.com", "reuters.com", "apnews.com", "bbc.", "theguardian.com", "wsj.com", "washingtonpost.com", "bloomberg.com")):
        source_type = "news"
        reliability_tier = "medium"
    elif any(token in host for token in ("x.com", "twitter.com", "facebook.com", "instagram.com", "youtube.com", "tiktok.com", "reddit.com", "linkedin.com")):
        source_type = "social"
        reliability_tier = "low"
    elif canonical_name and canonical_name in compact_host:
        source_type = "official"
        reliability_tier = "medium"
    elif host:
        source_type = "other"
        reliability_tier = "medium" if host.endswith((".org", ".com")) else "low"

    return {
        "url": url,
        "source_type": source_type,
        "reliability_tier": reliability_tier,
    }


def _classify_external_links(urls: list[str], canonical_entity_name: str | None) -> list[dict[str, str | None]]:
    return [_classify_external_link(url, canonical_entity_name) for url in urls if url]


def _extract_see_also_links(wikitext: str) -> list[str]:
    if not wikitext:
        return []
    section_match = re.search(
        r"(?ims)^==\s*See also\s*==\s*$([\s\S]*?)(?=^==\s*[^=]+?\s*==\s*$|\Z)",
        wikitext,
    )
    if section_match is None:
        return []
    results: list[str] = []
    for line in section_match.group(1).splitlines():
        stripped = line.strip()
        if not stripped.startswith("*"):
            continue
        matches = re.findall(r"\[\[(?:[^|\]]+\|)?([^\]]+)\]\]", stripped)
        for match in matches:
            candidate = _clean_wikitext_value(match)
            if candidate and candidate not in results:
                results.append(candidate)
    return results


def _extract_language_links(page: dict) -> tuple[dict[str, str], dict[str, str]]:
    cross_language_links: dict[str, str] = {}
    entity_name_translations: dict[str, str] = {}
    for item in page.get("langlinks", []):
        if not isinstance(item, dict):
            continue
        lang = str(item.get("lang") or "").strip()
        title = str(item.get("*") or item.get("title") or "").strip()
        url = str(item.get("url") or "").strip()
        if not lang:
            continue
        if title:
            entity_name_translations[lang] = title
        if url:
            cross_language_links[lang] = url
        elif title:
            cross_language_links[lang] = f"https://{lang}.wikipedia.org/wiki/{quote(title.replace(' ', '_'), safe=':/()_-')}"
    return cross_language_links, entity_name_translations


def _extract_infobox_from_html(html: str) -> tuple[str, dict[str, str]]:
    if not html:
        return "", {}
    soup = BeautifulSoup(html, "html.parser")
    table = soup.select_one("table.infobox")
    if table is None:
        return "", {}
    rows: list[str] = []
    structured: dict[str, str] = {}
    for row in table.select("tr"):
        header = row.find(["th", "td"])
        value_cell = row.find("td")
        if header is None or value_cell is None:
            continue
        key = header.get_text(" ", strip=True)
        value = value_cell.get_text(" ", strip=True)
        if key and value:
            structured[re.sub(r"\s+", "_", key).strip("_").lower()] = value
            rows.append(f"| {key} = {value}")
    infobox_raw = "{{Infobox\n" + "\n".join(rows) + "\n}}" if rows else ""
    return infobox_raw, structured


def _extract_see_also_from_html(html: str) -> list[str]:
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")
    anchor = soup.select_one("#See_also")
    if anchor is None:
        for heading in soup.find_all(["h2", "h3"]):
            if heading.get_text(" ", strip=True).lower() == "see also":
                anchor = heading
                break
    if anchor is None:
        return []
    heading = anchor if anchor.name in {"h2", "h3"} else anchor.find_parent(["h2", "h3"])
    if heading is None:
        return []
    results: list[str] = []
    for sibling in heading.find_next_siblings():
        if sibling.name in {"h2", "h3"}:
            break
        for link in sibling.select("li a, div.div-col a"):
            candidate = link.get_text(" ", strip=True)
            if candidate and candidate not in results:
                results.append(candidate)
    return results


def _extract_wikipedia(record: dict, fetched: dict) -> dict:
    data = fetched.get("json_data") or {}
    parse_data = fetched.get("parse_json_data") or {}
    parse_page = parse_data.get("parse") if isinstance(parse_data, dict) else {}
    pages = ((data.get("query") or {}).get("pages") or {}).values()
    page = next(iter(pages), {})
    categories = [item.get("title", "").removeprefix("Category:") for item in page.get("categories", [])]
    page_id = page.get("pageid")
    title = page.get("title") or record.get("title")
    plain_text = page.get("extract") or ""
    markdown = f"# {title}\n\n{plain_text}".strip()
    fullurl = page.get("fullurl") or fetched.get("url") or ""
    wiki_host = _extract_wiki_host(fullurl)
    extlinks = [item.get("*", "").strip() for item in page.get("extlinks", []) if item.get("*", "").strip()]
    linked_titles = [item.get("title", "").strip() for item in page.get("links", []) if item.get("title", "").strip()]
    image_titles = [item.get("title", "").strip() for item in page.get("images", []) if item.get("title", "").strip()]
    image_urls = [
        f"https://{wiki_host}/wiki/Special:FilePath/{quote(image.removeprefix('File:'), safe=':/()_-')}"
        for image in image_titles
    ]
    categories_cleaned = _clean_categories(categories)
    revisions = page.get("revisions", [])
    article_creation_date = ""
    if revisions and isinstance(revisions[0], dict):
        article_creation_date = str(revisions[0].get("timestamp") or "")
    parse_wikitext = ""
    parse_html = ""
    if isinstance(parse_page, dict):
        parse_wikitext = str(((parse_page.get("wikitext") or {}).get("*") or "")).strip()
        parse_html = str(((parse_page.get("text") or {}).get("*") or "")).strip()
    revision_wikitext = _extract_revision_wikitext(page) or parse_wikitext
    protection = page.get("protection", [])
    protection_level = _normalize_protection_level([
        str(item.get("level") or "")
        for item in protection
        if isinstance(item, dict)
    ])
    title_disambiguated, canonical_entity_name = _derive_title_metadata(title or "")
    article_summary = _extract_article_summary(plain_text)
    sections_structured, table_of_contents = _extract_sections_from_plain_text(plain_text)
    tables_structured = _extract_tables_from_html(parse_html or str(fetched.get("html_fallback_text") or ""))
    cross_language_links, entity_name_translations = _extract_language_links(page)
    infobox_raw = _extract_balanced_template(revision_wikitext, "Infobox")
    infobox_structured = _parse_infobox_structured(infobox_raw)
    if not infobox_raw:
        html_infobox_raw, html_infobox_structured = _extract_infobox_from_html(
            parse_html or str(fetched.get("html_fallback_text") or "")
        )
        infobox_raw = html_infobox_raw
        infobox_structured = html_infobox_structured
    see_also = (
        _extract_see_also_links(revision_wikitext)
        or _extract_see_also_from_html(parse_html or str(fetched.get("html_fallback_text") or ""))
    )
    reference_count = len(re.findall(r"<ref\b", revision_wikitext, flags=re.I)) if revision_wikitext else len(extlinks)
    section_count = 1 + len(re.findall(r"^==[^=].*?==\s*$", plain_text, flags=re.MULTILINE)) if plain_text else 0
    word_count = len(re.findall(r"\b\w+\b", plain_text))
    pageprops = page.get("pageprops", {})
    has_infobox = bool(pageprops.get("infobox")) or bool(pageprops.get("wikibase_item")) or bool(infobox_raw)
    citation_density = round(reference_count / word_count, 4) if word_count > 0 else None
    last_major_edit = str(page.get("touched") or "").strip() or None
    article_quality_class = _derive_article_quality_class(categories)
    domain = _derive_domain(categories_cleaned)
    topic_hierarchy = _derive_topic_hierarchy(categories_cleaned, domain)
    subject_tags = _derive_subject_tags(categories_cleaned, canonical_entity_name)
    external_links_classified = _classify_external_links(extlinks, canonical_entity_name)
    return {
        "metadata": {
            "title": title,
            "content_type": fetched.get("content_type"),
            "source_url": fullurl,
            "page_id": None if page_id in (None, "") else str(page_id),
            "pageprops": pageprops,
        },
        "plain_text": plain_text,
        "markdown": markdown,
        "document_blocks": [],
        "structured": {
            "categories": categories,
            "page_id": None if page_id in (None, "") else str(page_id),
            "article_creation_date": article_creation_date,
            "protection_level": protection_level,
            "references": extlinks,
            "references_count": reference_count,
            "external_links_count": len(extlinks),
            "see_also": see_also,
            "images": image_urls,
            "word_count": word_count,
            "number_of_sections": section_count,
            "has_infobox": has_infobox,
            "infobox_raw": infobox_raw,
            "infobox_structured": infobox_structured,
            "title_disambiguated": title_disambiguated,
            "canonical_entity_name": canonical_entity_name,
            "wikidata_id": pageprops.get("wikibase_item"),
            "article_summary": article_summary,
            "sections_structured": sections_structured,
            "table_of_contents": table_of_contents,
            "tables_structured": tables_structured,
            "categories_cleaned": categories_cleaned,
            "citation_density": citation_density,
            "last_major_edit": last_major_edit,
            "article_quality_class": article_quality_class,
            "domain": domain,
            "topic_hierarchy": topic_hierarchy,
            "subject_tags": subject_tags,
            "external_links_classified": external_links_classified,
            "cross_language_links": cross_language_links,
            "entity_name_translations": entity_name_translations,
        },
        "extractor": "wikipedia_api",
    }


ADAPTER = PlatformAdapter(
    platform="wikipedia",
    discovery=PlatformDiscoveryPlan(resource_types=("article",), canonicalizer="wikipedia"),
    fetch=FETCH_PLAN,
    extract=EXTRACT_PLAN,
    normalize=NORMALIZE_PLAN,
    enrich=ENRICH_PLAN,
    error=PlatformErrorPlan(normalized_code="WIKIPEDIA_FETCH_FAILED"),
    resolve_backend_fn=default_backend_resolver(FETCH_PLAN),
    fetch_fn=default_fetch_executor(_fetch_wikipedia_api),
    extract_fn=_extract_wikipedia,
    normalize_fn=hook_normalizer(NORMALIZE_PLAN.hook_name),
    enrichment_fn=route_enrichment_groups(ENRICH_PLAN),
)
