"""Amazon platform FieldGroupSpec definitions.

Covers all three subdatasets: products, reviews, sellers.
Generated from references/enrichment_catalog/amazon.json.
"""

from __future__ import annotations

from crawler.enrich.schemas.field_group_registry import (
    FieldGroupSpec,
    GenerativeConfig,
    OutputFieldSpec,
)

# ---------------------------------------------------------------------------
# 4.1 Amazon Products Dataset  (15 field groups)
# ---------------------------------------------------------------------------

_products_identity = FieldGroupSpec(
    name="amazon_products_identity",
    description="Product identity and brand standardization",
    required_source_fields=["title", "brand"],
    output_fields=[
        OutputFieldSpec(name="title_cleaned", field_type="string"),
        OutputFieldSpec(name="brand_standardized", field_type="string"),
        OutputFieldSpec(name="is_brand_official_store", field_type="boolean"),
    ],
    strategy="generative_only",
    generative_config=GenerativeConfig(prompt_template="amazon_products_identity.jinja2"),
    platform="amazon",
    subdataset="products",
)

_products_pricing = FieldGroupSpec(
    name="amazon_products_pricing",
    description="Price analysis, tier classification, and deal quality scoring",
    required_source_fields=["price", "categories"],
    output_fields=[
        OutputFieldSpec(name="price_tier", field_type="string"),
        OutputFieldSpec(name="price_vs_category_avg", field_type="number"),
        OutputFieldSpec(name="historical_price_trend", field_type="string"),
        OutputFieldSpec(name="deal_quality_score", field_type="number"),
        OutputFieldSpec(name="price_signals_on_page", field_type="array<string>"),
    ],
    strategy="generative_only",
    generative_config=GenerativeConfig(prompt_template="amazon_products_pricing.jinja2"),
    platform="amazon",
    subdataset="products",
)

_products_description = FieldGroupSpec(
    name="amazon_products_description",
    description="Structured feature extraction, spec table, use cases, and target audience inference",
    required_source_fields=["description", "bullet_points"],
    output_fields=[
        OutputFieldSpec(name="features_structured", field_type="array<object>"),
        OutputFieldSpec(name="key_specs_table", field_type="string"),
        OutputFieldSpec(name="use_cases_extracted", field_type="array<string>"),
        OutputFieldSpec(name="target_audience_inferred", field_type="array<string>"),
    ],
    strategy="generative_only",
    generative_config=GenerativeConfig(prompt_template="amazon_products_description.jinja2", max_tokens=1024),
    platform="amazon",
    subdataset="products",
)

_products_category = FieldGroupSpec(
    name="amazon_products_category",
    description="Category standardization, niche tagging, and seasonal relevance",
    required_source_fields=["categories", "title"],
    output_fields=[
        OutputFieldSpec(name="category_standardized", field_type="string"),
        OutputFieldSpec(name="niche_tags", field_type="array<string>"),
        OutputFieldSpec(name="seasonal_relevance", field_type="string"),
    ],
    strategy="generative_only",
    generative_config=GenerativeConfig(prompt_template="amazon_products_category.jinja2"),
    platform="amazon",
    subdataset="products",
)

_products_visual = FieldGroupSpec(
    name="amazon_products_visual",
    description="Image and video asset inventory with visual quality scoring",
    required_source_fields=["images"],
    output_fields=[
        OutputFieldSpec(name="image_count", field_type="integer"),
        OutputFieldSpec(name="has_lifestyle_images", field_type="boolean"),
        OutputFieldSpec(name="has_infographic", field_type="boolean"),
        OutputFieldSpec(name="has_video", field_type="boolean"),
        OutputFieldSpec(name="visual_quality_score", field_type="number"),
    ],
    strategy="generative_only",
    generative_config=GenerativeConfig(prompt_template="amazon_products_visual.jinja2"),
    platform="amazon",
    subdataset="products",
)

