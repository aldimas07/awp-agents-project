from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping
from urllib.parse import parse_qs, urlparse

from crawler.contracts import NormalizedError
from crawler.extract.html_extract import extract_html_document
from crawler.fetch.unified import unified_fetch


@dataclass(frozen=True, slots=True)
class PlatformDiscoveryPlan:
    resource_types: tuple[str, ...]
    canonicalizer: str = "default"


@dataclass(frozen=True, slots=True)
class PlatformFetchPlan:
    default_backend: str
    fallback_backends: tuple[str, ...] = ()
    requires_auth: bool = False


@dataclass(frozen=True, slots=True)
class PlatformExtractPlan:
    strategy: str


@dataclass(frozen=True, slots=True)
class PlatformNormalizePlan:
    hook_name: str


@dataclass(frozen=True, slots=True)
class PlatformEnrichmentPlan:
    route: str
    field_groups: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class PlatformErrorPlan:
    normalized_code: str
    retryable: bool = False


@dataclass(frozen=True, slots=True)
class PlatformAdapter:
    platform: str
    discovery: PlatformDiscoveryPlan
    fetch: PlatformFetchPlan
    extract: PlatformExtractPlan
    normalize: PlatformNormalizePlan
    enrich: PlatformEnrichmentPlan
    error: PlatformErrorPlan
    resolve_backend_fn: Callable[[dict[str, Any], str | None, int], str]
    fetch_fn: Callable[[dict[str, Any], dict[str, Any], str, str | None], dict[str, Any]]
    extract_fn: Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]]
    normalize_fn: Callable[[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]], dict[str, Any]]
    enrichment_fn: Callable[[dict[str, Any], tuple[str, ...]], dict[str, Any]]

    @property
    def supported_resource_types(self) -> tuple[str, ...]:
        return self.discovery.resource_types

    @property
    def requires_auth(self) -> bool:
        return self.fetch.requires_auth

    @property
    def default_backend(self) -> str:
        return self.fetch.default_backend

    @property
    def fallback_backends(self) -> tuple[str, ...]:
        return self.fetch.fallback_backends

    def resolve_backend(self, record: dict[str, Any], override_backend: str | None = None, retry_count: int = 0) -> str:
        return self.resolve_backend_fn(record, override_backend, retry_count)

    def extract_content(self, record: dict[str, Any], fetched: dict[str, Any]) -> dict[str, Any]:
        return self.extract_fn(record, fetched)

    def fetch_record(
        self,
        record: dict[str, Any],
        discovered: dict[str, Any],
        backend: str,
        storage_state_path: str | None = None,
    ) -> dict[str, Any]:
        return self.fetch_fn(record, discovered, backend, storage_state_path)

    def normalize_record(
        self,
        record: dict[str, Any],
        discovered: dict[str, Any],
        extracted: dict[str, Any],
        supplemental: dict[str, Any],
    ) -> dict[str, Any]:
        return self.normalize_fn(record, discovered, extracted, supplemental)

    def build_enrichment_request(self, record: dict[str, Any], requested_groups: tuple[str, ...] = ()) -> dict[str, Any]:
        return self.enrichment_fn(record, requested_groups)

    def normalize_error(
        self,
        *,
        resource_type: str | None,
        operation: str,
        exception: Exception,
    ) -> NormalizedError:
        return NormalizedError.from_exception(
            platform=self.platform,
            resource_type=resource_type,
            operation=operation,
            error_code=self.error.normalized_code,
            exception=exception,
            retryable=self.error.retryable,
        )


def default_backend_resolver(fetch: PlatformFetchPlan) -> Callable[[dict[str, Any], str | None, int], str]:
    def resolver(record: dict[str, Any], override_backend: str | None = None, retry_count: int = 0) -> str:
        if override_backend:
            return override_backend
        # Fallback applies to ALL platforms with declared fallback_backends, not just auth-required ones
        if fetch.fallback_backends and retry_count > 0:
            return fetch.fallback_backends[min(retry_count - 1, len(fetch.fallback_backends) - 1)]
        return fetch.default_backend

    return resolver


