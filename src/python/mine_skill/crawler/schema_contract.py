from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse

from crawler.normalize.amazon_normalizers import (
    normalize_date_text,
    normalize_price,
    normalize_rating,
    normalize_reviews_count,
)


Record = dict[str, Any]
Resolver = Callable[[Record], Any]

SCHEMA_DIR = Path(__file__).resolve().parents[1] / "schema"

SCHEMA_NAME_BY_PLATFORM_RESOURCE: dict[tuple[str, str], str] = {
    ("amazon", "product"): "amazon_products",
    ("amazon", "review"): "amazon_reviews",
    ("amazon", "seller"): "amazon_sellers",
    ("arxiv", "paper"): "arxiv",
    ("arxiv", "article"): "arxiv",
    ("linkedin", "company"): "linkedin_company",
    ("linkedin", "job"): "linkedin_jobs",
    ("linkedin", "post"): "linkedin_posts",
    ("linkedin", "profile"): "linkedin_profiles",
    ("wikipedia", "article"): "wikipedia",
}


@dataclass(frozen=True, slots=True)
class SchemaContract:
    dataset_name: str
    schema_path: Path
    schema: dict[str, Any]
    property_names: tuple[str, ...]
    required_fields: tuple[str, ...]


def get_schema_contract(record: Record) -> SchemaContract:
    platform = str(record.get("platform") or "").strip().lower()
    resource_type = str(record.get("resource_type") or "").strip().lower()
    if not platform or not resource_type:
        inferred_platform, inferred_resource_type = _infer_record_kind(record)
        platform = platform or inferred_platform
        resource_type = resource_type or inferred_resource_type
    dataset_name = SCHEMA_NAME_BY_PLATFORM_RESOURCE.get((platform, resource_type))
    if dataset_name is None:
        raise ValueError(f"unsupported schema contract for platform={platform!r} resource_type={resource_type!r}")
    return _load_schema_contract(dataset_name)


@lru_cache(maxsize=None)
def _load_schema_contract(dataset_name: str) -> SchemaContract:
    schema_path = SCHEMA_DIR / f"{dataset_name}.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    properties = schema.get("properties", {})
    required = schema.get("required", [])
    return SchemaContract(
        dataset_name=dataset_name,
        schema_path=schema_path,
        schema=schema,
        property_names=tuple(properties.keys()) if isinstance(properties, dict) else (),
        required_fields=tuple(required) if isinstance(required, list) else (),
    )


def flatten_record_for_schema(record: Record) -> dict[str, Any]:
    contract = get_schema_contract(record)
    flattened: dict[str, Any] = {}
    for field_name in contract.property_names:
        value = _resolve_schema_field(record, field_name)
        normalizer = FIELD_NORMALIZERS.get(field_name)
        if normalizer is not None:
            value = normalizer(value)
        if value in (None, ""):
            continue
        flattened[field_name] = value
    return flattened


def _resolve_schema_field(record: Record, field_name: str) -> Any:
    resolver = FIELD_RESOLVERS.get(field_name)
    if resolver is not None:
        resolved = resolver(record)
        if resolved not in (None, ""):
            return resolved

    for value in _direct_values(record, field_name):
        if value not in (None, ""):
            return value

    return None


def _direct_values(record: Record, field_name: str) -> list[Any]:
    values: list[Any] = []
    values.append(record.get(field_name))
    structured = record.get("structured")
    if isinstance(structured, dict):
        linkedin_structured = structured.get("linkedin")
        if isinstance(linkedin_structured, dict):
            values.append(linkedin_structured.get(field_name))
        values.append(structured.get(field_name))
    enrichment = record.get("enrichment")
    if isinstance(enrichment, dict):
        enriched_fields = enrichment.get("enriched_fields")
        if isinstance(enriched_fields, dict):
            values.append(enriched_fields.get(field_name))
    metadata = record.get("metadata")
    if isinstance(metadata, dict):
        values.append(metadata.get(field_name))
    return values


def _canonical_url(record: Record) -> str | None:
    value = record.get("canonical_url") or record.get("url")
    return str(value).strip() if value not in (None, "") else None


def _source_url(record: Record) -> str | None:
    return _first(
        record.get("source_url"),
        _structured(record).get("source_url"),
        _metadata(record).get("source_url"),
        _structured(record).get("URL"),
        record.get("URL"),
        record.get("url"),
        record.get("canonical_url"),
    )


def _infer_record_kind(record: Record) -> tuple[str, str]:
    canonical_url = _canonical_url(record) or ""
    parsed = urlparse(canonical_url)
    hostname = (parsed.hostname or "").lower()
    path = parsed.path.lower()
    if "wikipedia.org" in hostname:
        return "wikipedia", "article"
    if "linkedin.com" in hostname:
        if "/in/" in path:
            return "linkedin", "profile"
        if "/company/" in path:
            return "linkedin", "company"
        if "/jobs/view/" in path:
            return "linkedin", "job"
        if "/feed/update/" in path:
            return "linkedin", "post"
    if "amazon." in hostname:
        if "/dp/" in path or "/gp/product/" in path:
            return "amazon", "product"
        if "seller=" in parsed.query:
            return "amazon", "seller"
        if "/review/" in path or "/gp/customer-reviews/" in path:
            return "amazon", "review"
    if "arxiv.org" in hostname:
        return "arxiv", "paper"
    return "", ""


def _structured(record: Record) -> dict[str, Any]:
    value = record.get("structured")
    return value if isinstance(value, dict) else {}


