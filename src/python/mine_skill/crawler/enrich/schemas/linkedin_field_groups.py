"""LinkedIn field groups aligned with schema(1) contracts.

The primary groups mirror the canonical LinkedIn profile/company/job/post
schemas. A small set of compatibility aliases is retained so older callers
still resolve to sensible prompt-driven groups while the platform defaults now
route only the smaller core subsets.
"""

from __future__ import annotations

from dataclasses import replace

from crawler.enrich.schemas.field_group_registry import FieldGroupSpec, GenerativeConfig, OutputFieldSpec


def _field(name: str, field_type: str = "string", description: str = "") -> OutputFieldSpec:
    return OutputFieldSpec(name=name, field_type=field_type, description=description)


def _group(
    *,
    name: str,
    description: str,
    required_source_fields: list[str],
    output_fields: list[OutputFieldSpec],
    subdataset: str,
    max_tokens: int = 768,
    requires_vision: bool = False,
) -> FieldGroupSpec:
    return FieldGroupSpec(
        name=name,
        description=description,
        required_source_fields=required_source_fields,
        output_fields=output_fields,
        strategy="generative_only",
        generative_config=GenerativeConfig(prompt_template=f"{name}.jinja2", max_tokens=max_tokens),
        requires_vision=requires_vision,
        platform="linkedin",
        subdataset=subdataset,
    )


def _alias(name: str, spec: FieldGroupSpec, *, description: str | None = None) -> FieldGroupSpec:
    return replace(spec, name=name, description=description or f"Compatibility alias for {spec.name}")


_profiles_identity = _group(
    name="linkedin_profiles_identity",
    description="Identity inference for LinkedIn profiles.",
    required_source_fields=["name"],
    output_fields=[
        _field("name_gender_inference"),
        _field("name_ethnicity_estimation"),
        _field("profile_language_detected"),
        _field("linkable_identifiers", "object"),
    ],
    subdataset="profile",
)

_profiles_summary = _group(
    name="linkedin_profiles_summary",
    description="About-section summary and topic extraction for LinkedIn profiles.",
    required_source_fields=["about"],
    output_fields=[
        _field("about_summary"),
        _field("about_topics", "array<string>"),
        _field("about_sentiment"),
        _field("career_narrative_type"),
        _field("one_line_summary"),
        _field("recruiter_brief"),
        _field("investor_brief"),
        _field("full_profile_narrative"),
        _field("writing_style_profile"),
        _field("culture_fit_indicators"),
    ],
    subdataset="profile",
)

_profiles_career = _group(
    name="linkedin_profiles_career",
    description="Career normalization and trajectory inference for LinkedIn profiles.",
    required_source_fields=["headline"],
    output_fields=[
        _field("standardized_job_title"),
        _field("seniority_level"),
        _field("job_function_category"),
        _field("current_company_name"),
        _field("current_company_id"),
        _field("career_trajectory_vector", "array<number>"),
        _field("open_to_work", "boolean"),
        _field("job_change_signal_strength", "number"),
        _field("experience_structured", "array<object>"),
        _field("education_structured", "array<object>"),
        _field("skills_extracted", "array<string>"),
        _field("skill_categories", "array<string>"),
        _field("skill_proficiency_inferred", "object"),
        _field("career_transition_detected", "boolean"),
        _field("experience_gap_analysis"),
        _field("interview_questions_suggested", "array<object>"),
        _field("qa_pairs_generated", "array<object>"),
    ],
    subdataset="profile",
    max_tokens=1024,
)

_profiles_credibility = _group(
    name="linkedin_profiles_credibility",
    description="Credibility and authority signals for LinkedIn profiles.",
    required_source_fields=["headline"],
    output_fields=[
        _field("influence_score", "number"),
        _field("content_creator_tier"),
        _field("engagement_rate", "number"),
        _field("credibility_assessment"),
        _field("content_activity_level"),
        _field("professional_cluster"),
        _field("profile_completeness_score", "number"),
        _field("last_active_estimate"),
        _field("profile_freshness_grade"),
        _field("motivation_signals", "array<string>"),
        _field("side_project_signals", "array<string>"),
        _field("cold_outreach_hooks", "array<string>"),
        _field("internal_consistency_flags", "array<string>"),
    ],
    subdataset="profile",
)