_products_availability = FieldGroupSpec(
    name="amazon_products_availability",
    description="Fulfillment type, shipping speed, Prime eligibility, and estimated sales",
    required_source_fields=["fulfillment", "availability"],
    output_fields=[
        OutputFieldSpec(name="fulfillment_type", field_type="string"),
        OutputFieldSpec(name="shipping_speed_tier", field_type="string"),
        OutputFieldSpec(name="prime_eligible", field_type="boolean"),
        OutputFieldSpec(name="estimated_monthly_sales", field_type="integer"),
    ],
    strategy="generative_only",
    generative_config=GenerativeConfig(prompt_template="amazon_products_availability.jinja2"),
    platform="amazon",
    subdataset="products",
)

_products_competition = FieldGroupSpec(
    name="amazon_products_competition",
    description="Competitive positioning, listing quality, and SEO keyword density",
    required_source_fields=["title", "categories", "price", "rating"],
    output_fields=[
        OutputFieldSpec(name="competitive_position", field_type="object"),
        OutputFieldSpec(name="listing_quality_score", field_type="number"),
        OutputFieldSpec(name="seo_keyword_density", field_type="number"),
    ],
    strategy="generative_only",
    generative_config=GenerativeConfig(prompt_template="amazon_products_competition.jinja2"),
    platform="amazon",
    subdataset="products",
)

_products_reviews_summary = FieldGroupSpec(
    name="amazon_products_reviews_summary",
    description="Aggregate review analysis: rating trend, velocity, fake review risk, verified ratio",
    required_source_fields=["rating", "reviews_count"],
    output_fields=[
        OutputFieldSpec(name="recent_rating_signal", field_type="string"),
        OutputFieldSpec(name="rating_trend", field_type="string"),
        OutputFieldSpec(name="review_velocity", field_type="string"),
        OutputFieldSpec(name="review_pattern_risk_indicators", field_type="string"),
        OutputFieldSpec(name="fake_review_risk_score", field_type="number"),
        OutputFieldSpec(name="verified_purchase_ratio", field_type="number"),
    ],
    strategy="generative_only",
    generative_config=GenerativeConfig(prompt_template="amazon_products_reviews_summary.jinja2"),
    platform="amazon",
    subdataset="products",
)

_products_variants = FieldGroupSpec(
    name="amazon_products_variants",
    description="Variant matrix structure, best-seller variant, and variant price range",
    required_source_fields=["variants"],
    output_fields=[
        OutputFieldSpec(name="variant_matrix_structured", field_type="object"),
        OutputFieldSpec(name="best_seller_variant", field_type="string"),
        OutputFieldSpec(name="variant_price_range", field_type="string"),
    ],
    strategy="generative_only",
    generative_config=GenerativeConfig(prompt_template="amazon_products_variants.jinja2"),
    platform="amazon",
    subdataset="products",
)

_products_compliance = FieldGroupSpec(
    name="amazon_products_compliance",
    description="Certifications, origin, material composition, and safety warnings extraction",
    required_source_fields=["description", "bullet_points"],
    output_fields=[
        OutputFieldSpec(name="certifications_mentioned", field_type="array<string>"),
        OutputFieldSpec(name="country_of_origin", field_type="string"),
        OutputFieldSpec(name="material_composition_extracted", field_type="string"),
        OutputFieldSpec(name="safety_warnings", field_type="array<string>"),
    ],
    strategy="generative_only",
    generative_config=GenerativeConfig(prompt_template="amazon_products_compliance.jinja2"),
    platform="amazon",
    subdataset="products",
)

_products_multimodal_images = FieldGroupSpec(
    name="amazon_products_multimodal_images",
    description="Vision-based product image analysis: background, angles, text extraction, completeness",
    required_source_fields=["images"],
    output_fields=[
        OutputFieldSpec(name="main_image_analysis", field_type="object"),
        OutputFieldSpec(name="all_images_analysis", field_type="array<object>"),
        OutputFieldSpec(name="image_text_consistency_score", field_type="number"),
        OutputFieldSpec(name="listing_visual_completeness", field_type="object"),
    ],
    strategy="generative_only",
    generative_config=GenerativeConfig(prompt_template="amazon_products_multimodal_images.jinja2", max_tokens=1024),
    requires_vision=True,
    platform="amazon",
    subdataset="products",
)