def _metadata(record: Record) -> dict[str, Any]:
    value = record.get("metadata")
    return value if isinstance(value, dict) else {}


def _first(*values: Any) -> Any:
    for value in values:
        if value not in (None, ""):
            return value
    return None


def _join_strings(value: Any) -> str | None:
    if isinstance(value, str):
        text = value.strip()
        return text or None
    if isinstance(value, (list, tuple)):
        parts = [str(item).strip() for item in value if str(item).strip()]
        if parts:
            return ", ".join(parts)
    return None


def _count_items(value: Any) -> int | None:
    if isinstance(value, (list, tuple, set)):
        return len(value)
    return None


def _wikipedia_has_infobox(record: Record) -> bool | None:
    structured = _structured(record)
    metadata = _metadata(record)

    infobox = _first(structured.get("infobox_structured"), structured.get("infobox"))
    if isinstance(infobox, dict):
        return bool(infobox)

    pageprops = metadata.get("pageprops")
    if isinstance(pageprops, dict):
        for key in ("infobox", "wikibase_item", "wikibase-shortdesc"):
            if key in pageprops:
                return True
    return None


def _wikipedia_language(record: Record) -> str | None:
    explicit = _first(record.get("language"), _structured(record).get("language"), _metadata(record).get("language"))
    if explicit not in (None, ""):
        return explicit
    canonical_url = _canonical_url(record)
    if not canonical_url:
        return None
    hostname = urlparse(canonical_url).hostname or ""
    parts = hostname.split(".")
    return parts[0] if len(parts) >= 3 else None


def _amazon_seller_id(record: Record) -> str | None:
    candidate = _first(record.get("seller_id"), _structured(record).get("seller_id"))
    if candidate not in (None, ""):
        return candidate
    canonical_url = _canonical_url(record)
    if not canonical_url:
        return None
    return parse_qs(urlparse(canonical_url).query).get("seller", [None])[0]


def _amazon_review_id(record: Record) -> str | None:
    candidate = _first(record.get("review_id"), _structured(record).get("review_id"))
    if candidate not in (None, ""):
        return candidate
    canonical_url = _canonical_url(record)
    if not canonical_url:
        return None
    path_parts = [segment for segment in urlparse(canonical_url).path.split("/") if segment]
    if "customer-reviews" in path_parts:
        index = path_parts.index("customer-reviews")
        if index + 1 < len(path_parts):
            return path_parts[index + 1]
    return None


def _linkedin_post_id(record: Record) -> str | None:
    candidate = _first(
        record.get("post_id"),
        _structured(record).get("post_id"),
        _structured(record).get("source_id"),
        record.get("source_id"),
        record.get("activity_urn"),
        _structured(record).get("activity_urn"),
    )
    if isinstance(candidate, str):
        text = candidate.strip()
        if text.isdigit():
            return text
        if "activity:" in text:
            tail = text.rsplit("activity:", 1)[-1]
            if tail.isdigit():
                return tail
    canonical_url = _canonical_url(record)
    if not canonical_url:
        return None
    path = urlparse(canonical_url).path
    marker = "activity:"
    if marker in path:
        tail = path.rsplit(marker, 1)[-1].strip("/")
        if tail.isdigit():
            return tail
    return None


def _amazon_marketplace(record: Record) -> str | None:
    explicit = _first(record.get("marketplace"), _structured(record).get("marketplace"))
    if explicit not in (None, ""):
        return explicit
    canonical_url = _canonical_url(record)
    if not canonical_url:
        return None
    hostname = (urlparse(canonical_url).hostname or "").lower()
    if "amazon." not in hostname:
        return None
    return hostname.rsplit("amazon.", 1)[-1] or None


def _amazon_price_data(record: Record) -> dict[str, Any]:
    raw_price = _first(
        record.get("price"),
        _structured(record).get("price"),
        record.get("price_text"),
        _structured(record).get("price_text"),
    )
    if raw_price in (None, ""):
        return {}
    return normalize_price(str(raw_price))


def _amazon_categories(record: Record) -> list[str] | None:
    for candidate in (
        record.get("categories"),
        _structured(record).get("categories"),
        record.get("breadcrumbs"),
        _structured(record).get("breadcrumbs"),
        record.get("category"),
        _structured(record).get("category"),
    ):
        normalized = _normalize_string_list(candidate)
        if normalized:
            return normalized
    return None


def _amazon_category_tree(record: Record) -> str | None:
    explicit = _first(
        record.get("category_tree"),
        _structured(record).get("category_tree"),
    )
    if explicit not in (None, ""):
        return str(explicit).strip()
    categories = _amazon_categories(record)
    if categories:
        return " > ".join(categories)
    return None


def _amazon_estimated_monthly_sales(record: Record) -> int | None:
    explicit = _first(
        record.get("estimated_monthly_sales"),
        _structured(record).get("estimated_monthly_sales"),
    )
    if isinstance(explicit, int):
        return explicit
    if isinstance(explicit, float):
        return int(explicit)
    sales_hint = _first(record.get("sales_volume_hint"), _structured(record).get("sales_volume_hint"))
    if not isinstance(sales_hint, str):
        return None
    text = sales_hint.strip().lower()
    match = re.search(r"(\d+(?:[.,]\d+)?)\s*([km])?\+?", text)
    if not match:
        return None
    value_text, suffix = match.groups()
    try:
        value = float(value_text.replace(",", "."))
    except ValueError:
        return None
    multiplier = 1
    if suffix == "k":
        multiplier = 1000
    elif suffix == "m":
        multiplier = 1000000
    estimated = int(value * multiplier)
    return estimated or None