_profiles_multimodal = _group(
    name="linkedin_profiles_multimodal",
    description="Avatar and banner analysis for LinkedIn profiles.",
    required_source_fields=["avatar"],
    output_fields=[
        _field("avatar_quality_assessment", "object", "is_professional_headshot, face_detected, lighting_quality, background_type"),
        _field("banner_content_analysis", "object", "depicts, brand_alignment_score, text_extracted_from_banner"),
    ],
    subdataset="profile",
    max_tokens=1024,
    requires_vision=True,
)

_company_basic = _group(
    name="linkedin_company_basic",
    description="Company identity and basic normalization for LinkedIn companies.",
    required_source_fields=["company_name"],
    output_fields=[
        _field("company_legal_name_inferred"),
        _field("parent_company_mentioned"),
        _field("subsidiary_mentioned", "array<string>"),
    ],
    subdataset="company",
)

_company_org_intel = _group(
    name="linkedin_company_org_intel",
    description="Organizational intelligence for LinkedIn companies.",
    required_source_fields=["about"],
    output_fields=[
        _field("parent_company"),
        _field("subsidiary_tree", "array<string>"),
        _field("department_distribution_estimated", "object"),
        _field("parent_company_mentioned"),
        _field("subsidiary_mentioned", "array<string>"),
    ],
    subdataset="company",
)

_company_financial_signals = _group(
    name="linkedin_company_financial_signals",
    description="Financial signals for LinkedIn companies.",
    required_source_fields=["company_name", "about"],
    output_fields=[
        _field("revenue_range_estimated"),
        _field("funding_stage_inferred"),
        _field("revenue_hints_in_text"),
        _field("company_stage_signals", "object"),
        _field("investor_brief"),
    ],
    subdataset="company",
)

_company_talent_signals = _group(
    name="linkedin_company_talent_signals",
    description="Hiring and retention signals for LinkedIn companies.",
    required_source_fields=["employees_in_linkedin"],
    output_fields=[
        _field("employee_growth_trend"),
        _field("attrition_signal"),
        _field("hiring_velocity"),
        _field("posts_recent", "array<object>"),
    ],
    subdataset="company",
)

_company_tech_signals = _group(
    name="linkedin_company_tech_signals",
    description="Technology and engineering signals for LinkedIn companies.",
    required_source_fields=["about"],
    output_fields=[
        _field("tech_stack_inferred", "array<string>"),
        _field("engineering_team_size_estimated", "number"),
        _field("top_topics", "array<string>"),
    ],
    subdataset="company",
)

_company_summary = _group(
    name="linkedin_company_summary",
    description="Summary and narrative fields for LinkedIn companies.",
    required_source_fields=["company_name", "about"],
    output_fields=[
        _field("about_summary"),
        _field("core_business_extracted"),
        _field("value_proposition"),
        _field("target_market_inferred"),
        _field("industry_standardized"),
        _field("business_model_type"),
        _field("brand_voice_profile"),
        _field("elevator_pitch"),
        _field("investor_brief"),
        _field("competitor_brief"),
        _field("hiring_intent_from_about"),
        _field("posting_frequency"),
        _field("top_topics", "array<string>"),
        _field("linkable_identifiers", "object"),
        _field("content_strategy_analysis"),
        _field("company_legal_name_inferred"),
    ],
    subdataset="company",
    max_tokens=1024,
)

_jobs_basic = _group(
    name="linkedin_jobs_basic",
    description="Basic LinkedIn job normalization.",
    required_source_fields=["job_title", "location"],
    output_fields=[
        _field("job_title_standardized"),
        _field("remote_policy"),
        _field("remote_policy_detail"),
        _field("location_parsed", "object", "city, state, country"),
    ],
    subdataset="job",
)

