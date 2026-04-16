from __future__ import annotations

from .base import (
    PlatformAdapter,
    PlatformDiscoveryPlan,
    PlatformEnrichmentPlan,
    PlatformErrorPlan,
    PlatformExtractPlan,
    PlatformFetchPlan,
    PlatformNormalizePlan,
    default_backend_resolver,
    default_fetch_executor,
    hook_normalizer,
    route_enrichment_groups,
    strategy_extractor,
)

FETCH_PLAN = PlatformFetchPlan(default_backend="http", fallback_backends=("playwright", "camoufox"))
EXTRACT_PLAN = PlatformExtractPlan(strategy="article_html")
NORMALIZE_PLAN = PlatformNormalizePlan(hook_name="generic_page")
ENRICH_PLAN = PlatformEnrichmentPlan(route="generic_document", field_groups=("summaries",))


ADAPTER = PlatformAdapter(
    platform="generic",
    discovery=PlatformDiscoveryPlan(resource_types=("page",), canonicalizer="generic"),
    fetch=FETCH_PLAN,
    extract=EXTRACT_PLAN,
    normalize=NORMALIZE_PLAN,
    enrich=ENRICH_PLAN,
    error=PlatformErrorPlan(normalized_code="GENERIC_FETCH_FAILED"),
    resolve_backend_fn=default_backend_resolver(FETCH_PLAN),
    fetch_fn=default_fetch_executor(),
    extract_fn=strategy_extractor(EXTRACT_PLAN.strategy),
    normalize_fn=hook_normalizer(NORMALIZE_PLAN.hook_name),
    enrichment_fn=route_enrichment_groups(ENRICH_PLAN),
)