def _normalize_string_list(value: Any) -> list[str] | None:
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else None
    if isinstance(value, (list, tuple, set)):
        items = [str(item).strip() for item in value if str(item).strip()]
        return items or None
    return None


def _normalize_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        text = value.strip().lower()
        if text in {"true", "yes", "y", "1", "verified purchase"}:
            return True
        if text in {"false", "no", "n", "0"}:
            return False
    return None


def _to_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if value in (None, ""):
        return None
    text = str(value).strip()
    return int(text) if text.isdigit() else None


def _extract_company_from_headline(headline: str | None) -> str | None:
    """Extract company name from LinkedIn headline patterns like 'Title at Company' or 'Title, Company'."""
    if not headline:
        return None
    text = str(headline).strip()
    # Pattern: "Title at Company"
    if " at " in text.lower():
        parts = text.lower().split(" at ", 1)
        if len(parts) == 2:
            company = text[text.lower().index(" at ") + 4 :].strip()
            # Remove trailing qualifiers
            for sep in [" and ", " | ", " - "]:
                if sep in company:
                    company = company.split(sep)[0].strip()
            if company:
                return company
    # Pattern: "Title, Company"
    if ", " in text:
        parts = text.split(", ")
        if len(parts) >= 2:
            candidate = parts[1].strip()
            if candidate:
                return candidate.split(" and ")[0].strip()
    return None


def _normalize_wikipedia_entity_type(value: Any) -> str | None:
    if value in (None, ""):
        return None
    normalized = str(value).strip().lower()
    mapping = {
        "person": "person",
        "place": "place",
        "organization": "organization",
        "org": "organization",
        "event": "event",
        "concept": "concept",
        "thing": "thing",
        "object": "thing",
        "article": None,
    }
    if normalized in mapping:
        return mapping[normalized]
    return None


def _normalize_arxiv_authors(value: Any) -> list[dict[str, Any]] | None:
    if value in (None, "", [], {}):
        return None
    if not isinstance(value, list):
        return None
    normalized: list[dict[str, Any]] = []
    for item in value:
        if isinstance(item, dict):
            name = str(item.get("name") or item.get("full_name") or "").strip()
            if not name:
                continue
            normalized.append(
                {
                    "name": name,
                    "affiliation": item.get("affiliation") or item.get("affiliation_standardized"),
                }
            )
            continue
        name = str(item).strip()
        if name:
            normalized.append({"name": name, "affiliation": None})
    return normalized or None


def _normalize_arxiv_versions(value: Any) -> list[dict[str, Any]] | None:
    if value in (None, "", [], {}):
        return None
    if not isinstance(value, list):
        return None
    normalized: list[dict[str, Any]] = []
    for item in value:
        if isinstance(item, dict):
            normalized.append(item)
            continue
        version = str(item).strip()
        if version:
            normalized.append({"version": version})
    return normalized or None