_products_multi_level_summary = FieldGroupSpec(
    name="amazon_products_multi_level_summary",
    description="Multi-audience summaries: buyer quick take, elevator pitch, seller brief, SEO description",
    required_source_fields=["title", "description", "bullet_points", "rating"],
    output_fields=[
        OutputFieldSpec(name="buyer_quick_take", field_type="string"),
        OutputFieldSpec(name="product_elevator_pitch", field_type="string"),
        OutputFieldSpec(name="seller_competitive_brief", field_type="string"),
        OutputFieldSpec(name="seo_optimized_description", field_type="string"),
    ],
    strategy="generative_only",
    generative_config=GenerativeConfig(prompt_template="amazon_products_multi_level_summary.jinja2", max_tokens=1024),
    platform="amazon",
    subdataset="products",
)

_products_market_positioning = FieldGroupSpec(
    name="amazon_products_market_positioning",
    description="Lifecycle stage inference, USPs, purchase decision factors, and cross-sell hints",
    required_source_fields=["title", "description", "categories", "rating", "reviews_count"],
    output_fields=[
        OutputFieldSpec(name="product_lifecycle_stage_inferred", field_type="string"),
        OutputFieldSpec(name="lifecycle_evidence", field_type="string"),
        OutputFieldSpec(name="unique_selling_points", field_type="array<string>"),
        OutputFieldSpec(name="purchase_decision_factors_from_listing", field_type="array<object>"),
        OutputFieldSpec(name="cross_sell_category_hints", field_type="array<string>"),
    ],
    strategy="generative_only",
    generative_config=GenerativeConfig(prompt_template="amazon_products_market_positioning.jinja2", max_tokens=1024),
    platform="amazon",
    subdataset="products",
)

_products_listing_quality = FieldGroupSpec(
    name="amazon_products_listing_quality",
    description="Listing optimization scoring, issue detection, and completeness audit",
    required_source_fields=["title", "bullet_points", "description", "images"],
    output_fields=[
        OutputFieldSpec(name="listing_optimization_score", field_type="number"),
        OutputFieldSpec(name="listing_issues_detected", field_type="array<object>"),
        OutputFieldSpec(name="listing_completeness", field_type="object"),
        OutputFieldSpec(name="title_description_coherence_score", field_type="number"),
        OutputFieldSpec(name="spec_description_mismatch", field_type="array<object>"),
        OutputFieldSpec(name="misleading_claim_flags", field_type="array<object>"),
        OutputFieldSpec(name="gift_potential_score", field_type="number"),
        OutputFieldSpec(name="customer_faq_generated", field_type="array<object>"),
        OutputFieldSpec(name="product_comparison_dimensions", field_type="array<object>"),
        OutputFieldSpec(name="buyer_persona_from_qa", field_type="object"),
        OutputFieldSpec(name="return_risk_indicators", field_type="object"),
    ],
    strategy="generative_only",
    generative_config=GenerativeConfig(prompt_template="amazon_products_listing_quality.jinja2", max_tokens=1024),
    platform="amazon",
    subdataset="products",
)

_products_linkable_ids = FieldGroupSpec(
    name="amazon_products_linkable_ids",
    description="Cross-dataset linkable identifiers: brand URLs, patents, UPC/EAN/ISBN, model numbers",
    required_source_fields=["title", "brand", "description"],
    output_fields=[
        OutputFieldSpec(name="linkable_identifiers", field_type="object"),
    ],
    strategy="generative_only",
    generative_config=GenerativeConfig(prompt_template="amazon_products_linkable_ids.jinja2"),
    platform="amazon",
    subdataset="products",
)

# ---------------------------------------------------------------------------
# 4.2 Amazon Reviews Dataset  (9 field groups)
# ---------------------------------------------------------------------------

