from __future__ import annotations

import hashlib
from typing import Any


IGNORED_RECORD_KEYS = {
    "artifacts",
    "chunks",
    "discovery",
    "document_blocks",
    "enrichment",
    "errors",
    "extraction_quality",
    "metadata",
    "source",
}


def build_enrich_input(record: dict[str, Any]) -> dict[str, Any]:
    metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
    enrich_input: dict[str, Any] = {
        "doc_id": record.get("doc_id") or _build_doc_id(record["canonical_url"], record.get("platform", "unknown")),
        "canonical_url": record["canonical_url"],
        "platform": record.get("platform", "unknown"),
        "resource_type": record.get("resource_type") or record.get("entity_type") or "unknown",
        "plain_text": record.get("plain_text", ""),
        "markdown": record.get("markdown", ""),
        "structured": record.get("structured", {}),
        "title": metadata.get("title") or record.get("title"),
        "description": metadata.get("description") or record.get("description"),
    }

    for key, value in record.items():
        if key not in IGNORED_RECORD_KEYS and key not in enrich_input and value not in (None, "", [], {}):
            enrich_input[key] = value

    for key, value in flatten_enrichment_source_fields(record.get("structured", {})).items():
        if key not in enrich_input and value not in (None, "", [], {}):
            enrich_input[key] = value

    for key, value in metadata.items():
        if key not in enrich_input and value not in (None, "", [], {}):
            enrich_input[key] = value

    _apply_common_aliases(enrich_input)
    _apply_platform_aliases(enrich_input)
    return enrich_input


def flatten_enrichment_source_fields(value: Any) -> dict[str, Any]:
    flattened: dict[str, Any] = {}
    if not isinstance(value, dict):
        return flattened

    for key, nested in value.items():
        if key not in flattened and nested not in (None, "", [], {}):
            flattened[key] = nested
        if isinstance(nested, dict):
            for nested_key, nested_value in flatten_enrichment_source_fields(nested).items():
                if nested_key not in flattened and nested_value not in (None, "", [], {}):
                    flattened[nested_key] = nested_value
    return flattened


def _build_doc_id(canonical_url: str, platform: str) -> str:
    payload = f"{platform}:{canonical_url}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:16]


def _setdefault_from_candidates(document: dict[str, Any], target: str, *candidates: str) -> None:
    if document.get(target) not in (None, "", [], {}):
        return
    for candidate in candidates:
        value = document.get(candidate)
        if value not in (None, "", [], {}):
            document[target] = value
            return


def _apply_common_aliases(document: dict[str, Any]) -> None:
    _setdefault_from_candidates(document, "summary", "extract", "abstract", "description")
    _setdefault_from_candidates(document, "extract", "summary", "plain_text")
    _setdefault_from_candidates(document, "abstract", "summary", "description", "plain_text")
    _setdefault_from_candidates(document, "full_text", "plain_text")
    _setdefault_from_candidates(document, "references", "citations", "refs")
    _setdefault_from_candidates(document, "bullet_points", "highlights", "bullets")
    _setdefault_from_candidates(document, "category", "categories", "category_path")
    _setdefault_from_candidates(document, "reviews_count", "review_count", "ratings_count")
    _setdefault_from_candidates(document, "review_text", "review_body", "body", "content")
    _setdefault_from_candidates(document, "seller_name", "seller", "merchant_name", "shop_name")
    _setdefault_from_candidates(document, "price", "current_price")
    _setdefault_from_candidates(document, "images", "image_urls")
    _setdefault_from_candidates(document, "balance", "eth_balance")
    _setdefault_from_candidates(document, "token_balances", "tokens", "assets")
    _setdefault_from_candidates(document, "transactions", "txs", "transaction_list")
    _setdefault_from_candidates(document, "code", "bytecode", "runtime_code")
    _setdefault_from_candidates(document, "source_code", "verified_source", "contract_source")
    _setdefault_from_candidates(document, "abi", "contract_abi")
    _setdefault_from_candidates(document, "tx_hash", "hash", "transaction_hash", "identifier")
    _setdefault_from_candidates(document, "from_address", "from")
    _setdefault_from_candidates(document, "to_address", "to")
    _setdefault_from_candidates(document, "input", "input_data", "calldata")
    _setdefault_from_candidates(document, "gas_used", "gasUsed")
    _setdefault_from_candidates(document, "gas_price", "gasPrice")
    _setdefault_from_candidates(document, "block_number", "blockNumber")
    _setdefault_from_candidates(document, "logs", "events", "log_entries")


