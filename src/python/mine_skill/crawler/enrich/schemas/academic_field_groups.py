"""FieldGroupSpec definitions for arXiv and Wikipedia platforms.

Auto-generated from:
  - references/enrichment_catalog/arxiv.json   (18 field groups)
  - references/enrichment_catalog/wikipedia.json (17 field groups)
"""

from __future__ import annotations

from crawler.enrich.schemas.field_group_registry import (
    FieldGroupSpec,
    GenerativeConfig,
    OutputFieldSpec,
    PassthroughConfig,
)


def _passthrough_field_group(
    *,
    name: str,
    description: str,
    platform: str,
    subdataset: str,
    source_fields: list[str],
    output_field: str,
    field_type: str = "string",
) -> FieldGroupSpec:
    return FieldGroupSpec(
        name=name,
        description=description,
        required_source_fields=[],
        output_fields=[OutputFieldSpec(name=output_field, field_type=field_type)],
        strategy="passthrough",
        passthrough_config=PassthroughConfig(source_fields=source_fields, output_field=output_field),
        platform=platform,
        subdataset=subdataset,
    )


ARXIV_BASE_FIELD_GROUPS: dict[str, FieldGroupSpec] = {
    "arxiv_base_dedup_key": _passthrough_field_group(name="arxiv_base_dedup_key", description="Pass through arXiv dedup key", platform="arxiv", subdataset="paper", source_fields=["dedup_key"], output_field="dedup_key"),
    "arxiv_base_canonical_url": _passthrough_field_group(name="arxiv_base_canonical_url", description="Pass through canonical URL", platform="arxiv", subdataset="paper", source_fields=["canonical_url"], output_field="canonical_url"),
    "arxiv_base_url": _passthrough_field_group(name="arxiv_base_url", description="Pass through source URL", platform="arxiv", subdataset="paper", source_fields=["URL"], output_field="URL"),
    "arxiv_base_arxiv_id": _passthrough_field_group(name="arxiv_base_arxiv_id", description="Pass through arXiv id", platform="arxiv", subdataset="paper", source_fields=["arxiv_id"], output_field="arxiv_id"),
    "arxiv_base_doi": _passthrough_field_group(name="arxiv_base_doi", description="Pass through DOI", platform="arxiv", subdataset="paper", source_fields=["DOI", "doi"], output_field="DOI"),
    "arxiv_base_title": _passthrough_field_group(name="arxiv_base_title", description="Pass through title", platform="arxiv", subdataset="paper", source_fields=["title"], output_field="title"),
    "arxiv_base_abstract": _passthrough_field_group(name="arxiv_base_abstract", description="Pass through abstract", platform="arxiv", subdataset="paper", source_fields=["abstract"], output_field="abstract"),
    "arxiv_base_page_count": _passthrough_field_group(name="arxiv_base_page_count", description="Pass through page count", platform="arxiv", subdataset="paper", source_fields=["page_count"], output_field="page_count", field_type="integer"),
    "arxiv_base_num_authors": _passthrough_field_group(name="arxiv_base_num_authors", description="Pass through author count", platform="arxiv", subdataset="paper", source_fields=["num_authors"], output_field="num_authors", field_type="integer"),
    "arxiv_base_num_figures": _passthrough_field_group(name="arxiv_base_num_figures", description="Pass through figure count", platform="arxiv", subdataset="paper", source_fields=["num_figures"], output_field="num_figures", field_type="integer"),
    "arxiv_base_authors": _passthrough_field_group(name="arxiv_base_authors", description="Pass through authors", platform="arxiv", subdataset="paper", source_fields=["authors"], output_field="authors", field_type="array<object>"),
    "arxiv_base_categories": _passthrough_field_group(name="arxiv_base_categories", description="Pass through categories", platform="arxiv", subdataset="paper", source_fields=["categories"], output_field="categories", field_type="array<string>"),
    "arxiv_base_primary_category": _passthrough_field_group(name="arxiv_base_primary_category", description="Pass through primary category", platform="arxiv", subdataset="paper", source_fields=["primary_category"], output_field="primary_category"),
    "arxiv_base_submission_date": _passthrough_field_group(name="arxiv_base_submission_date", description="Pass through submission date", platform="arxiv", subdataset="paper", source_fields=["submission_date", "published"], output_field="submission_date"),
    "arxiv_base_update_date": _passthrough_field_group(name="arxiv_base_update_date", description="Pass through update date", platform="arxiv", subdataset="paper", source_fields=["update_date", "updated"], output_field="update_date"),
    "arxiv_base_versions": _passthrough_field_group(name="arxiv_base_versions", description="Pass through versions", platform="arxiv", subdataset="paper", source_fields=["versions"], output_field="versions", field_type="array<object>"),
    "arxiv_base_submission_comments": _passthrough_field_group(name="arxiv_base_submission_comments", description="Pass through submission comments", platform="arxiv", subdataset="paper", source_fields=["submission_comments", "comment"], output_field="submission_comments"),
    "arxiv_base_journal_ref": _passthrough_field_group(name="arxiv_base_journal_ref", description="Pass through journal reference", platform="arxiv", subdataset="paper", source_fields=["journal_ref"], output_field="journal_ref"),
    "arxiv_base_license": _passthrough_field_group(name="arxiv_base_license", description="Pass through license", platform="arxiv", subdataset="paper", source_fields=["license"], output_field="license"),
    "arxiv_base_raw_text": _passthrough_field_group(name="arxiv_base_raw_text", description="Pass through raw paper text", platform="arxiv", subdataset="paper", source_fields=["raw_text", "plain_text"], output_field="raw_text"),
    "arxiv_base_pdf_url": _passthrough_field_group(name="arxiv_base_pdf_url", description="Pass through PDF URL", platform="arxiv", subdataset="paper", source_fields=["PDF_url", "pdf_url"], output_field="PDF_url"),
    "arxiv_base_references": _passthrough_field_group(name="arxiv_base_references", description="Pass through references", platform="arxiv", subdataset="paper", source_fields=["references"], output_field="references", field_type="array<string>"),
}