_jobs_requirements = _group(
    name="linkedin_jobs_requirements",
    description="Requirements and skill extraction for LinkedIn jobs.",
    required_source_fields=["job_description"],
    output_fields=[
        _field("responsibilities_extracted", "array<string>"),
        _field("requirements_extracted", "array<object>", "skill, required_or_preferred, years_experience"),
        _field("benefits_extracted", "array<string>"),
        _field("team_size_hint"),
        _field("reporting_to_level"),
        _field("required_skills", "array<string>"),
        _field("preferred_skills", "array<string>"),
        _field("tools_and_platforms", "array<string>"),
        _field("programming_languages", "array<string>"),
        _field("frameworks", "array<string>"),
    ],
    subdataset="job",
    max_tokens=1024,
)

_jobs_market = _group(
    name="linkedin_jobs_market",
    description="Market and hiring urgency analysis for LinkedIn jobs.",
    required_source_fields=["job_title", "posted_date"],
    output_fields=[
        _field("competition_level"),
        _field("days_to_fill_estimated", "number"),
        _field("urgency_signal"),
    ],
    subdataset="job",
)

_jobs_compensation = _group(
    name="linkedin_jobs_compensation",
    description="Compensation inference for LinkedIn jobs.",
    required_source_fields=["job_description"],
    output_fields=[
        _field("salary_range_inferred"),
        _field("equity_compensation_signal"),
    ],
    subdataset="job",
)

_jobs_candidate_view = _group(
    name="linkedin_jobs_candidate_view",
    description="Candidate-facing role summary for LinkedIn jobs.",
    required_source_fields=["job_title", "job_description"],
    output_fields=[
        _field("candidate_facing_summary"),
        _field("hiring_manager_brief"),
        _field("ideal_candidate_persona"),
    ],
    subdataset="job",
    max_tokens=1024,
)

_jobs_risk = _group(
    name="linkedin_jobs_risk",
    description="Risk signals and contradictions in LinkedIn job posts.",
    required_source_fields=["job_description"],
    output_fields=[
        _field("red_flags_detected", "array<string>"),
        _field("culture_signals_extracted", "object"),
        _field("tech_stack_full_picture", "object"),
        _field("jd_internal_contradictions", "array<string>"),
        _field("role_clarity_score", "number"),
    ],
    subdataset="job",
)

_posts_basic = _group(
    name="linkedin_posts_basic",
    description="Basic content analysis for LinkedIn posts.",
    required_source_fields=["post_text"],
    output_fields=[
        _field("post_topic_tags", "array<string>"),
        _field("post_type"),
        _field("key_claims_extracted", "array<string>"),
    ],
    subdataset="post",
)

_posts_entities = _group(
    name="linkedin_posts_entities",
    description="Entity extraction for LinkedIn posts.",
    required_source_fields=["post_text"],
    output_fields=[
        _field("entities_mentioned", "array<object>", "name, type, sentiment"),
    ],
    subdataset="post",
)

_posts_engagement_analysis = _group(
    name="linkedin_posts_engagement_analysis",
    description="Engagement quality analysis for LinkedIn posts.",
    required_source_fields=["num_likes", "num_comments"],
    output_fields=[
        _field("engagement_quality_score", "number"),
        _field("comment_sentiment_distribution", "object"),
        _field("viral_coefficient_estimated", "number"),
        _field("controversial_flag", "boolean"),
    ],
    subdataset="post",
)

_posts_author_analysis = _group(
    name="linkedin_posts_author_analysis",
    description="Author authority signals for LinkedIn posts.",
    required_source_fields=["user_url"],
    output_fields=[
        _field("author_authority_score", "number"),
        _field("author_industry"),
        _field("is_corporate_voice", "boolean"),
    ],
    subdataset="post",
)