def _apply_platform_aliases(document: dict[str, Any]) -> None:
    platform = str(document.get("platform") or "")
    resource_type = str(document.get("resource_type") or "")

    if platform == "linkedin" and resource_type == "profile":
        _setdefault_from_candidates(document, "name", "title")
        _setdefault_from_candidates(document, "profile_url", "canonical_url")
        _setdefault_from_candidates(document, "avatar_url", "avatar", "avatar_url")
        _setdefault_from_candidates(document, "banner_image", "banner", "banner_url")
        _setdefault_from_candidates(document, "follower_count", "followers")
        _setdefault_from_candidates(document, "connection_count", "connections")
        _setdefault_from_candidates(document, "posts", "featured_content", "posts_count")
        return

    if platform == "linkedin" and resource_type == "company":
        _setdefault_from_candidates(document, "company_name", "title")
        _setdefault_from_candidates(document, "about", "description", "summary", "plain_text")
        _setdefault_from_candidates(document, "employee_count", "staff_count")
        _setdefault_from_candidates(document, "company_url", "canonical_url")
        _setdefault_from_candidates(document, "website", "company_website")
        _setdefault_from_candidates(document, "headquarters_location", "headquarters", "headquarter")
        _setdefault_from_candidates(document, "company_posts", "posts_recent")
        _setdefault_from_candidates(document, "job_postings", "jobs", "open_jobs")
        return

    if platform == "linkedin" and resource_type == "job":
        _setdefault_from_candidates(document, "job_title", "title", "headline")
        _setdefault_from_candidates(document, "job_description", "description", "plain_text")
        _setdefault_from_candidates(document, "location", "job_location", "city")
        _setdefault_from_candidates(document, "posted_date", "date_posted", "published_at", "listed_at")
        _setdefault_from_candidates(document, "job_summary", "summary")
        _setdefault_from_candidates(document, "required_skills_seed", "skills", "required_skills")
        return

    if platform == "linkedin" and resource_type == "post":
        _setdefault_from_candidates(document, "post_text", "body", "plain_text")
        _setdefault_from_candidates(document, "like_count", "num_likes", "reaction_count")
        _setdefault_from_candidates(document, "comment_count", "num_comments", "comment_count")
        _setdefault_from_candidates(document, "share_count", "num_shares", "repost_count")
        _setdefault_from_candidates(document, "author_profile_url", "user_url", "author_profile_url")
        _setdefault_from_candidates(document, "author_headline", "headline")
        _setdefault_from_candidates(document, "posted_date", "date_posted")
        if document.get("post_media_urls") in (None, "", [], {}):
            media_urls: list[Any] = []
            for key in ("images", "videos"):
                value = document.get(key)
                if isinstance(value, list):
                    media_urls.extend(item for item in value if item not in (None, ""))
            if media_urls:
                document["post_media_urls"] = media_urls
        return

    if platform == "wikipedia" and resource_type == "article":
        _setdefault_from_candidates(document, "extract", "summary", "plain_text")
        _setdefault_from_candidates(document, "raw_text", "plain_text")
        _setdefault_from_candidates(document, "HTML", "markdown")
        return

    if platform == "arxiv" and resource_type == "paper":
        _setdefault_from_candidates(document, "abstract", "summary", "description", "plain_text")
        _setdefault_from_candidates(document, "full_text", "plain_text")
        _setdefault_from_candidates(document, "raw_text", "plain_text")
        return

    if platform == "amazon" and resource_type == "product":
        _setdefault_from_candidates(document, "brand", "manufacturer")
        _setdefault_from_candidates(document, "availability", "stock_status")
        _setdefault_from_candidates(document, "fulfillment", "shipping_type")
        _setdefault_from_candidates(document, "variants", "variant_options", "product_variants")
        return

    if platform == "amazon" and resource_type == "review":
        _setdefault_from_candidates(document, "review_text", "plain_text")
        _setdefault_from_candidates(document, "reviewer_name", "author_name", "author", "reviewer", "user_name")
        _setdefault_from_candidates(document, "author_name", "reviewer_name", "author", "reviewer", "user_name")
        _setdefault_from_candidates(document, "rating", "review_rating", "stars")
        _setdefault_from_candidates(document, "verified_purchase", "is_verified_purchase", "verified")
        _setdefault_from_candidates(document, "review_images", "photo_urls", "image_urls", "images")
        _setdefault_from_candidates(document, "date_posted", "review_date", "date", "posted_date")
        return

    if platform == "amazon" and resource_type == "seller":
        _setdefault_from_candidates(document, "seller_name", "title", "name")
        _setdefault_from_candidates(document, "product_listings", "products", "listings", "items")
        _setdefault_from_candidates(document, "seller_since", "since", "shop_since", "joined_date")
        _setdefault_from_candidates(document, "seller_rating", "stars")
        _setdefault_from_candidates(document, "feedback_count", "feedbacks")
        return

    if platform == "base" and resource_type == "address":
        _setdefault_from_candidates(document, "address", "identifier", "canonical_url")
        return

    if platform == "base" and resource_type == "contract":
        _setdefault_from_candidates(document, "address", "identifier", "contract_address", "canonical_url")
        _setdefault_from_candidates(document, "contract_address", "address", "identifier")
        return

    if platform == "base" and resource_type == "defi":
        _setdefault_from_candidates(document, "protocol_id", "identifier", "title")
