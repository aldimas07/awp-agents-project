from __future__ import annotations

import re

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

ARXIV_ENRICHMENT_GROUPS = (
    "arxiv_base_dedup_key",
    "arxiv_base_canonical_url",
    "arxiv_base_url",
    "arxiv_base_arxiv_id",
    "arxiv_base_doi",
    "arxiv_base_title",
    "arxiv_base_abstract",
    "arxiv_base_page_count",
    "arxiv_base_num_authors",
    "arxiv_base_num_figures",
    "arxiv_base_authors",
    "arxiv_base_categories",
    "arxiv_base_primary_category",
    "arxiv_base_submission_date",
    "arxiv_base_update_date",
    "arxiv_base_versions",
    "arxiv_base_submission_comments",
    "arxiv_base_journal_ref",
    "arxiv_base_license",
    "arxiv_base_raw_text",
    "arxiv_base_pdf_url",
    "arxiv_base_references",
    "arxiv_identity",
    "arxiv_authors",
    "arxiv_classification",
    "arxiv_dates",
    "arxiv_full_text",
    "arxiv_contribution",
    "arxiv_methodology",
    "arxiv_results",
    "arxiv_limitations",
    "arxiv_references",
    "arxiv_code_and_data",
    "arxiv_embeddings",
    "arxiv_relations",
    "arxiv_multimodal_figures",
    "arxiv_multimodal_equations",
    "arxiv_multi_level_summary",
    "arxiv_research_depth_analysis",
    "arxiv_cross_dataset_linkable_ids",
)

FETCH_PLAN = PlatformFetchPlan(default_backend="api", fallback_backends=("http",))
EXTRACT_PLAN = PlatformExtractPlan(strategy="paper_metadata")
NORMALIZE_PLAN = PlatformNormalizePlan(hook_name="arxiv")
ENRICH_PLAN = PlatformEnrichmentPlan(
    route="research_graph",
    field_groups=ARXIV_ENRICHMENT_GROUPS,
)


def _extract_versions(raw_arxiv_id: str) -> list[str]:
    match = re.search(r"v(\d+)$", raw_arxiv_id)
    if match is None:
        return ["v1"] if raw_arxiv_id else []
    latest_version = int(match.group(1))
    if latest_version <= 0:
        return []
    return [f"v{index}" for index in range(1, latest_version + 1)]


def _fetch_arxiv_api(record: dict, discovered: dict, storage_state_path: str | None) -> dict:
    arxiv_id = discovered.get("fields", {}).get("arxiv_id", "")
    if not arxiv_id:
        raise ValueError(f"arXiv record missing arxiv_id: {discovered.get('canonical_url', '?')}")
    endpoint = f"http://export.arxiv.org/api/query?id_list={arxiv_id}"
    return fetch_api_get(
        canonical_url=discovered["canonical_url"],
        api_endpoint=endpoint,
        headers={"Accept": "application/atom+xml,text/xml;q=0.9,*/*;q=0.8"},
    )