_posts_discourse = _group(
    name="linkedin_posts_discourse",
    description="Discourse and intent analysis for LinkedIn posts.",
    required_source_fields=["post_text"],
    output_fields=[
        _field("argument_structure"),
        _field("posting_intent"),
        _field("audience_targeting"),
        _field("self_promotion_score", "number"),
        _field("factual_claims_checkable", "array<string>"),
    ],
    subdataset="post",
)

_posts_multimodal = _group(
    name="linkedin_posts_multimodal",
    description="Multimodal analysis for LinkedIn post images and shared links.",
    required_source_fields=["post_media_urls"],
    output_fields=[
        _field("post_image_analysis", "array<object>", "image_type, text_extracted_from_image, chart_data_described, visual_sentiment"),
        _field("shared_link_content_summary"),
    ],
    subdataset="post",
    max_tokens=1024,
    requires_vision=True,
)

_posts_summary = _group(
    name="linkedin_posts_summary",
    description="Summary fields for LinkedIn posts.",
    required_source_fields=["post_text"],
    output_fields=[
        _field("post_one_liner"),
        _field("post_takeaway"),
        _field("thought_leadership_depth"),
    ],
    subdataset="post",
)


# Compatibility aliases retained for older tests/callers.
_profiles_current_role = replace(
    _profiles_career,
    name="linkedin_profiles_current_role",
    description="Compatibility alias for linkedin_profiles_career.",
    output_fields=[
        _field("standardized_job_title"),
        _field("seniority_level"),
        _field("job_function_category"),
    ],
)
_profiles_about = replace(_profiles_summary, name="linkedin_profiles_about", description="Compatibility alias for linkedin_profiles_summary.")
_company_profile = replace(
    _company_summary,
    name="linkedin_company_profile",
    description="Compatibility alias for linkedin_company_summary.",
    output_fields=[
        _field("about_summary"),
        _field("core_business_extracted"),
        _field("value_proposition"),
        _field("target_market_inferred"),
        _field("industry_standardized"),
    ],
)
_company_scale = replace(_company_talent_signals, name="linkedin_company_scale", description="Compatibility alias for linkedin_company_talent_signals.")
_jobs_content = replace(
    _jobs_requirements,
    name="linkedin_jobs_content",
    description="Compatibility alias for linkedin_jobs_requirements.",
    output_fields=[
        _field("responsibilities_extracted", "array<string>"),
        _field("requirements_extracted", "array<object>", "skill, required_or_preferred, years_experience"),
        _field("salary_range_inferred"),
        _field("benefits_extracted", "array<string>"),
        _field("team_size_hint"),
        _field("reporting_to_level"),
    ],
)
_jobs_classification = replace(
    _jobs_basic,
    name="linkedin_jobs_classification",
    description="Compatibility alias for linkedin_jobs_basic.",
    required_source_fields=["job_title", "job_description"],
    output_fields=[
        _field("role_category_fine_grained"),
        _field("industry_vertical"),
        _field("visa_sponsorship_signal"),
        _field("equity_compensation_signal"),
    ],
)
_jobs_skills = replace(
    _jobs_requirements,
    name="linkedin_jobs_skills",
    description="Compatibility alias for linkedin_jobs_requirements.",
    output_fields=[
        _field("required_skills", "array<string>"),
        _field("preferred_skills", "array<string>"),
        _field("tools_and_platforms", "array<string>"),
        _field("programming_languages", "array<string>"),
        _field("frameworks", "array<string>"),
    ],
)
_jobs_multi_level_summary = replace(
    _jobs_candidate_view,
    name="linkedin_jobs_multi_level_summary",
    description="Compatibility alias for linkedin_jobs_candidate_view.",
    output_fields=[
        _field("candidate_facing_summary"),
        _field("hiring_manager_brief"),
    ],
)
_jobs_domain_specific = replace(
    _jobs_risk,
    name="linkedin_jobs_domain_specific",
    description="Compatibility alias for linkedin_jobs_risk.",
    output_fields=[
        _field("red_flags_detected", "array<string>"),
        _field("culture_signals_extracted", "object", "management_style_hints, growth_opportunity_signals, work_life_balance_indicators"),
        _field("tech_stack_full_picture", "object", "must_have, nice_to_have, infrastructure, methodology"),
    ],
)
_posts_content = replace(
    _posts_basic,
    name="linkedin_posts_content",
    description="Compatibility alias for linkedin_posts_basic.",
    output_fields=[
        _field("post_topic_tags", "array<string>"),
        _field("post_type"),
        _field("key_claims_extracted", "array<string>"),
        _field("entities_mentioned", "array<object>", "name, type, sentiment"),
    ],
)
_posts_engagement = replace(_posts_engagement_analysis, name="linkedin_posts_engagement", description="Compatibility alias for linkedin_posts_engagement_analysis.")
_posts_author = replace(_posts_author_analysis, name="linkedin_posts_author", description="Compatibility alias for linkedin_posts_author_analysis.")
_posts_temporal = _group(
    name="linkedin_posts_temporal",
    description="Compatibility temporal analysis group for LinkedIn posts.",
    required_source_fields=["post_text", "posted_date"],
    output_fields=[
        _field("trending_topic_relevance", "number"),
        _field("news_event_linkage"),
    ],
    subdataset="post",
)
_posts_multi_level_summary = replace(
    _posts_summary,
    name="linkedin_posts_multi_level_summary",
    description="Compatibility alias for linkedin_posts_summary.",
    output_fields=[
        _field("post_one_liner"),
        _field("post_takeaway"),
    ],
)
_posts_behavioral = replace(
    _posts_summary,
    name="linkedin_posts_behavioral",
    description="Compatibility alias for linkedin_posts_summary.",
    output_fields=[
        _field("thought_leadership_depth"),
        _field("self_promotion_score", "number"),
        _field("argument_structure"),
    ],
)