_reviews_identity = FieldGroupSpec(
    name="amazon_reviews_identity",
    description="Reviewer profile type classification",
    required_source_fields=["author_name", "review_text"],
    output_fields=[
        OutputFieldSpec(name="reviewer_profile_type", field_type="string"),
    ],
    strategy="generative_only",
    generative_config=GenerativeConfig(prompt_template="amazon_reviews_identity.jinja2"),
    platform="amazon",
    subdataset="reviews",
)

_reviews_content = FieldGroupSpec(
    name="amazon_reviews_content",
    description="Overall and aspect-level sentiment analysis of review text",
    required_source_fields=["review_text", "rating"],
    output_fields=[
        OutputFieldSpec(name="sentiment_overall", field_type="string"),
        OutputFieldSpec(name="sentiment_aspects", field_type="array<object>"),
    ],
    strategy="generative_only",
    generative_config=GenerativeConfig(prompt_template="amazon_reviews_content.jinja2"),
    platform="amazon",
    subdataset="reviews",
)

_reviews_analysis = FieldGroupSpec(
    name="amazon_reviews_analysis",
    description="Pros/cons extraction, feature satisfaction mapping, use cases, and alternative comparisons",
    required_source_fields=["review_text", "rating"],
    output_fields=[
        OutputFieldSpec(name="product_pros_extracted", field_type="array<string>"),
        OutputFieldSpec(name="product_cons_extracted", field_type="array<string>"),
        OutputFieldSpec(name="feature_satisfaction_map", field_type="object"),
        OutputFieldSpec(name="use_case_mentioned", field_type="string"),
        OutputFieldSpec(name="comparison_to_alternatives", field_type="array<object>"),
    ],
    strategy="generative_only",
    generative_config=GenerativeConfig(prompt_template="amazon_reviews_analysis.jinja2", max_tokens=1024),
    platform="amazon",
    subdataset="reviews",
)

_reviews_quality = FieldGroupSpec(
    name="amazon_reviews_quality",
    description="Review quality scoring, type classification, authenticity, and information density",
    required_source_fields=["review_text", "rating", "verified_purchase"],
    output_fields=[
        OutputFieldSpec(name="review_quality_score", field_type="number"),
        OutputFieldSpec(name="review_type", field_type="string"),
        OutputFieldSpec(name="authenticity_score", field_type="number"),
        OutputFieldSpec(name="information_density", field_type="number"),
        OutputFieldSpec(name="review_text_rating_mismatch", field_type="object"),
        OutputFieldSpec(name="sponsored_review_indicators", field_type="object"),
    ],
    strategy="generative_only",
    generative_config=GenerativeConfig(prompt_template="amazon_reviews_quality.jinja2"),
    platform="amazon",
    subdataset="reviews",
)

_reviews_structured = FieldGroupSpec(
    name="amazon_reviews_structured",
    description="Structured issue extraction, customer segment inference, and purchase context",
    required_source_fields=["review_text"],
    output_fields=[
        OutputFieldSpec(name="issues_reported", field_type="array<object>"),
        OutputFieldSpec(name="customer_segment_inferred", field_type="string"),
        OutputFieldSpec(name="purchase_context", field_type="string"),
        OutputFieldSpec(name="seller_response_quality", field_type="string"),
        OutputFieldSpec(name="issue_resolution_status", field_type="string"),
        OutputFieldSpec(name="temporal_context_of_opinion", field_type="object"),
        OutputFieldSpec(name="problem_root_cause_inferred", field_type="object"),
    ],
    strategy="generative_only",
    generative_config=GenerativeConfig(prompt_template="amazon_reviews_structured.jinja2"),
    platform="amazon",
    subdataset="reviews",
)

_reviews_media = FieldGroupSpec(
    name="amazon_reviews_media",
    description="Review media analysis: image content description, product-in-use detection, defect detection",
    required_source_fields=["review_images"],
    output_fields=[
        OutputFieldSpec(name="image_content_described", field_type="array<string>"),
        OutputFieldSpec(name="shows_product_in_use", field_type="boolean"),
        OutputFieldSpec(name="shows_defect", field_type="boolean"),
    ],
    strategy="generative_only",
    generative_config=GenerativeConfig(prompt_template="amazon_reviews_media.jinja2"),
    platform="amazon",
    subdataset="reviews",
)