def _extract_arxiv(record: dict, fetched: dict) -> dict:
    text = fetched.get("text", "")
    html_fallback = str(fetched.get("html_fallback_text") or "")
    entry_match = re.search(r"<entry>(.*?)</entry>", text, flags=re.S)
    entry = entry_match.group(1) if entry_match else text
    title_matches = re.findall(r"<title>\s*(.*?)\s*</title>", text, flags=re.S)
    summary_match = re.search(r"<summary>\s*(.*?)\s*</summary>", entry, flags=re.S)
    authors = re.findall(r"<name>\s*(.*?)\s*</name>", entry, flags=re.S)
    id_match = re.search(r"<id>\s*https?://arxiv\.org/abs/([^<\s]+)\s*</id>", entry, flags=re.S)
    raw_arxiv_id = id_match.group(1).strip() if id_match else str(record.get("arxiv_id") or "")
    arxiv_id = re.sub(r"v\d+$", "", raw_arxiv_id)
    versions = _extract_versions(raw_arxiv_id)
    doi_match = re.search(r"<arxiv:doi>\s*(.*?)\s*</arxiv:doi>", entry, flags=re.S)
    published_match = re.search(r"<published>\s*(.*?)\s*</published>", entry, flags=re.S)
    updated_match = re.search(r"<updated>\s*(.*?)\s*</updated>", entry, flags=re.S)
    comment_match = re.search(r"<arxiv:comment>\s*(.*?)\s*</arxiv:comment>", entry, flags=re.S)
    journal_ref_match = re.search(r"<arxiv:journal_ref>\s*(.*?)\s*</arxiv:journal_ref>", entry, flags=re.S)
    rights_match = re.search(r"<rights>\s*(.*?)\s*</rights>", entry, flags=re.S)
    primary_category_match = re.search(r'<arxiv:primary_category[^>]*term="([^"]+)"', entry, flags=re.S)
    category_matches = re.findall(r'<category[^>]*term="([^"]+)"', entry, flags=re.S)
    pdf_link_match = re.search(r'<link[^>]*(?:title="pdf"|href="([^"]*pdf[^"]*)")[^>]*href="([^"]+)"', entry, flags=re.S)
    pdf_url = ""
    if pdf_link_match:
        pdf_url = pdf_link_match.group(2) or pdf_link_match.group(1) or ""
    if not pdf_url and html_fallback:
        pdf_match = re.search(r'href="(https?://arxiv\.org/pdf/[^"]+)"', html_fallback, flags=re.I)
        if pdf_match:
            pdf_url = pdf_match.group(1).strip()
    raw_title = title_matches[1] if len(title_matches) > 1 else (title_matches[0] if title_matches else record.get("arxiv_id") or "")
    title = re.sub(r"\s+", " ", str(raw_title)).strip()
    summary = re.sub(r"\s+", " ", summary_match.group(1)).strip() if summary_match else ""
    markdown = f"# {title}\n\n{summary}".strip()
    published = published_match.group(1).strip()[:10] if published_match else ""
    updated = updated_match.group(1).strip()[:10] if updated_match else ""
    doi = re.sub(r"\s+", " ", doi_match.group(1)).strip() if doi_match else ""
    comment = re.sub(r"\s+", " ", comment_match.group(1)).strip() if comment_match else ""
    journal_ref = re.sub(r"\s+", " ", journal_ref_match.group(1)).strip() if journal_ref_match else ""
    license_url = re.sub(r"\s+", " ", rights_match.group(1)).strip() if rights_match else ""
    if not license_url and html_fallback:
        license_match = re.search(r'href="(http[^"]*licenses?[^"]*)"', html_fallback, flags=re.I)
        if license_match:
            license_url = license_match.group(1).strip()
    primary_category = primary_category_match.group(1).strip() if primary_category_match else ""
    categories: list[str] = []
    for category in category_matches:
        normalized = category.strip()
        if normalized and normalized not in categories:
            categories.append(normalized)
    page_count_match = re.search(r"(\d+)\s+pages?", html_fallback, flags=re.I)
    num_figures_match = re.search(r"(\d+)\s+figures?", html_fallback, flags=re.I)
    return {
        "metadata": {
            "title": title,
            "authors": authors,
            "content_type": fetched.get("content_type"),
            "source_url": fetched["url"],
        },
        "plain_text": summary,
        "markdown": markdown,
        "document_blocks": [],
        "structured": {
            "arxiv_id": arxiv_id,
            "authors": authors,
            "doi": doi,
            "published": published,
            "updated": updated,
            "versions": versions,
            "comment": comment,
            "journal_ref": journal_ref,
            "license": license_url,
            "primary_category": primary_category,
            "categories": categories,
            "pdf_url": pdf_url,
            "page_count": int(page_count_match.group(1)) if page_count_match else None,
            "num_figures": int(num_figures_match.group(1)) if num_figures_match else None,
        },
        "extractor": "arxiv_api",
    }


ADAPTER = PlatformAdapter(
    platform="arxiv",
    discovery=PlatformDiscoveryPlan(resource_types=("paper",), canonicalizer="arxiv"),
    fetch=FETCH_PLAN,
    extract=EXTRACT_PLAN,
    normalize=NORMALIZE_PLAN,
    enrich=ENRICH_PLAN,
    error=PlatformErrorPlan(normalized_code="ARXIV_FETCH_FAILED"),
    resolve_backend_fn=default_backend_resolver(FETCH_PLAN),
    fetch_fn=default_fetch_executor(_fetch_arxiv_api),
    extract_fn=_extract_arxiv,
    normalize_fn=hook_normalizer(NORMALIZE_PLAN.hook_name),
    enrichment_fn=route_enrichment_groups(ENRICH_PLAN),
)