LINKEDIN_FIELD_GROUPS: dict[str, FieldGroupSpec] = {
    _profiles_identity.name: _profiles_identity,
    _profiles_summary.name: _profiles_summary,
    _profiles_career.name: _profiles_career,
    _profiles_credibility.name: _profiles_credibility,
    _profiles_multimodal.name: _profiles_multimodal,
    _company_basic.name: _company_basic,
    _company_org_intel.name: _company_org_intel,
    _company_financial_signals.name: _company_financial_signals,
    _company_talent_signals.name: _company_talent_signals,
    _company_tech_signals.name: _company_tech_signals,
    _company_summary.name: _company_summary,
    _jobs_basic.name: _jobs_basic,
    _jobs_requirements.name: _jobs_requirements,
    _jobs_market.name: _jobs_market,
    _jobs_compensation.name: _jobs_compensation,
    _jobs_candidate_view.name: _jobs_candidate_view,
    _jobs_risk.name: _jobs_risk,
    _posts_basic.name: _posts_basic,
    _posts_entities.name: _posts_entities,
    _posts_engagement_analysis.name: _posts_engagement_analysis,
    _posts_author_analysis.name: _posts_author_analysis,
    _posts_discourse.name: _posts_discourse,
    _posts_multimodal.name: _posts_multimodal,
    _posts_summary.name: _posts_summary,
    _profiles_current_role.name: _profiles_current_role,
    _profiles_about.name: _profiles_about,
    _company_profile.name: _company_profile,
    _company_scale.name: _company_scale,
    _jobs_content.name: _jobs_content,
    _jobs_classification.name: _jobs_classification,
    _jobs_skills.name: _jobs_skills,
    _jobs_multi_level_summary.name: _jobs_multi_level_summary,
    _jobs_domain_specific.name: _jobs_domain_specific,
    _posts_content.name: _posts_content,
    _posts_engagement.name: _posts_engagement,
    _posts_author.name: _posts_author,
    _posts_temporal.name: _posts_temporal,
    _posts_multi_level_summary.name: _posts_multi_level_summary,
    _posts_behavioral.name: _posts_behavioral,
}