WIKIPEDIA_BASE_FIELD_GROUPS: dict[str, FieldGroupSpec] = {
    "wikipedia_base_dedup_key": _passthrough_field_group(name="wikipedia_base_dedup_key", description="Pass through article dedup key", platform="wikipedia", subdataset="article", source_fields=["dedup_key"], output_field="dedup_key"),
    "wikipedia_base_canonical_url": _passthrough_field_group(name="wikipedia_base_canonical_url", description="Pass through canonical URL", platform="wikipedia", subdataset="article", source_fields=["canonical_url"], output_field="canonical_url"),
    "wikipedia_base_url": _passthrough_field_group(name="wikipedia_base_url", description="Pass through source URL", platform="wikipedia", subdataset="article", source_fields=["URL"], output_field="URL"),
    "wikipedia_base_page_id": _passthrough_field_group(name="wikipedia_base_page_id", description="Pass through page id", platform="wikipedia", subdataset="article", source_fields=["page_id"], output_field="page_id"),
    "wikipedia_base_title": _passthrough_field_group(name="wikipedia_base_title", description="Pass through title", platform="wikipedia", subdataset="article", source_fields=["title"], output_field="title"),
    "wikipedia_base_language": _passthrough_field_group(name="wikipedia_base_language", description="Pass through language", platform="wikipedia", subdataset="article", source_fields=["language"], output_field="language"),
    "wikipedia_base_article_creation_date": _passthrough_field_group(name="wikipedia_base_article_creation_date", description="Pass through creation date", platform="wikipedia", subdataset="article", source_fields=["article_creation_date"], output_field="article_creation_date"),
    "wikipedia_base_protection_level": _passthrough_field_group(name="wikipedia_base_protection_level", description="Pass through protection level", platform="wikipedia", subdataset="article", source_fields=["protection_level"], output_field="protection_level"),
    "wikipedia_base_raw_text": _passthrough_field_group(name="wikipedia_base_raw_text", description="Pass through raw article text", platform="wikipedia", subdataset="article", source_fields=["raw_text", "plain_text"], output_field="raw_text"),
    "wikipedia_base_html": _passthrough_field_group(name="wikipedia_base_html", description="Pass through article HTML or markdown", platform="wikipedia", subdataset="article", source_fields=["HTML", "markdown"], output_field="HTML"),
    "wikipedia_base_word_count": _passthrough_field_group(name="wikipedia_base_word_count", description="Pass through word count", platform="wikipedia", subdataset="article", source_fields=["word_count"], output_field="word_count", field_type="integer"),
    "wikipedia_base_number_of_sections": _passthrough_field_group(name="wikipedia_base_number_of_sections", description="Pass through number of sections", platform="wikipedia", subdataset="article", source_fields=["number_of_sections"], output_field="number_of_sections", field_type="integer"),
    "wikipedia_base_has_infobox": _passthrough_field_group(name="wikipedia_base_has_infobox", description="Pass through infobox flag", platform="wikipedia", subdataset="article", source_fields=["has_infobox"], output_field="has_infobox", field_type="boolean"),
    "wikipedia_base_infobox_raw": _passthrough_field_group(name="wikipedia_base_infobox_raw", description="Pass through raw infobox content", platform="wikipedia", subdataset="article", source_fields=["infobox_raw"], output_field="infobox_raw"),
    "wikipedia_base_categories": _passthrough_field_group(name="wikipedia_base_categories", description="Pass through categories", platform="wikipedia", subdataset="article", source_fields=["categories"], output_field="categories", field_type="array<string>"),
    "wikipedia_base_references_count": _passthrough_field_group(name="wikipedia_base_references_count", description="Pass through references count", platform="wikipedia", subdataset="article", source_fields=["references_count"], output_field="references_count", field_type="integer"),
    "wikipedia_base_external_links_count": _passthrough_field_group(name="wikipedia_base_external_links_count", description="Pass through external links count", platform="wikipedia", subdataset="article", source_fields=["external_links_count"], output_field="external_links_count", field_type="integer"),
    "wikipedia_base_references": _passthrough_field_group(name="wikipedia_base_references", description="Pass through references", platform="wikipedia", subdataset="article", source_fields=["references"], output_field="references", field_type="array<string>"),
    "wikipedia_base_see_also": _passthrough_field_group(name="wikipedia_base_see_also", description="Pass through see also links", platform="wikipedia", subdataset="article", source_fields=["see_also"], output_field="see_also", field_type="array<string>"),
    "wikipedia_base_images": _passthrough_field_group(name="wikipedia_base_images", description="Pass through image URLs", platform="wikipedia", subdataset="article", source_fields=["images"], output_field="images", field_type="array<string>"),
}