def default_fetch_executor(
    api_fetcher: Callable[[dict[str, Any], dict[str, Any], str | None], dict[str, Any]] | None = None,
) -> Callable[[dict[str, Any], dict[str, Any], str, str | None], dict[str, Any]]:
    """
    Creates a fetch executor that routes to the unified fetch interface.

    For "api" backend, uses the provided api_fetcher callable.
    For all other backends (http, playwright, camoufox), uses unified_fetch()
    which internally uses FetchEngine with BrowserPool, WaitStrategy, etc.
    """
    def fetcher(
        record: dict[str, Any],
        discovered: dict[str, Any],
        backend: str,
        storage_state_path: str | None = None,
    ) -> dict[str, Any]:
        if backend == "api":
            if api_fetcher is None:
                raise ValueError(f"platform {record['platform']} does not support api backend")
            return api_fetcher(record, discovered, storage_state_path)

        # Use unified fetch (internally uses FetchEngine)
        return unified_fetch(
            url=discovered["canonical_url"],
            platform=record["platform"],
            resource_type=record.get("resource_type"),
            backend=backend,
            storage_state_path=storage_state_path,
        )

    return fetcher


def strategy_extractor(strategy: str) -> Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]]:
    def extractor(record: dict[str, Any], fetched: dict[str, Any]) -> dict[str, Any]:
        content_type = fetched.get("content_type")
        html = fetched.get("text") or fetched.get("html") or fetched.get("content_bytes", b"").decode("utf-8", "ignore")
        return extract_html_document(
            html,
            fetched["url"],
            content_type=content_type,
            platform=record["platform"],
            resource_type=record.get("resource_type", ""),
        )

    return extractor


