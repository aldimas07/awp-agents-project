from __future__ import annotations

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
    strategy_extractor,
)

PRODUCT_FIELD_GROUPS = (
    "amazon_products_identity",
    "amazon_products_pricing",
    "amazon_products_description",
    "amazon_products_category",
    "amazon_products_visual",
    "amazon_products_availability",
    "amazon_products_competition",
    "amazon_products_reviews_summary",
    "amazon_products_variants",
    "amazon_products_compliance",
    "amazon_products_multimodal_images",
    "amazon_products_multi_level_summary",
    "amazon_products_market_positioning",
    "amazon_products_listing_quality",
    "amazon_products_linkable_ids",
)

REVIEW_FIELD_GROUPS = (
    "amazon_reviews_identity",
    "amazon_reviews_content",
    "amazon_reviews_analysis",
    "amazon_reviews_quality",
    "amazon_reviews_structured",
    "amazon_reviews_media",
    "amazon_reviews_multimodal_images",
    "amazon_reviews_multi_level_summary",
    "amazon_reviews_review_depth",
)

SELLER_FIELD_GROUPS = (
    "amazon_sellers_identity",
    "amazon_sellers_performance",
    "amazon_sellers_portfolio",
    "amazon_sellers_business_intel",
    "amazon_sellers_multi_level_summary",
    "amazon_sellers_linkable_ids",
)

FETCH_PLAN = PlatformFetchPlan(default_backend="http", fallback_backends=("playwright", "camoufox"))
EXTRACT_PLAN = PlatformExtractPlan(strategy="commerce_page")
NORMALIZE_PLAN = PlatformNormalizePlan(hook_name="amazon")
ENRICH_PLAN = PlatformEnrichmentPlan(
    route="commerce_graph",
    field_groups=PRODUCT_FIELD_GROUPS,
)


def _build_amazon_enrichment_request(record: dict[str, object], requested_groups: tuple[str, ...] = ()) -> dict[str, object]:
    if requested_groups:
        field_groups = requested_groups
    else:
        resource_type = str(record.get("resource_type") or "")
        if resource_type == "product":
            field_groups = PRODUCT_FIELD_GROUPS
        elif resource_type == "seller":
            field_groups = SELLER_FIELD_GROUPS
        elif resource_type == "review":
            field_groups = REVIEW_FIELD_GROUPS
        else:
            field_groups = ()
    return {
        "route": ENRICH_PLAN.route,
        "field_groups": tuple(field_groups),
    }


ADAPTER = PlatformAdapter(
    platform="amazon",
    discovery=PlatformDiscoveryPlan(
        resource_types=("product", "seller", "review", "search"),
        canonicalizer="amazon",
    ),
    fetch=FETCH_PLAN,
    extract=EXTRACT_PLAN,
    normalize=NORMALIZE_PLAN,
    enrich=ENRICH_PLAN,
    error=PlatformErrorPlan(normalized_code="AMAZON_FETCH_FAILED"),
    resolve_backend_fn=default_backend_resolver(FETCH_PLAN),
    fetch_fn=default_fetch_executor(),
    extract_fn=strategy_extractor(EXTRACT_PLAN.strategy),
    normalize_fn=hook_normalizer(NORMALIZE_PLAN.hook_name),
    enrichment_fn=_build_amazon_enrichment_request,
)
