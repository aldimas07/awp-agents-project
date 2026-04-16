"""AI enrichment helpers.

Layer 3: Enrich Pipeline

Components:
- models: EnrichedField, FieldGroupResult, EnrichedRecord, ExtractiveResult, LLMResponse
- schemas/field_group_registry: FieldGroupSpec, FIELD_GROUP_REGISTRY
- extractive/lookup_enricher: LookupEnricher
- extractive/regex_enricher: RegexEnricher
- generative/llm_client: LLMClient
- generative/prompt_renderer: render_prompt
- batch/async_executor: BatchEnrichmentExecutor
- pipeline: EnrichPipeline
- agent_executor: AgentEnrichmentExecutor, enrich_with_llm (Agent Integration Layer)
"""