def hook_normalizer(hook_name: str) -> Callable[[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]], dict[str, Any]]:
    def normalizer(
        record: dict[str, Any],
        discovered: dict[str, Any],
        extracted: dict[str, Any],
        supplemental: dict[str, Any],
    ) -> dict[str, Any]:
        metadata = extracted.get("metadata", {})
        canonical_url = discovered.get("canonical_url") or record.get("canonical_url") or record.get("url")

        def _first(*values: Any) -> Any:
            for value in values:
                if value not in (None, "", [], {}):
                    return value
            return None

        if hook_name == "wikipedia":
            from crawler.platforms.wikipedia import _parse_infobox_structured

            language = None
            if isinstance(canonical_url, str):
                hostname = urlparse(canonical_url).hostname or ""
                parts = hostname.split(".")
                language = parts[0] if len(parts) >= 3 else "en"  # default to "en" for bare wikipedia.org
            structured = extracted.get("structured", {})
            page_id = metadata.get("page_id") or structured.get("page_id")
            result = {
                "title": metadata.get("title") or record.get("title"),
                "summary": extracted.get("plain_text", "").splitlines()[0] if extracted.get("plain_text") else "",
                "URL": canonical_url,
                "canonical_url": canonical_url,
                "raw_text": extracted.get("plain_text"),
                "HTML": extracted.get("markdown"),
            }
            if page_id not in (None, ""):
                result["page_id"] = str(page_id)
            if language not in (None, ""):
                result["language"] = language
            if page_id not in (None, "") and language not in (None, ""):
                result["dedup_key"] = f"{page_id}:{language}"
            for field_name in (
                "categories",
                "article_creation_date",
                "protection_level",
                "references",
                "references_count",
                "external_links_count",
                "see_also",
                "images",
                "word_count",
                "number_of_sections",
                "has_infobox",
                "infobox_raw",
                "title_disambiguated",
                "canonical_entity_name",
                "wikidata_id",
                "article_summary",
                "sections_structured",
                "table_of_contents",
                "tables_structured",
                "categories_cleaned",
                "citation_density",
                "last_major_edit",
                "article_quality_class",
                "domain",
                "topic_hierarchy",
                "subject_tags",
                "external_links_classified",
                "cross_language_links",
                "entity_name_translations",
            ):
                value = structured.get(field_name)
                if value not in (None, "", [], {}):
                    result[field_name] = value
            infobox_structured = structured.get("infobox_structured")
            if infobox_structured in (None, "", [], {}):
                infobox_structured = _parse_infobox_structured(str(result.get("infobox_raw") or structured.get("infobox_raw") or ""))
            if infobox_structured not in (None, "", [], {}):
                result["infobox_structured"] = infobox_structured
            return result
        if hook_name == "arxiv":
            structured = extracted.get("structured", {})
            abstract = metadata.get("description") or structured.get("abstract_plain_text") or ""
            if not abstract and extracted.get("plain_text"):
                abstract = extracted.get("plain_text", "").splitlines()[0]
            arxiv_id = discovered["fields"].get("arxiv_id")
            result = {
                "arxiv_id": arxiv_id,
                "abstract": abstract,
                "pdf_document_blocks": supplemental.get("document_blocks", []),
                "title": metadata.get("title") or record.get("title"),
                "authors": metadata.get("authors") or structured.get("authors"),
                "categories": structured.get("categories"),
                "URL": canonical_url,
                "canonical_url": canonical_url,
                "dedup_key": arxiv_id,
                "page_count": structured.get("page_count"),
                "raw_text": extracted.get("plain_text"),
            }
            for target, candidates in (
                ("DOI", ("DOI", "doi")),
                ("primary_category", ("primary_category",)),
                ("submission_date", ("submission_date", "published")),
                ("update_date", ("update_date", "updated")),
                ("versions", ("versions",)),
                ("submission_comments", ("submission_comments", "comment")),
                ("journal_ref", ("journal_ref",)),
                ("license", ("license",)),
                ("PDF_url", ("PDF_url", "pdf_url")),
                ("references", ("references",)),
                ("num_figures", ("num_figures",)),
            ):
                value = _first(*(structured.get(candidate) for candidate in candidates))
                if value not in (None, "", [], {}):
                    result[target] = value
            authors = result.get("authors")
            if isinstance(authors, list):
                result["num_authors"] = len(authors)
            return result
        if hook_name == "amazon":
            from crawler.normalize import normalize_amazon_record

            extracted_structured = extracted.get("structured", {})
            result = {
                key: value
                for key, value in discovered["fields"].items()
                if value not in (None, "", [], {})
            }
            result["title"] = metadata.get("title") or (
                extracted_structured.get("title") if isinstance(extracted_structured, dict) else None
            )
            if isinstance(extracted_structured, dict):
                result.update({
                    key: value
                    for key, value in extracted_structured.items()
                    if key != "title" and value not in (None, "", [], {})
                })
            result["URL"] = canonical_url
            result["canonical_url"] = canonical_url
            marketplace = _first(record.get("marketplace"), result.get("marketplace"), "com")
            if marketplace not in (None, ""):
                result["marketplace"] = marketplace
            resource_type = str(record.get("resource_type") or result.get("resource_type") or "").strip().lower()
            seller_id = _first(result.get("seller_id"), record.get("seller_id"))
            review_id = _first(result.get("review_id"), record.get("review_id"))
            asin = _first(result.get("asin"), record.get("asin"))
            if resource_type == "seller" and seller_id not in (None, "") and marketplace not in (None, ""):
                result["dedup_key"] = f"{seller_id}:{marketplace}"
            elif resource_type == "review" and review_id not in (None, "") and marketplace not in (None, ""):
                result["dedup_key"] = f"{review_id}:{marketplace}"
            elif asin not in (None, "") and marketplace not in (None, ""):
                result["dedup_key"] = f"{asin}:{marketplace}"
            if "category" not in result and result.get("categories") not in (None, "", [], {}):
                result["category"] = result["categories"]
            if "categories" not in result and result.get("category") not in (None, "", [], {}):
                result["categories"] = result["category"]
            if "breadcrumbs" not in result and result.get("categories") not in (None, "", [], {}):
                result["breadcrumbs"] = result["categories"]
            result["resource_type"] = resource_type or record.get("resource_type")
            return normalize_amazon_record(result)
        if hook_name == "base_chain":
            return {
                "identifier": next(iter(discovered["fields"].values()), None),
                "title": metadata.get("title"),
            }
        if hook_name == "linkedin":
            from crawler.platforms.linkedin import _normalize_linkedin_record

            return _normalize_linkedin_record(record, discovered, extracted, supplemental)
        if hook_name == "generic_page":
            result: dict[str, Any] = {}
            title = metadata.get("title")
            description = metadata.get("description")
            source_url = metadata.get("source_url")
            if title:
                result["title"] = title
            if description:
                result["description"] = description
            if source_url:
                result["source_url"] = source_url
            if canonical_url:
                result["URL"] = canonical_url
                result["canonical_url"] = canonical_url
            return result
        return {}

    return normalizer


def route_enrichment_groups(
    plan: PlatformEnrichmentPlan,
) -> Callable[[dict[str, Any], tuple[str, ...]], dict[str, Any]]:
    def builder(record: dict[str, Any], requested_groups: tuple[str, ...] = ()) -> dict[str, Any]:
        field_groups = requested_groups or plan.field_groups
        return {
            "route": plan.route,
            "field_groups": tuple(field_groups),
        }

    return builder