_reviews_multimodal_images = FieldGroupSpec(
    name="amazon_reviews_multimodal_images",
    description="Vision-based review image analysis: defect detection, usage context, text-image consistency",
    required_source_fields=["review_images"],
    output_fields=[
        OutputFieldSpec(name="review_image_analysis", field_type="array<object>"),
    ],
    strategy="generative_only",
    generative_config=GenerativeConfig(prompt_template="amazon_reviews_multimodal_images.jinja2", max_tokens=1024),
    requires_vision=True,
    platform="amazon",
    subdataset="reviews",
)

_reviews_multi_level_summary = FieldGroupSpec(
    name="amazon_reviews_multi_level_summary",
    description="Review one-liner and purchase decision factor extraction",
    required_source_fields=["review_text", "rating"],
    output_fields=[
        OutputFieldSpec(name="review_one_liner", field_type="string"),
        OutputFieldSpec(name="purchase_decision_factor", field_type="string"),
    ],
    strategy="generative_only",
    generative_config=GenerativeConfig(prompt_template="amazon_reviews_multi_level_summary.jinja2"),
    platform="amazon",
    subdataset="reviews",
)

_reviews_depth = FieldGroupSpec(
    name="amazon_reviews_review_depth",
    description="Review depth analysis: usage duration, expertise level, actionable feedback, competitor mentions",
    required_source_fields=["review_text"],
    output_fields=[
        OutputFieldSpec(name="usage_duration_mentioned", field_type="string"),
        OutputFieldSpec(name="expertise_level_inferred", field_type="string"),
        OutputFieldSpec(name="actionable_feedback", field_type="array<string>"),
        OutputFieldSpec(name="competitor_products_mentioned", field_type="array<string>"),
    ],
    strategy="generative_only",
    generative_config=GenerativeConfig(prompt_template="amazon_reviews_review_depth.jinja2"),
    platform="amazon",
    subdataset="reviews",
)

# ---------------------------------------------------------------------------
# 4.3 Amazon Sellers Dataset  (6 field groups)
# ---------------------------------------------------------------------------

_sellers_identity = FieldGroupSpec(
    name="amazon_sellers_identity",
    description="Seller type classification and registered business name extraction",
    required_source_fields=["seller_name"],
    output_fields=[
        OutputFieldSpec(name="seller_type", field_type="string"),
        OutputFieldSpec(name="business_name_registered", field_type="string"),
    ],
    strategy="generative_only",
    generative_config=GenerativeConfig(prompt_template="amazon_sellers_identity.jinja2"),
    platform="amazon",
    subdataset="sellers",
)

_sellers_performance = FieldGroupSpec(
    name="amazon_sellers_performance",
    description="Seller health scoring, response time tier, and dispute rate estimation",
    required_source_fields=["seller_rating", "feedback_count"],
    output_fields=[
        OutputFieldSpec(name="seller_health_score", field_type="number"),
        OutputFieldSpec(name="response_time_tier", field_type="string"),
        OutputFieldSpec(name="dispute_rate_estimated", field_type="number"),
    ],
    strategy="generative_only",
    generative_config=GenerativeConfig(prompt_template="amazon_sellers_performance.jinja2"),
    platform="amazon",
    subdataset="sellers",
)

_sellers_portfolio = FieldGroupSpec(
    name="amazon_sellers_portfolio",
    description="Product count, category focus, brand portfolio, price range, and average rating",
    required_source_fields=["seller_name", "product_listings"],
    output_fields=[
        OutputFieldSpec(name="product_count", field_type="integer"),
        OutputFieldSpec(name="category_focus", field_type="array<string>"),
        OutputFieldSpec(name="brand_portfolio", field_type="array<string>"),
        OutputFieldSpec(name="brands_featured_on_storefront", field_type="array<string>"),
        OutputFieldSpec(name="price_range", field_type="string"),
        OutputFieldSpec(name="avg_product_rating", field_type="number"),
    ],
    strategy="generative_only",
    generative_config=GenerativeConfig(prompt_template="amazon_sellers_portfolio.jinja2"),
    platform="amazon",
    subdataset="sellers",
)