# ---------------------------------------------------------------------------
# arXiv field groups (18)
# ---------------------------------------------------------------------------

ARXIV_FIELD_GROUPS: dict[str, FieldGroupSpec] = {
    # 1. Identity ──────────────────────────────────────────────────────────
    "arxiv_identity": FieldGroupSpec(
        name="arxiv_identity",
        description="Title and abstract normalization",
        required_source_fields=["title", "abstract"],
        output_fields=[
            OutputFieldSpec(name="title_normalized", field_type="string"),
            OutputFieldSpec(name="abstract_plain_text", field_type="string"),
        ],
        strategy="generative_only",
        generative_config=GenerativeConfig(prompt_template="arxiv_identity.jinja2"),
        platform="arxiv",
    ),
    # 2. Authors ───────────────────────────────────────────────────────────
    "arxiv_authors": FieldGroupSpec(
        name="arxiv_authors",
        description="Structured author list with affiliation and career metadata",
        required_source_fields=["authors"],
        output_fields=[
            OutputFieldSpec(
                name="authors_structured",
                field_type="array<object>",
                description="full_name, first_name, last_name, affiliation_standardized, affiliation_type, affiliation_country, author_id_crossref, h_index_estimated, career_stage_inferred",
            ),
        ],
        strategy="generative_only",
        generative_config=GenerativeConfig(
            prompt_template="arxiv_authors.jinja2",
            max_tokens=1024,
        ),
        platform="arxiv",
    ),
    # 3. Classification ────────────────────────────────────────────────────
    "arxiv_classification": FieldGroupSpec(
        name="arxiv_classification",
        description="Topic hierarchy, keywords, research area, and interdisciplinary score",
        required_source_fields=["title", "abstract", "categories"],
        output_fields=[
            OutputFieldSpec(name="topic_hierarchy", field_type="array<string>"),
            OutputFieldSpec(name="keywords_extracted", field_type="array<string>"),
            OutputFieldSpec(name="research_area_plain_english", field_type="string"),
            OutputFieldSpec(name="interdisciplinary_score", field_type="number"),
        ],
        strategy="generative_only",
        generative_config=GenerativeConfig(
            prompt_template="arxiv_classification.jinja2",
            max_tokens=512,
        ),
        platform="arxiv",
    ),
    # 4. Dates ─────────────────────────────────────────────────────────────
    "arxiv_dates": FieldGroupSpec(
        name="arxiv_dates",
        description="Acceptance status inference, venue identification, and tier classification",
        required_source_fields=["title", "abstract"],
        output_fields=[
            OutputFieldSpec(name="acceptance_status_inferred", field_type="string"),
            OutputFieldSpec(name="venue_mentioned", field_type="string"),
            OutputFieldSpec(name="venue_published", field_type="string"),
            OutputFieldSpec(name="venue_tier_mapped", field_type="string"),
            OutputFieldSpec(name="venue_tier", field_type="string"),
            OutputFieldSpec(name="target_venue_inferred", field_type="string"),
        ],
        strategy="generative_only",
        generative_config=GenerativeConfig(prompt_template="arxiv_dates.jinja2"),
        platform="arxiv",
    ),
    # 5. Full Text ─────────────────────────────────────────────────────────
    "arxiv_full_text": FieldGroupSpec(
        name="arxiv_full_text",
        description="Structured section breakdown of the full paper text",
        required_source_fields=["raw_text"],
        output_fields=[
            OutputFieldSpec(
                name="sections_structured",
                field_type="array<object>",
                description="heading, content_summary, section_type",
            ),
        ],
        strategy="generative_only",
        generative_config=GenerativeConfig(
            prompt_template="arxiv_full_text.jinja2",
            max_tokens=1024,
        ),
        platform="arxiv",
    ),
    # 6. Contribution ──────────────────────────────────────────────────────
    "arxiv_contribution": FieldGroupSpec(
        name="arxiv_contribution",
        description="Main contributions, novelty type, problem statement, and proposed solution",
        required_source_fields=["title", "abstract"],
        output_fields=[
            OutputFieldSpec(name="main_contributions", field_type="array<string>"),
            OutputFieldSpec(name="novelty_type", field_type="string"),
            OutputFieldSpec(name="problem_statement", field_type="string"),
            OutputFieldSpec(name="proposed_solution_summary", field_type="string"),
        ],
        strategy="generative_only",
        generative_config=GenerativeConfig(
            prompt_template="arxiv_contribution.jinja2",
            max_tokens=512,
        ),
        platform="arxiv",
    ),
    # 7. Methodology ───────────────────────────────────────────────────────
    "arxiv_methodology": FieldGroupSpec(
        name="arxiv_methodology",
        description="Methods, baselines, metrics, datasets, and experimental setup",
        required_source_fields=["title", "abstract"],
        output_fields=[
            OutputFieldSpec(
                name="methods_used",
                field_type="array<object>",
                description="method_name, method_category, is_novel",
            ),
            OutputFieldSpec(name="baselines_compared", field_type="array<string>"),
            OutputFieldSpec(name="evaluation_metrics", field_type="array<string>"),
            OutputFieldSpec(
                name="datasets_used",
                field_type="array<object>",
                description="name, url, size, domain",
            ),
            OutputFieldSpec(name="experimental_setup_summary", field_type="string"),
        ],
        strategy="generative_only",
        generative_config=GenerativeConfig(
            prompt_template="arxiv_methodology.jinja2",
            max_tokens=1024,
        ),
        platform="arxiv",
    ),
    # 8. Results ───────────────────────────────────────────────────────────
    "arxiv_results": FieldGroupSpec(
        name="arxiv_results",
        description="Key results, SOTA claims, statistical significance, and reproducibility",
        required_source_fields=["title", "abstract"],
        output_fields=[
            OutputFieldSpec(
                name="key_results",
                field_type="array<object>",
                description="metric, value, baseline_comparison, improvement_percentage",
            ),
            OutputFieldSpec(name="state_of_art_claimed", field_type="boolean"),
            OutputFieldSpec(name="statistical_significance_reported", field_type="boolean"),
            OutputFieldSpec(name="reproducibility_indicators", field_type="array<string>"),
        ],
        strategy="generative_only",
        generative_config=GenerativeConfig(
            prompt_template="arxiv_results.jinja2",
            max_tokens=512,
        ),
        platform="arxiv",
    ),
    # 9. Limitations ───────────────────────────────────────────────────────
    "arxiv_limitations": FieldGroupSpec(
        name="arxiv_limitations",
        description="Stated limitations, future work directions, and threats to validity",
        required_source_fields=["title", "abstract"],
        output_fields=[
            OutputFieldSpec(name="limitations_stated", field_type="array<string>"),
            OutputFieldSpec(name="future_work_directions", field_type="array<string>"),
            OutputFieldSpec(name="threats_to_validity", field_type="array<string>"),
        ],
        strategy="generative_only",
        generative_config=GenerativeConfig(
            prompt_template="arxiv_limitations.jinja2",
            max_tokens=512,
        ),
        platform="arxiv",
    ),
    # 10. References ───────────────────────────────────────────────────────
    "arxiv_references": FieldGroupSpec(
        name="arxiv_references",
        description="Structured reference list with citation context and counts",
        required_source_fields=["references"],
        output_fields=[
            OutputFieldSpec(
                name="references_structured",
                field_type="array<object>",
                description="title, authors, year, venue, citation_context, citation_sentiment",
            ),
            OutputFieldSpec(name="total_citation_count", field_type="integer"),
            OutputFieldSpec(name="influential_citation_count", field_type="integer"),
        ],
        strategy="generative_only",
        generative_config=GenerativeConfig(
            prompt_template="arxiv_references.jinja2",
            max_tokens=1024,
        ),
        platform="arxiv",
    ),
    # 11. Code & Data ──────────────────────────────────────────────────────
    "arxiv_code_and_data": FieldGroupSpec(
        name="arxiv_code_and_data",
        description="Code availability, framework, dataset release, and open-access status",
        required_source_fields=["title", "abstract"],
        output_fields=[
            OutputFieldSpec(name="code_available", field_type="boolean"),
            OutputFieldSpec(name="code_url", field_type="string", required=False),
            OutputFieldSpec(name="code_framework", field_type="string", required=False),
            OutputFieldSpec(name="dataset_released", field_type="boolean"),
            OutputFieldSpec(name="dataset_url", field_type="string", required=False),
            OutputFieldSpec(name="open_access_status", field_type="string"),
        ],
        strategy="generative_only",
        generative_config=GenerativeConfig(prompt_template="arxiv_code_and_data.jinja2"),
        platform="arxiv",
    ),
    # 12. Embeddings ───────────────────────────────────────────────────────
    "arxiv_embeddings": FieldGroupSpec(
        name="arxiv_embeddings",
        description="Vector embeddings for title, abstract, and full paper",
        required_source_fields=["title", "abstract"],
        output_fields=[
            OutputFieldSpec(name="title_embedding", field_type="array<number>"),
            OutputFieldSpec(name="abstract_embedding", field_type="array<number>"),
            OutputFieldSpec(name="full_paper_embedding", field_type="array<number>", required=False),
        ],
        strategy="generative_only",
        generative_config=GenerativeConfig(
            prompt_template="arxiv_embeddings.jinja2",
            max_tokens=16,
        ),
        platform="arxiv",
    ),
    # 13. Relations ────────────────────────────────────────────────────────
    "arxiv_relations": FieldGroupSpec(
        name="arxiv_relations",
        description="Inter-paper relationships: builds upon, contradicts, replicates, shared datasets/methods",
        required_source_fields=["title", "abstract", "references"],
        output_fields=[
            OutputFieldSpec(name="builds_upon", field_type="array<string>"),
            OutputFieldSpec(name="contradicts", field_type="array<string>"),
            OutputFieldSpec(name="replicates", field_type="array<string>"),
            OutputFieldSpec(name="uses_dataset_from", field_type="array<string>"),
            OutputFieldSpec(name="uses_method_from", field_type="array<string>"),
        ],
        strategy="generative_only",
        generative_config=GenerativeConfig(
            prompt_template="arxiv_relations.jinja2",
            max_tokens=512,
        ),
        platform="arxiv",
    ),
    # 14. Multimodal Figures ───────────────────────────────────────────────
    "arxiv_multimodal_figures": FieldGroupSpec(
        name="arxiv_multimodal_figures",
        description="Vision-based analysis of paper figures: type, caption enhancement, data extraction",
        required_source_fields=["figures"],
        output_fields=[
            OutputFieldSpec(
                name="figures_analyzed",
                field_type="array<object>",
                description="figure_id, figure_type, caption_original, caption_enhanced, key_findings_from_figure, data_points_extracted, components_identified",
            ),
        ],
        strategy="generative_only",
        generative_config=GenerativeConfig(
            prompt_template="arxiv_multimodal_figures.jinja2",
            max_tokens=1024,
        ),
        requires_vision=True,
        platform="arxiv",
    ),
    # 15. Multimodal Equations ─────────────────────────────────────────────
    "arxiv_multimodal_equations": FieldGroupSpec(
        name="arxiv_multimodal_equations",
        description="Vision-based equation parsing: LaTeX, plain English explanation, variable definitions",
        required_source_fields=["full_text"],
        output_fields=[
            OutputFieldSpec(
                name="key_equations",
                field_type="array<object>",
                description="equation_latex, equation_id, plain_english_explanation, variables_defined, equation_role",
            ),
        ],
        strategy="generative_only",
        generative_config=GenerativeConfig(
            prompt_template="arxiv_multimodal_equations.jinja2",
            max_tokens=1024,
        ),
        requires_vision=True,
        platform="arxiv",
    ),
    # 16. Multi-level Summary ──────────────────────────────────────────────
    "arxiv_multi_level_summary": FieldGroupSpec(
        name="arxiv_multi_level_summary",
        description="Multiple summary styles: tweet, one-line, executive, layman, technical, review",
        required_source_fields=["title", "abstract"],
        output_fields=[
            OutputFieldSpec(name="tweet_summary", field_type="string"),
            OutputFieldSpec(name="one_line_summary", field_type="string"),
            OutputFieldSpec(name="executive_summary", field_type="string"),
            OutputFieldSpec(name="layman_summary", field_type="string"),
            OutputFieldSpec(name="technical_abstract_enhanced", field_type="string"),
            OutputFieldSpec(name="practitioner_takeaway", field_type="string"),
            OutputFieldSpec(name="qa_pairs_generated", field_type="array<object>"),
            OutputFieldSpec(name="review_style_summary", field_type="object"),
        ],
        strategy="generative_only",
        generative_config=GenerativeConfig(
            prompt_template="arxiv_multi_level_summary.jinja2",
            max_tokens=1024,
        ),
        platform="arxiv",
    ),
    # 17. Research Depth Analysis ──────────────────────────────────────────
    "arxiv_research_depth_analysis": FieldGroupSpec(
        name="arxiv_research_depth_analysis",
        description="Mathematical complexity, novelty delta, methodology transferability, claim verification",
        required_source_fields=["title", "abstract"],
        output_fields=[
            OutputFieldSpec(name="mathematical_complexity_score", field_type="integer"),
            OutputFieldSpec(name="mathematical_complexity_evidence", field_type="string"),
            OutputFieldSpec(name="novelty_delta_assessment", field_type="object"),
            OutputFieldSpec(name="methodology_transferability", field_type="array<string>"),
            OutputFieldSpec(name="claim_verification_notes", field_type="array<object>"),
            OutputFieldSpec(name="internal_consistency_issues", field_type="array<string>"),
            OutputFieldSpec(name="missing_baselines_or_ablations", field_type="array<string>"),
            OutputFieldSpec(name="cherry_picking_indicators", field_type="array<string>"),
            OutputFieldSpec(name="writing_quality_assessment", field_type="string"),
            OutputFieldSpec(name="experiment_rigor_score", field_type="number"),
            OutputFieldSpec(name="readability_for_audience", field_type="string"),
            OutputFieldSpec(name="follow_up_research_questions", field_type="array<string>"),
        ],
        strategy="generative_only",
        generative_config=GenerativeConfig(
            prompt_template="arxiv_research_depth_analysis.jinja2",
            max_tokens=1024,
        ),
        platform="arxiv",
    ),
    # 18. Cross-dataset Linkable IDs ───────────────────────────────────────
    "arxiv_cross_dataset_linkable_ids": FieldGroupSpec(
        name="arxiv_cross_dataset_linkable_ids",
        description="Cross-platform identifiers: LinkedIn hints, GitHub repos, project URLs, Wikipedia concepts, dataset sources, related arXiv IDs",
        required_source_fields=["title", "abstract"],
        output_fields=[
            OutputFieldSpec(
                name="linkable_identifiers",
                field_type="object",
                description="author_linkedin_hints, github_repos_mentioned, project_urls_mentioned, wikipedia_concept_hints, dataset_source_urls, related_arxiv_ids_mentioned",
            ),
        ],
        strategy="generative_only",
        generative_config=GenerativeConfig(
            prompt_template="arxiv_cross_dataset_linkable_ids.jinja2",
        ),
        platform="arxiv",
    ),
}