def _normalize_rating_value(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        numeric = float(value)
        return numeric if 0 <= numeric <= 5 else None
    if value in (None, ""):
        return None
    return normalize_rating(str(value))


def _normalize_count_value(value: Any) -> int | None:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if value in (None, ""):
        return None
    return normalize_reviews_count(str(value))


def _normalize_date_value(value: Any) -> str | None:
    if value in (None, ""):
        return None
    return normalize_date_text(str(value)) or str(value).strip() or None


def _amazon_product_dedup_key(record: Record) -> str | None:
    asin = _first(record.get("asin"), _structured(record).get("asin"))
    if asin in (None, ""):
        return None
    marketplace = _amazon_marketplace(record)
    return f"{asin}:{marketplace}" if marketplace not in (None, "") else str(asin)


def _amazon_seller_dedup_key(record: Record) -> str | None:
    seller_id = _amazon_seller_id(record)
    if seller_id in (None, ""):
        return None
    marketplace = _amazon_marketplace(record)
    return f"{seller_id}:{marketplace}" if marketplace not in (None, "") else str(seller_id)


def _amazon_review_dedup_key(record: Record) -> str | None:
    review_id = _amazon_review_id(record)
    if review_id in (None, ""):
        return None
    marketplace = _amazon_marketplace(record)
    return f"{review_id}:{marketplace}" if marketplace not in (None, "") else str(review_id)


def _get_voyager_profile(record: Record) -> dict[str, Any]:
    """Extract the primary profile element from voyager data."""
    voyager = record.get("voyager") or _structured(record).get("voyager") or {}
    data = voyager.get("data", {})
    elements = data.get("identityDashProfilesByMemberIdentity", {}).get("elements", [])
    return elements[0] if elements else {}



def _linkedin_profile_language(record: Record) -> str | None:
    """Extract the primary language from the profile."""
    profile = _get_voyager_profile(record)
    primary_locale = profile.get("primaryLocale") or {}
    lang = primary_locale.get("language")
    if lang:
        return lang
    supported_locales = profile.get("supportedLocales") or []
    if supported_locales and isinstance(supported_locales[0], dict):
        return supported_locales[0].get("language")
    return None


def _linkedin_account_created(record: Record) -> str | None:
    """Extract account creation timestamp."""
    profile = _get_voyager_profile(record)
    created = profile.get("created")
    if isinstance(created, (int, float)) and created > 0:
        # Convert milliseconds to ISO date
        from datetime import datetime, timezone
        try:
            dt = datetime.fromtimestamp(created / 1000, tz=timezone.utc)
            return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        except (ValueError, OSError):
            pass
    return None


def _linkedin_connections(record: Record) -> int | None:
    """Extract connection count."""
    for key in ("connections", "connectionCount", "connection_count"):
        value = record.get(key) or _structured(record).get(key)
        if isinstance(value, int):
            return value
    return None


def _linkedin_open_to_work(record: Record) -> bool | None:
    """Check if the profile shows 'Open to Work' status."""
    profile = _get_voyager_profile(record)
    # Check for open to work status
    for key in ("openToWork", "isOpenToWork", "open_to_work"):
        value = profile.get(key)
        if isinstance(value, bool):
            return value
    # Check in structured data
    structured = _structured(record)
    for key in ("openToWork", "isOpenToWork", "open_to_work"):
        value = structured.get(key)
        if isinstance(value, bool):
            return value
    return None


def _calculate_profile_completeness(record: Record) -> float | None:
    """Calculate profile completeness score based on filled fields."""
    key_fields = [
        "name", "headline", "about", "avatar", "city", "country_code",
        "experience", "education", "skills_extracted", "current_company"
    ]
    filled = 0
    for field in key_fields:
        value = record.get(field) or _structured(record).get(field)
        if value not in (None, "", []):
            filled += 1
    return round(filled / len(key_fields), 2) if key_fields else None


def _is_custom_profile_url(record: Record) -> bool | None:
    """Check if the profile has a custom vanity URL."""
    url = _canonical_url(record)
    if not url:
        return None
    public_id = record.get("public_identifier") or _structured(record).get("public_identifier")
    if not public_id:
        # Try to extract from URL
        path = urlparse(url).path
        if "/in/" in path:
            parts = path.split("/in/")
            if len(parts) > 1:
                public_id = parts[1].strip("/")
    if not public_id:
        return None
    # Check if it's a custom URL (not the default numeric format)
    return not public_id.replace("-", "").isdigit()


def _amazon_dedup_key(record: Record) -> str | None:
    platform = str(record.get("platform") or "").strip().lower()
    resource_type = str(record.get("resource_type") or "").strip().lower()
    if not platform or not resource_type:
        platform, resource_type = _infer_record_kind(record)
    if platform != "amazon":
        return None
    if resource_type == "seller":
        return _amazon_seller_dedup_key(record)
    if resource_type == "review":
        return _amazon_review_dedup_key(record)
    return _amazon_product_dedup_key(record)


FIELD_RESOLVERS: dict[str, Resolver] = {
    "ID": lambda record: _first(
        record.get("ID"),
        _structured(record).get("ID"),
        record.get("linkedin_num_id"),
        _structured(record).get("linkedin_num_id"),
        record.get("company_id"),
        _structured(record).get("company_id"),
        _structured(record).get("source_id"),
        record.get("source_id"),
    ),
    "URL": _source_url,
    "input_url": _source_url,
    "canonical_url": lambda record: _first(record.get("canonical_url"), _structured(record).get("canonical_url"), record.get("url")),
    "title": lambda record: _first(_structured(record).get("title"), _metadata(record).get("title"), record.get("title")),
    "name": lambda record: _first(_structured(record).get("name"), _structured(record).get("title"), _metadata(record).get("title"), record.get("name"), record.get("title")),
    "about": lambda record: _first(
        record.get("about"),
        _structured(record).get("about"),
        _structured(record).get("about_summary"),
        _structured(record).get("description"),
        _metadata(record).get("description"),
        record.get("summary"),
    ),
    "about_summary": lambda record: _first(
        record.get("about_summary"),
        _structured(record).get("about_summary"),
        record.get("about"),
        _structured(record).get("about"),
    ),
    "seller_name": lambda record: _first(
        record.get("seller_name"),
        _structured(record).get("seller_name"),
        record.get("name"),
        _structured(record).get("name"),
        record.get("seller"),
        _structured(record).get("seller"),
        _metadata(record).get("title"),
        record.get("title"),
    ),
    "job_title": lambda record: _first(
        _structured(record).get("job_title"),
        _structured(record).get("title"),
        _metadata(record).get("job_title"),
        _metadata(record).get("title"),
        record.get("job_title"),
        record.get("title"),
    ),
    "city": lambda record: _first(
        record.get("city"),
        _structured(record).get("city"),
        record.get("location"),
        _structured(record).get("location"),
    ),
    "country_code": lambda record: _first(
        record.get("country_code"),
        _structured(record).get("country_code"),
    ),
    "content_creator_tier": lambda record: _first(
        record.get("content_creator_tier"),
        _structured(record).get("content_creator_tier"),
    ),
    "featured_content": lambda record: _first(
        record.get("featured_content"),
        _structured(record).get("featured_content"),
    ),
    "industry": lambda record: _first(
        record.get("industry"),
        _structured(record).get("industry"),
    ),
    "founded_year": lambda record: _first(
        record.get("founded_year"),
        _structured(record).get("founded_year"),
    ),
    "company_size_range": lambda record: _first(
        record.get("company_size_range"),
        _structured(record).get("company_size_range"),
        record.get("staff_count_range"),
        _structured(record).get("staff_count_range"),
    ),
    "staff_count": lambda record: _first(
        record.get("staff_count"),
        _structured(record).get("staff_count"),
        record.get("employee_count"),
        _structured(record).get("employee_count"),
        record.get("employees_in_linkedin"),
        _structured(record).get("employees_in_linkedin"),
    ),
    "text": lambda record: _first(
        record.get("text"),
        _structured(record).get("text"),
        record.get("post_text"),
        _structured(record).get("post_text"),
        record.get("body"),
        _structured(record).get("body"),
        record.get("plain_text"),
    ),
    "post_text": lambda record: _first(
        record.get("post_text"),
        _structured(record).get("post_text"),
        record.get("plain_text"),
        record.get("cleaned_data"),
        record.get("markdown"),
    ),
    "review_text": lambda record: _first(
        record.get("review_text"),
        _structured(record).get("review_text"),
        record.get("review_body"),
        _structured(record).get("review_body"),
        record.get("plain_text"),
        record.get("cleaned_data"),
    ),
    "author_name": lambda record: _first(
        record.get("author_name"),
        _structured(record).get("author_name"),
        record.get("author"),
        _structured(record).get("author"),
        record.get("reviewer_name"),
        _structured(record).get("reviewer_name"),
        record.get("reviewer"),
        _structured(record).get("reviewer"),
        record.get("user_name"),
        _structured(record).get("user_name"),
    ),
    "content": lambda record: _first(record.get("plain_text"), record.get("cleaned_data"), record.get("markdown")),
    "raw_text": lambda record: _first(
        record.get("raw_text"),
        _structured(record).get("raw_text"),
        record.get("plain_text"),
        record.get("cleaned_data"),
        record.get("markdown"),
    ),
    "HTML": lambda record: _first(record.get("HTML"), _structured(record).get("HTML"), record.get("html"), _structured(record).get("html"), record.get("markdown")),
    "article_summary": lambda record: _first(
        record.get("article_summary"),
        _structured(record).get("article_summary"),
        record.get("summary"),
        _structured(record).get("summary"),
        _metadata(record).get("description"),
    ),
    "has_infobox": _wikipedia_has_infobox,
    "infobox_structured": lambda record: _first(
        record.get("infobox_structured"),
        _structured(record).get("infobox_structured"),
        _structured(record).get("infobox"),
    ),
    "linkedin_num_id": lambda record: _first(record.get("linkedin_num_id"), _structured(record).get("linkedin_num_id"), _structured(record).get("source_id"), record.get("source_id")),
    "company_id": lambda record: _first(record.get("company_id"), _structured(record).get("company_id"), _structured(record).get("source_id"), record.get("source_id")),
    "current_company_name": lambda record: _first(
        record.get("current_company_name"),
        _structured(record).get("current_company_name"),
        record.get("current_company"),
        _structured(record).get("current_company"),
        _extract_company_from_headline(
            _first(record.get("headline"), _structured(record).get("headline"), record.get("position"), _structured(record).get("position"))
        ),
    ),
    "current_company": lambda record: _first(
        record.get("current_company"),
        _structured(record).get("current_company"),
        record.get("current_company_name"),
        _structured(record).get("current_company_name"),
        _extract_company_from_headline(
            _first(record.get("headline"), _structured(record).get("headline"), record.get("position"), _structured(record).get("position"))
        ),
    ),
    "current_company_id": lambda record: _first(
        record.get("current_company_id"),
        _structured(record).get("current_company_id"),
    ),
    "people_also_viewed": lambda record: _first(
        record.get("people_also_viewed"),
        _structured(record).get("people_also_viewed"),
    ),
    "education": lambda record: _first(
        record.get("education"),
        _structured(record).get("education"),
        record.get("educations_details"),
        _structured(record).get("educations_details"),
    ),
    "experience": lambda record: _first(
        record.get("experience"),
        _structured(record).get("experience"),
        record.get("experiences_details"),
        _structured(record).get("experiences_details"),
    ),
    "followers": lambda record: _first(
        record.get("followers"),
        _structured(record).get("followers"),
        record.get("follower_count"),
        _structured(record).get("follower_count"),
    ),
    "position": lambda record: _first(
        record.get("position"),
        _structured(record).get("position"),
        _structured(record).get("headline"),
        _structured(record).get("title"),
        _metadata(record).get("headline"),
    ),
    "website": lambda record: _first(
        record.get("website"),
        _structured(record).get("website"),
        record.get("company_website"),
        _structured(record).get("company_website"),
    ),
    "specialties": lambda record: _first(
        _join_strings(_structured(record).get("specialties")),
        _join_strings(record.get("specialties")),
        record.get("specialties"),
        _structured(record).get("specialties"),
    ),
    "job_posting_id": lambda record: _first(record.get("job_posting_id"), _structured(record).get("job_posting_id"), _structured(record).get("source_id"), record.get("job_id"), record.get("source_id")),
    "job_title_standardized": lambda record: _first(
        record.get("job_title_standardized"),
        _structured(record).get("job_title_standardized"),
        ((record.get("enrichment") or {}).get("enriched_fields") or {}).get("job_title_standardized"),
        ((record.get("enrichment") or {}).get("enriched_fields") or {}).get("standardized_job_title"),
        record.get("standardized_job_title"),
    ),
    "job_summary": lambda record: _first(
        record.get("job_summary"),
        _structured(record).get("job_summary"),
        record.get("summary"),
        _structured(record).get("summary"),
        record.get("plain_text"),
    ),
    "remote_policy_detail": lambda record: _first(
        record.get("remote_policy_detail"),
        _structured(record).get("remote_policy_detail"),
        ((record.get("enrichment") or {}).get("enriched_fields") or {}).get("remote_policy_detail"),
        ((record.get("enrichment") or {}).get("enriched_fields") or {}).get("remote_policy"),
        record.get("remote_policy"),
    ),
    "post_id": _linkedin_post_id,
    "entities_mentioned": lambda record: _first(
        record.get("entities_mentioned"),
        _structured(record).get("entities_mentioned"),
        record.get("entities"),
        _structured(record).get("entities"),
        record.get("mentions"),
        _structured(record).get("mentions"),
    ),
    "page_id": lambda record: _first(record.get("page_id"), _structured(record).get("page_id"), _metadata(record).get("page_id")),
    "language": _wikipedia_language,
    "date_posted": lambda record: _first(
        record.get("date_posted"),
        _structured(record).get("date_posted"),
        record.get("review_date"),
        _structured(record).get("review_date"),
        record.get("date"),
        _structured(record).get("date"),
        record.get("posted_date"),
        _structured(record).get("posted_date"),
        _structured(record).get("published_at"),
        _metadata(record).get("date_posted"),
        _metadata(record).get("posted_date"),
        _metadata(record).get("published_at"),
        record.get("published_at"),
    ),
    "asin": lambda record: _first(record.get("asin"), _structured(record).get("asin")),
    "marketplace": _amazon_marketplace,
    "categories": _amazon_categories,
    "breadcrumbs": _amazon_categories,
    "category_tree": _amazon_category_tree,
    "initial_price": lambda record: _first(record.get("initial_price"), _structured(record).get("initial_price"), _amazon_price_data(record).get("initial_price")),
    "final_price": lambda record: _first(record.get("final_price"), _structured(record).get("final_price"), _amazon_price_data(record).get("final_price")),
    "currency": lambda record: _first(record.get("currency"), _structured(record).get("currency"), _amazon_price_data(record).get("currency")),
    "discount": lambda record: _first(record.get("discount"), _structured(record).get("discount"), _amazon_price_data(record).get("discount")),
    "estimated_monthly_sales": _amazon_estimated_monthly_sales,
    "variant_purchased": lambda record: _first(
        record.get("variant_purchased"),
        _structured(record).get("variant_purchased"),
        record.get("purchased_variant"),
        _structured(record).get("purchased_variant"),
    ),
    "seller_id": _amazon_seller_id,
    "review_id": _amazon_review_id,
    "feedbacks": lambda record: _first(
        record.get("feedbacks"),
        _structured(record).get("feedbacks"),
        record.get("feedback_count"),
        _structured(record).get("feedback_count"),
    ),
    "stars": lambda record: _first(
        record.get("stars"),
        _structured(record).get("stars"),
        record.get("seller_rating"),
        _structured(record).get("seller_rating"),
    ),
    "rating": lambda record: _first(
        record.get("rating"),
        _structured(record).get("rating"),
    ),
    "reviews_count": lambda record: _first(
        record.get("reviews_count"),
        _structured(record).get("reviews_count"),
        record.get("review_count"),
        _structured(record).get("review_count"),
    ),
    "coupon_available": lambda record: _first(
        record.get("coupon_available"),
        _structured(record).get("coupon_available"),
    ),
    "arxiv_id": lambda record: _first(record.get("arxiv_id"), _structured(record).get("arxiv_id")),
    "doi": lambda record: _first(record.get("doi"), _structured(record).get("doi"), record.get("DOI"), _structured(record).get("DOI")),
    "submission_comments": lambda record: _first(
        record.get("submission_comments"),
        _structured(record).get("submission_comments"),
        record.get("comment"),
        _structured(record).get("comment"),
    ),
    "published_date": lambda record: _first(
        record.get("published_date"),
        _structured(record).get("published_date"),
        record.get("submission_date"),
        _structured(record).get("submission_date"),
        record.get("published"),
        _structured(record).get("published"),
    ),
    "updated_date": lambda record: _first(
        record.get("updated_date"),
        _structured(record).get("updated_date"),
        record.get("update_date"),
        _structured(record).get("update_date"),
        record.get("updated"),
        _structured(record).get("updated"),
    ),
    "pdf_url": lambda record: _first(record.get("pdf_url"), _structured(record).get("pdf_url"), record.get("PDF_url"), _structured(record).get("PDF_url")),
    "primary_category": lambda record: _first(
        record.get("primary_category"),
        _structured(record).get("primary_category"),
    ),
    "page_count": lambda record: _first(
        record.get("page_count"),
        _structured(record).get("page_count"),
        record.get("num_pages"),
        _structured(record).get("num_pages"),
    ),
    "figures_count": lambda record: _first(
        record.get("figures_count"),
        _structured(record).get("figures_count"),
        record.get("num_figures"),
        _structured(record).get("num_figures"),
        record.get("figure_count"),
        _structured(record).get("figure_count"),
    ),
    "num_authors": lambda record: _count_items(
        _first(record.get("authors"), _structured(record).get("authors"), _structured(record).get("authors_structured"))
    ),
    "dedup_key": lambda record: _first(
        record.get("dedup_key"),
        _structured(record).get("dedup_key"),
        _first(record.get("linkedin_num_id"), _structured(record).get("linkedin_num_id"), _structured(record).get("source_id"), record.get("source_id")),
        _first(record.get("company_id"), _structured(record).get("company_id"), _structured(record).get("source_id"), record.get("source_id")),
        _first(record.get("job_posting_id"), _structured(record).get("job_posting_id"), _structured(record).get("source_id"), record.get("job_id"), record.get("source_id")),
        _linkedin_post_id(record),
        _amazon_dedup_key(record),
        _wikipedia_dedup_key(record),
        _first(record.get("arxiv_id"), _structured(record).get("arxiv_id")),
    ),
    "frequently_bought_together": lambda record: _first(
        record.get("frequently_bought_together"),
        _structured(record).get("frequently_bought_together"),
        record.get("customers_also_viewed"),
        _structured(record).get("customers_also_viewed"),
    ),
    # LinkedIn profile fields from voyager data
    "profile_url_custom": _is_custom_profile_url,
    "profile_language_detected": _linkedin_profile_language,
    "connections": _linkedin_connections,
    "timestamp": lambda record: _first(
        record.get("timestamp"),
        _structured(record).get("timestamp"),
        record.get("crawl_timestamp"),
        record.get("extraction_timestamp"),
        _linkedin_account_created(record),
    ),
    "avatar": lambda record: _first(
        record.get("avatar"),
        _structured(record).get("avatar"),
        record.get("avatar_url"),
        _structured(record).get("avatar_url"),
        record.get("profile_picture_url"),
        _structured(record).get("profile_picture_url"),
    ),
    "banner_image": lambda record: _first(
        record.get("banner_image"),
        _structured(record).get("banner_image"),
        record.get("background_image"),
        _structured(record).get("background_image"),
    ),
    "featured_content_themes": lambda record: _first(
        record.get("featured_content_themes"),
        _structured(record).get("featured_content_themes"),
    ),
    "personal_brand_focus": lambda record: _first(
        record.get("personal_brand_focus"),
        _structured(record).get("personal_brand_focus"),
    ),
    # Wikipedia fields
    "word_count": lambda record: _first(
        record.get("word_count"),
        _structured(record).get("word_count"),
        record.get("content_length"),
        _structured(record).get("content_length"),
    ),
    "section_count": lambda record: _first(
        record.get("section_count"),
        _structured(record).get("section_count"),
    ),
    "references_count": lambda record: _first(
        record.get("references_count"),
        _structured(record).get("references_count"),
        record.get("ref_count"),
        _structured(record).get("ref_count"),
    ),
    "external_links_count": lambda record: _first(
        record.get("external_links_count"),
        _structured(record).get("external_links_count"),
    ),
    "wikidata_id": lambda record: _first(
        record.get("wikidata_id"),
        _structured(record).get("wikidata_id"),
        _metadata(record).get("wikibase_item"),
    ),
    "entity_type": lambda record: _first(
        record.get("entity_type"),
        _structured(record).get("entity_type"),
    ),
    # arXiv fields
    "abstract": lambda record: _first(
        record.get("abstract"),
        _structured(record).get("abstract"),
        record.get("summary"),
        _structured(record).get("summary"),
    ),
    "authors": lambda record: _first(
        record.get("authors"),
        _structured(record).get("authors"),
        record.get("authors_structured"),
        _structured(record).get("authors_structured"),
    ),
    "secondary_categories": lambda record: _first(
        record.get("secondary_categories"),
        _structured(record).get("secondary_categories"),
        record.get("categories"),
        _structured(record).get("categories"),
    ),
    "versions": lambda record: _first(
        record.get("versions"),
        _structured(record).get("versions"),
    ),
    # Amazon product fields
    "description": lambda record: _first(
        record.get("description"),
        _structured(record).get("description"),
        record.get("product_description"),
        _structured(record).get("product_description"),
    ),
    "features": lambda record: _first(
        record.get("features"),
        _structured(record).get("features"),
        record.get("product_features"),
        _structured(record).get("product_features"),
        record.get("bullet_points"),
        _structured(record).get("bullet_points"),
    ),
    "images": lambda record: _first(
        record.get("images"),
        _structured(record).get("images"),
        record.get("image_urls"),
        _structured(record).get("image_urls"),
    ),
    "brand": lambda record: _first(
        record.get("brand"),
        _structured(record).get("brand"),
        record.get("manufacturer"),
        _structured(record).get("manufacturer"),
    ),
    "availability": lambda record: _first(
        record.get("availability"),
        _structured(record).get("availability"),
        record.get("in_stock"),
        _structured(record).get("in_stock"),
    ),
    "prime_eligible": lambda record: _first(
        record.get("prime_eligible"),
        _structured(record).get("prime_eligible"),
        record.get("is_prime"),
        _structured(record).get("is_prime"),
    ),
    "variations": lambda record: _first(
        record.get("variations"),
        _structured(record).get("variations"),
        record.get("product_variations"),
        _structured(record).get("product_variations"),
    ),
    # LinkedIn company fields
    "headquarters": lambda record: _first(
        record.get("headquarters"),
        _structured(record).get("headquarters"),
        record.get("hq_location"),
        _structured(record).get("hq_location"),
    ),
    "logo_url": lambda record: _first(
        record.get("logo_url"),
        _structured(record).get("logo_url"),
        record.get("logo"),
        _structured(record).get("logo"),
        record.get("company_logo"),
        _structured(record).get("company_logo"),
    ),
    "company_type": lambda record: _first(
        record.get("company_type"),
        _structured(record).get("company_type"),
        record.get("type"),
        _structured(record).get("type"),
    ),
    "locations": lambda record: _first(
        record.get("locations"),
        _structured(record).get("locations"),
        record.get("office_locations"),
        _structured(record).get("office_locations"),
    ),
    # Review fields
    "verified_purchase": lambda record: _normalize_bool(_first(
        record.get("verified_purchase"),
        _structured(record).get("verified_purchase"),
        record.get("verified"),
        _structured(record).get("verified"),
    )),
    "helpful_count": lambda record: _first(
        record.get("helpful_count"),
        _structured(record).get("helpful_count"),
        record.get("helpful_votes"),
        _structured(record).get("helpful_votes"),
    ),
    # Additional LinkedIn fields
    "open_to_work": _linkedin_open_to_work,
    "profile_completeness_score": _calculate_profile_completeness,
    "education_structured": lambda record: _first(
        record.get("education_structured"),
        _structured(record).get("education_structured"),
        record.get("education"),
        _structured(record).get("education"),
    ),
    "experience_structured": lambda record: _first(
        record.get("experience_structured"),
        _structured(record).get("experience_structured"),
        record.get("experience"),
        _structured(record).get("experience"),
    ),
    "educations_details": lambda record: _first(
        record.get("educations_details"),
        _structured(record).get("educations_details"),
        record.get("education"),
        _structured(record).get("education"),
    ),
    "skills_extracted": lambda record: _first(
        record.get("skills_extracted"),
        _structured(record).get("skills_extracted"),
        record.get("skills"),
        _structured(record).get("skills"),
    ),
    "certifications": lambda record: _first(
        record.get("certifications"),
        _structured(record).get("certifications"),
    ),
    "languages": lambda record: _first(
        record.get("languages"),
        _structured(record).get("languages"),
    ),
    "courses": lambda record: _first(
        record.get("courses"),
        _structured(record).get("courses"),
    ),
    "volunteer_experience": lambda record: _first(
        record.get("volunteer_experience"),
        _structured(record).get("volunteer_experience"),
    ),
    "projects_listed": lambda record: _first(
        record.get("projects_listed"),
        _structured(record).get("projects_listed"),
        record.get("projects"),
        _structured(record).get("projects"),
    ),
    "publications_listed": lambda record: _first(
        record.get("publications_listed"),
        _structured(record).get("publications_listed"),
        record.get("publications"),
        _structured(record).get("publications"),
    ),
    "patents_listed": lambda record: _first(
        record.get("patents_listed"),
        _structured(record).get("patents_listed"),
        record.get("patents"),
        _structured(record).get("patents"),
    ),
    "honors_and_awards": lambda record: _first(
        record.get("honors_and_awards"),
        _structured(record).get("honors_and_awards"),
        record.get("awards"),
        _structured(record).get("awards"),
    ),
    "recommendations_count": lambda record: _to_int(_first(
        record.get("recommendations_count"),
        _structured(record).get("recommendations_count"),
    )),
    "posts_count": lambda record: _to_int(_first(
        record.get("posts_count"),
        _structured(record).get("posts_count"),
    )),
    # Additional Wikipedia fields (categories already defined above via _amazon_categories)
    "links_count": lambda record: _to_int(_first(
        record.get("links_count"),
        _structured(record).get("links_count"),
    )),
    "image_count": lambda record: _to_int(_first(
        record.get("image_count"),
        _structured(record).get("image_count"),
        record.get("images_count"),
        _structured(record).get("images_count"),
    )),
    "first_paragraph": lambda record: _first(
        record.get("first_paragraph"),
        _structured(record).get("first_paragraph"),
        record.get("summary"),
        _structured(record).get("summary"),
    ),
    # Additional arXiv fields
    "journal_ref": lambda record: _first(
        record.get("journal_ref"),
        _structured(record).get("journal_ref"),
    ),
    "license_url": lambda record: _first(
        record.get("license_url"),
        _structured(record).get("license_url"),
        record.get("license"),
        _structured(record).get("license"),
    ),
    # More Wikipedia fields
    "summary": lambda record: _first(
        record.get("summary"),
        _structured(record).get("summary"),
        record.get("article_summary"),
        _structured(record).get("article_summary"),
    ),
    "number_of_sections": lambda record: _to_int(_first(
        record.get("number_of_sections"),
        _structured(record).get("number_of_sections"),
        record.get("section_count"),
        _structured(record).get("section_count"),
    )),
    "protection_level": lambda record: _first(
        record.get("protection_level"),
        _structured(record).get("protection_level"),
    ),
    # images already defined above — removed duplicate
    "infobox_raw": lambda record: _first(
        record.get("infobox_raw"),
        _structured(record).get("infobox_raw"),
    ),
    "references": lambda record: _first(
        record.get("references"),
        _structured(record).get("references"),
    ),
    "article_creation_date": lambda record: _first(
        record.get("article_creation_date"),
        _structured(record).get("article_creation_date"),
    ),
    "see_also": lambda record: _first(
        record.get("see_also"),
        _structured(record).get("see_also"),
    ),
}


FIELD_NORMALIZERS: dict[str, Callable[[Any], Any]] = {
    "specialties": _join_strings,
    "categories": _normalize_string_list,
    "breadcrumbs": _normalize_string_list,
    "page_id": _to_int,
    "entity_type": _normalize_wikipedia_entity_type,
    "authors": _normalize_arxiv_authors,
    "versions": _normalize_arxiv_versions,
    "rating": _normalize_rating_value,
    "stars": _normalize_rating_value,
    "reviews_count": _normalize_count_value,
    "helpful_count": _normalize_count_value,
    "date_posted": _normalize_date_value,
    "verified_purchase": _normalize_bool,
}


def _wikipedia_dedup_key(record: Record) -> str | None:
    wikidata_id = _first(record.get("wikidata_id"), _structured(record).get("wikidata_id"))
    if wikidata_id not in (None, ""):
        return wikidata_id
    page_id = _first(record.get("page_id"), _structured(record).get("page_id"), _metadata(record).get("page_id"))
    language = _wikipedia_language(record)
    if page_id in (None, "") or language in (None, ""):
        return None
    return f"{page_id}:{language}"