_sellers_business_intel = FieldGroupSpec(
    name="amazon_sellers_business_intel",
    description="Business intelligence: years on Amazon, growth trajectory, geographic focus, fulfillment strategy",
    required_source_fields=["seller_name", "seller_since"],
    output_fields=[
        OutputFieldSpec(name="years_on_amazon", field_type="integer"),
        OutputFieldSpec(name="growth_trajectory", field_type="string"),
        OutputFieldSpec(name="geographic_focus", field_type="string"),
        OutputFieldSpec(name="fulfillment_strategy", field_type="string"),
        OutputFieldSpec(name="seller_legitimacy_signals", field_type="object"),
        OutputFieldSpec(name="seller_origin_country_inferred", field_type="object"),
    ],
    strategy="generative_only",
    generative_config=GenerativeConfig(prompt_template="amazon_sellers_business_intel.jinja2"),
    platform="amazon",
    subdataset="sellers",
)

_sellers_multi_level_summary = FieldGroupSpec(
    name="amazon_sellers_multi_level_summary",
    description="Seller one-liner and profile narrative generation",
    required_source_fields=["seller_name", "seller_rating", "feedback_count"],
    output_fields=[
        OutputFieldSpec(name="seller_one_liner", field_type="string"),
        OutputFieldSpec(name="seller_profile_narrative", field_type="string"),
    ],
    strategy="generative_only",
    generative_config=GenerativeConfig(prompt_template="amazon_sellers_multi_level_summary.jinja2"),
    platform="amazon",
    subdataset="sellers",
)

_sellers_linkable_ids = FieldGroupSpec(
    name="amazon_sellers_linkable_ids",
    description="Cross-dataset linkable identifiers: seller website, LinkedIn hint, brand names",
    required_source_fields=["seller_name"],
    output_fields=[
        OutputFieldSpec(name="linkable_identifiers", field_type="object"),
    ],
    strategy="generative_only",
    generative_config=GenerativeConfig(prompt_template="amazon_sellers_linkable_ids.jinja2"),
    platform="amazon",
    subdataset="sellers",
)

# ---------------------------------------------------------------------------
# Public registry — all 30 Amazon field groups
# ---------------------------------------------------------------------------

AMAZON_FIELD_GROUPS: dict[str, FieldGroupSpec] = {
    # Products (15)
    _products_identity.name: _products_identity,
    _products_pricing.name: _products_pricing,
    _products_description.name: _products_description,
    _products_category.name: _products_category,
    _products_visual.name: _products_visual,
    _products_availability.name: _products_availability,
    _products_competition.name: _products_competition,
    _products_reviews_summary.name: _products_reviews_summary,
    _products_variants.name: _products_variants,
    _products_compliance.name: _products_compliance,
    _products_multimodal_images.name: _products_multimodal_images,
    _products_multi_level_summary.name: _products_multi_level_summary,
    _products_market_positioning.name: _products_market_positioning,
    _products_listing_quality.name: _products_listing_quality,
    _products_linkable_ids.name: _products_linkable_ids,
    # Reviews (9)
    _reviews_identity.name: _reviews_identity,
    _reviews_content.name: _reviews_content,
    _reviews_analysis.name: _reviews_analysis,
    _reviews_quality.name: _reviews_quality,
    _reviews_structured.name: _reviews_structured,
    _reviews_media.name: _reviews_media,
    _reviews_multimodal_images.name: _reviews_multimodal_images,
    _reviews_multi_level_summary.name: _reviews_multi_level_summary,
    _reviews_depth.name: _reviews_depth,
    # Sellers (6)
    _sellers_identity.name: _sellers_identity,
    _sellers_performance.name: _sellers_performance,
    _sellers_portfolio.name: _sellers_portfolio,
    _sellers_business_intel.name: _sellers_business_intel,
    _sellers_multi_level_summary.name: _sellers_multi_level_summary,
    _sellers_linkable_ids.name: _sellers_linkable_ids,
}