# ---------------------------------------------------------------------------
# Wikipedia field groups (17)
# ---------------------------------------------------------------------------

WIKIPEDIA_FIELD_GROUPS: dict[str, FieldGroupSpec] = {
    # 1. Identity ──────────────────────────────────────────────────────────
    "wikipedia_identity": FieldGroupSpec(
        name="wikipedia_identity",
        description="Disambiguated title, canonical entity name, entity type, and Wikidata ID",
        required_source_fields=["title"],
        output_fields=[
            OutputFieldSpec(name="title_disambiguated", field_type="string"),
            OutputFieldSpec(name="canonical_entity_name", field_type="string"),
            OutputFieldSpec(name="entity_type", field_type="string"),
            OutputFieldSpec(name="wikidata_id", field_type="string"),
        ],
        strategy="generative_only",
        generative_config=GenerativeConfig(prompt_template="wikipedia_identity.jinja2"),
        platform="wikipedia",
    ),
    # 2. Content ───────────────────────────────────────────────────────────
    "wikipedia_content": FieldGroupSpec(
        name="wikipedia_content",
        description="Structured sections, table of contents, article summary, and reading level",
        required_source_fields=["raw_text"],
        output_fields=[
            OutputFieldSpec(
                name="sections_structured",
                field_type="array<object>",
                description="heading, content, section_type",
            ),
            OutputFieldSpec(name="table_of_contents", field_type="array<string>"),
            OutputFieldSpec(name="article_summary", field_type="string"),
            OutputFieldSpec(name="reading_level", field_type="string"),
            OutputFieldSpec(name="alternative_explanations", field_type="array<string>"),
            OutputFieldSpec(name="section_interdependency_map", field_type="array<object>"),
            OutputFieldSpec(name="qa_pairs_generated", field_type="array<object>"),
        ],
        strategy="generative_only",
        generative_config=GenerativeConfig(
            prompt_template="wikipedia_content.jinja2",
            max_tokens=4096,
        ),
        platform="wikipedia",
    ),
    # 3. Tables ────────────────────────────────────────────────────────────
    "wikipedia_tables": FieldGroupSpec(
        name="wikipedia_tables",
        description="Structured extraction of HTML/wikitext tables",
        required_source_fields=["HTML"],
        output_fields=[
            OutputFieldSpec(
                name="tables_structured",
                field_type="array<object>",
                description="table_title, headers, rows, table_topic, data_type",
            ),
        ],
        strategy="generative_only",
        generative_config=GenerativeConfig(
            prompt_template="wikipedia_tables.jinja2",
            max_tokens=1024,
        ),
        platform="wikipedia",
    ),
    # 4. Infobox ───────────────────────────────────────────────────────────
    "wikipedia_infobox": FieldGroupSpec(
        name="wikipedia_infobox",
        description="Structured infobox key-value extraction",
        required_source_fields=["infobox_raw"],
        output_fields=[
            OutputFieldSpec(name="infobox_structured", field_type="object"),
            OutputFieldSpec(name="infobox_text_consistency", field_type="string"),
        ],
        strategy="generative_only",
        generative_config=GenerativeConfig(prompt_template="wikipedia_infobox.jinja2"),
        platform="wikipedia",
    ),
    # 5. Categories ────────────────────────────────────────────────────────
    "wikipedia_categories": FieldGroupSpec(
        name="wikipedia_categories",
        description="Cleaned categories, topic hierarchy, domain, and subject tags",
        required_source_fields=["categories"],
        output_fields=[
            OutputFieldSpec(name="categories_cleaned", field_type="array<string>"),
            OutputFieldSpec(name="topic_hierarchy", field_type="array<string>"),
            OutputFieldSpec(name="domain", field_type="string"),
            OutputFieldSpec(name="subject_tags", field_type="array<string>"),
        ],
        strategy="generative_only",
        generative_config=GenerativeConfig(
            prompt_template="wikipedia_categories.jinja2",
            max_tokens=512,
        ),
        platform="wikipedia",
    ),
    # 6. Entities ──────────────────────────────────────────────────────────
    "wikipedia_entities": FieldGroupSpec(
        name="wikipedia_entities",
        description="Named entity extraction with Wikidata IDs and relation to subject",
        required_source_fields=["raw_text"],
        output_fields=[
            OutputFieldSpec(
                name="entities_extracted",
                field_type="array<object>",
                description="name, type, wikidata_id, first_mention_context, relation_to_subject",
            ),
        ],
        strategy="generative_only",
        generative_config=GenerativeConfig(
            prompt_template="wikipedia_entities.jinja2",
            max_tokens=1024,
        ),
        platform="wikipedia",
    ),
    # 7. Facts ─────────────────────────────────────────────────────────────
    "wikipedia_facts": FieldGroupSpec(
        name="wikipedia_facts",
        description="Structured fact triples with confidence scores and temporal scope",
        required_source_fields=["raw_text"],
        output_fields=[
            OutputFieldSpec(
                name="structured_facts",
                field_type="array<object>",
                description="subject, predicate, object, confidence_score, temporal_scope, source_sentence",
            ),
        ],
        strategy="generative_only",
        generative_config=GenerativeConfig(
            prompt_template="wikipedia_facts.jinja2",
            max_tokens=1024,
        ),
        platform="wikipedia",
    ),
    # 8. Timeline ──────────────────────────────────────────────────────────
    "wikipedia_timeline": FieldGroupSpec(
        name="wikipedia_timeline",
        description="Chronological event extraction with types and participants",
        required_source_fields=["raw_text"],
        output_fields=[
            OutputFieldSpec(
                name="temporal_events",
                field_type="array<object>",
                description="date, event_description, event_type, participants",
            ),
        ],
        strategy="generative_only",
        generative_config=GenerativeConfig(
            prompt_template="wikipedia_timeline.jinja2",
            max_tokens=1024,
        ),
        platform="wikipedia",
    ),
    # 9. Relations ─────────────────────────────────────────────────────────
    "wikipedia_relations": FieldGroupSpec(
        name="wikipedia_relations",
        description="Related entities with relation types and classified external links",
        required_source_fields=["raw_text"],
        output_fields=[
            OutputFieldSpec(
                name="related_entities",
                field_type="array<object>",
                description="entity, relation_type, bidirectional",
            ),
            OutputFieldSpec(
                name="external_links_classified",
                field_type="array<object>",
                description="url, source_type, reliability_tier",
            ),
            OutputFieldSpec(name="controversy_map", field_type="array<object>"),
        ],
        strategy="generative_only",
        generative_config=GenerativeConfig(
            prompt_template="wikipedia_relations.jinja2",
            max_tokens=2048,
        ),
        platform="wikipedia",
    ),
    # 10. Quality ──────────────────────────────────────────────────────────
    "wikipedia_quality": FieldGroupSpec(
        name="wikipedia_quality",
        description="Article quality class, neutrality score, citation density, edit controversy",
        required_source_fields=["raw_text"],
        output_fields=[
            OutputFieldSpec(name="article_quality_class", field_type="string"),
            OutputFieldSpec(name="neutrality_score", field_type="number"),
            OutputFieldSpec(name="citation_density", field_type="number"),
            OutputFieldSpec(name="last_major_edit", field_type="string"),
            OutputFieldSpec(name="edit_controversy_score", field_type="number"),
            OutputFieldSpec(name="internal_contradictions", field_type="array<object>"),
            OutputFieldSpec(name="article_completeness_assessment", field_type="object"),
            OutputFieldSpec(name="source_diversity_assessment", field_type="object"),
        ],
        strategy="generative_only",
        generative_config=GenerativeConfig(
            prompt_template="wikipedia_quality.jinja2",
            max_tokens=1024,
        ),
        platform="wikipedia",
    ),
    # 11. Multi-lingual ────────────────────────────────────────────────────
    "wikipedia_multi_lingual": FieldGroupSpec(
        name="wikipedia_multi_lingual",
        description="Cross-language links, translation coverage, and entity name translations",
        required_source_fields=["title"],
        output_fields=[
            OutputFieldSpec(name="cross_language_links", field_type="object"),
            OutputFieldSpec(name="translation_coverage_score", field_type="number"),
            OutputFieldSpec(name="entity_name_translations", field_type="object"),
        ],
        strategy="generative_only",
        generative_config=GenerativeConfig(
            prompt_template="wikipedia_multi_lingual.jinja2",
            max_tokens=512,
        ),
        platform="wikipedia",
    ),
    # 12. Embeddings ───────────────────────────────────────────────────────
    "wikipedia_embeddings": FieldGroupSpec(
        name="wikipedia_embeddings",
        description="Vector embeddings for article and individual sections",
        required_source_fields=["raw_text"],
        output_fields=[
            OutputFieldSpec(name="article_embedding", field_type="array<number>"),
            OutputFieldSpec(name="section_embeddings", field_type="array<array<number>>"),
        ],
        strategy="generative_only",
        generative_config=GenerativeConfig(
            prompt_template="wikipedia_embeddings.jinja2",
            max_tokens=16,
        ),
        platform="wikipedia",
    ),
    # 13. Multimodal Images ────────────────────────────────────────────────
    "wikipedia_multimodal_images": FieldGroupSpec(
        name="wikipedia_multimodal_images",
        description="Vision-based image annotation: captions, depicted content, spatial description, historical period",
        required_source_fields=["images"],
        output_fields=[
            OutputFieldSpec(
                name="images_annotated",
                field_type="array<object>",
                description="url, caption_generated, depicts, image_type, spatial_description, historical_period_depicted, scientific_annotation",
            ),
        ],
        strategy="generative_only",
        generative_config=GenerativeConfig(
            prompt_template="wikipedia_multimodal_images.jinja2",
            max_tokens=1024,
        ),
        requires_vision=True,
        platform="wikipedia",
    ),
    # 14. Multi-level Summary ──────────────────────────────────────────────
    "wikipedia_multi_level_summary": FieldGroupSpec(
        name="wikipedia_multi_level_summary",
        description="Multiple summary styles: one-line, ELI5, standard, academic, key takeaways",
        required_source_fields=["raw_text"],
        output_fields=[
            OutputFieldSpec(name="one_line_summary", field_type="string"),
            OutputFieldSpec(name="eli5_summary", field_type="string"),
            OutputFieldSpec(name="standard_summary", field_type="string"),
            OutputFieldSpec(name="academic_summary", field_type="string"),
            OutputFieldSpec(name="key_takeaways", field_type="array<string>"),
        ],
        strategy="generative_only",
        generative_config=GenerativeConfig(
            prompt_template="wikipedia_multi_level_summary.jinja2",
            max_tokens=2048,
        ),
        platform="wikipedia",
    ),
    # 15. Educational ──────────────────────────────────────────────────────
    "wikipedia_educational": FieldGroupSpec(
        name="wikipedia_educational",
        description="Prerequisite concepts, difficulty level, quiz questions, and common misconceptions",
        required_source_fields=["raw_text"],
        output_fields=[
            OutputFieldSpec(
                name="prerequisite_concepts",
                field_type="array<object>",
                description="concept_name, wikipedia_title_hint, why_needed",
            ),
            OutputFieldSpec(name="difficulty_level", field_type="string"),
            OutputFieldSpec(
                name="quiz_questions_generated",
                field_type="array<object>",
                description="question, answer, difficulty, question_type, distractor_answers",
            ),
            OutputFieldSpec(
                name="common_misconceptions",
                field_type="array<object>",
                description="misconception, correction, evidence_from_article",
            ),
        ],
        strategy="generative_only",
        generative_config=GenerativeConfig(
            prompt_template="wikipedia_educational.jinja2",
            max_tokens=3072,
        ),
        platform="wikipedia",
    ),
    # 16. Bias & Neutrality ────────────────────────────────────────────────
    "wikipedia_bias_and_neutrality": FieldGroupSpec(
        name="wikipedia_bias_and_neutrality",
        description="Bias detection, missing perspectives, and weasel word identification",
        required_source_fields=["raw_text"],
        output_fields=[
            OutputFieldSpec(
                name="bias_detection",
                field_type="array<object>",
                description="section_heading, bias_type, evidence_quote_location, severity, suggested_neutral_framing",
            ),
            OutputFieldSpec(name="missing_perspectives", field_type="array<string>"),
            OutputFieldSpec(
                name="weasel_words_detected",
                field_type="array<object>",
                description="phrase, location, issue",
            ),
            OutputFieldSpec(name="citation_needed_gaps", field_type="array<object>"),
        ],
        strategy="generative_only",
        generative_config=GenerativeConfig(
            prompt_template="wikipedia_bias_and_neutrality.jinja2",
            max_tokens=2048,
        ),
        platform="wikipedia",
    ),
    # 17. Content Freshness ────────────────────────────────────────────────
    "wikipedia_content_freshness": FieldGroupSpec(
        name="wikipedia_content_freshness",
        description="Information freshness score, outdated claims detection, and temporal coverage gaps",
        required_source_fields=["raw_text"],
        output_fields=[
            OutputFieldSpec(name="information_freshness_score", field_type="number"),
            OutputFieldSpec(
                name="potentially_outdated_claims",
                field_type="array<object>",
                description="claim, date_context, reason_suspect",
            ),
            OutputFieldSpec(name="temporal_coverage_gap", field_type="string"),
        ],
        strategy="generative_only",
        generative_config=GenerativeConfig(
            prompt_template="wikipedia_content_freshness.jinja2",
            max_tokens=512,
        ),
        platform="wikipedia",
    ),
    # 18. Cross-dataset Linkable IDs ───────────────────────────────────────
    "wikipedia_cross_dataset_linkable_ids": FieldGroupSpec(
        name="wikipedia_cross_dataset_linkable_ids",
        description="Cross-platform identifiers: arXiv paper hints, LinkedIn person hints, Amazon product hints, Base on-chain hints, external DB IDs",
        required_source_fields=["plain_text"],
        output_fields=[
            OutputFieldSpec(
                name="linkable_identifiers",
                field_type="object",
                description="arxiv_paper_hints, linkedin_person_hints, amazon_product_hints, base_onchain_hints, external_database_ids",
            ),
        ],
        strategy="generative_only",
        generative_config=GenerativeConfig(
            prompt_template="wikipedia_cross_dataset_linkable_ids.jinja2",
        ),
        platform="wikipedia",
    ),
}

# ---------------------------------------------------------------------------
# Combined registry for all academic field groups
# ---------------------------------------------------------------------------

ACADEMIC_FIELD_GROUPS: dict[str, FieldGroupSpec] = {
    **ARXIV_BASE_FIELD_GROUPS,
    **WIKIPEDIA_BASE_FIELD_GROUPS,
    **ARXIV_FIELD_GROUPS,
    **WIKIPEDIA_FIELD_GROUPS,
}
