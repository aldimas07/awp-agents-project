from __future__ import annotations

import asyncio
import hashlib
from dataclasses import asdict
import logging
import time
import json
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

from crawler.enrich.extractive.lookup_enricher import LookupEnricher
from crawler.enrich.extractive.regex_enricher import RegexEnricher
from crawler.enrich.generative.llm_client import parse_json_response
from crawler.enrich.generative.llm_enrich import enrich_with_llm, llm_execution_available
from crawler.enrich.generative.prompt_renderer import render_prompt
from crawler.enrich.models import (
    EnrichedField,
    EnrichedRecord,
    ExtractiveResult,
    FieldGroupResult,
    StructuredFields,
)
from crawler.enrich.schemas.field_group_registry import (
    FieldGroupSpec,
    get_field_group_spec,
)
from crawler.schema_runtime import LLMExecutor


class LLMSchemaFieldGroupExecutor:
    def __init__(self, schema_path: Path, model_config: dict[str, Any]):
        self.schema = json.loads(schema_path.read_text(encoding="utf-8"))
        self.executor = LLMExecutor(model_config)

    async def execute(self, payload: dict[str, Any]) -> dict[str, Any]:
        result = await self.executor.execute(
            schema_name=str(self.schema.get("schema_name", "enrich_schema")),
            instruction=str(self.schema.get("instruction", "Extract enrichment fields")),
            payload=payload,
            system_prompt=str(self.schema.get("system_prompt", "Extract only the requested JSON object. Return valid JSON only.")),
        )
        return {
            "success": result.success,
            "data": result.data,
            "error": result.error,
            "schema_name": result.schema_name,
            "output_fields": list(self.schema.get("output_fields", [])),
        }


class EnrichPipeline:
    """Enrichment pipeline: extractive-first, generative with graceful fallback.

    Generative execution prefers the OpenClaw agent CLI.
    If that path is unavailable, it falls back to model-config driven Gateway or
    other OpenAI-compatible APIs. Only when no execution path is available do
    generative field groups remain ``pending_agent`` for later fulfillment.
    """

    def __init__(
        self,
        *,
        enrich_llm_schema_path: Path | None = None,
        model_config: dict[str, Any] | None = None,
        cache_dir: Path | None = None,
    ) -> None:
        self._lookup_cache: dict[str, LookupEnricher] = {}
        self._regex_cache: dict[str, RegexEnricher] = {}
        self._cache_dir = cache_dir
        self._model_config = model_config or {}
        if self._cache_dir is not None:
            self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._llm_schema_executor = (
            LLMSchemaFieldGroupExecutor(enrich_llm_schema_path, self._model_config)
            if enrich_llm_schema_path is not None
            else None
        )

    def _get_lookup_enricher(self, table_path: str) -> LookupEnricher:
        if table_path not in self._lookup_cache:
            self._lookup_cache[table_path] = LookupEnricher(table_path)
        return self._lookup_cache[table_path]

    def _get_regex_enricher(self, patterns_file: str) -> RegexEnricher:
        if patterns_file not in self._regex_cache:
            self._regex_cache[patterns_file] = RegexEnricher(patterns_file)
        return self._regex_cache[patterns_file]

    async def enrich(
        self,
        document: dict[str, Any],
        field_groups: list[str],
        model_capabilities: dict[str, bool] | None = None,
    ) -> EnrichedRecord:
        """Enrich a document across requested field groups.

        For each field group:
        1. Check if model capabilities match (e.g., vision for multimodal)
        2. Check if required source fields are present
        3. Run extractive enrichment (lookup/regex) — zero cost, instant
        4. If generative is needed, return ``pending_agent`` with prompt

        Args:
            document: The document to enrich.
            field_groups: List of field group names to apply.
            model_capabilities: Optional dict indicating model capabilities.
                - "vision": bool - whether the model supports image analysis.
                If a field group requires vision but model doesn't support it,
                the group will be skipped with an informative message.
        """
        model_capabilities = model_capabilities or {}
        record = EnrichedRecord(
            doc_id=document.get("doc_id", document.get("canonical_url", "")),
            source_url=document.get("canonical_url", ""),
            platform=document.get("platform", "unknown"),
            resource_type=document.get("resource_type", document.get("entity_type", "unknown")),
            structured=StructuredFields(fields=document.get("structured", {}) if isinstance(document.get("structured"), dict) else (document.get("structured").platform_fields if hasattr(document.get("structured"), "platform_fields") else {})),
        )

        # First pass: synchronously handle cache hits, unknown groups, llm_schema, and extractive field groups.
        # Generative field groups that need LLM are collected and executed in parallel afterwards.
        deferred_specs: list[FieldGroupSpec] = []

        for group_name in field_groups:
            cached = self._read_cached_result(document, group_name)
            if cached is not None:
                record.merge_field_group_result(cached)
                continue
            if group_name == "llm_schema" and self._llm_schema_executor is not None:
                result = await self._run_llm_schema_group(document)
                self._write_cached_result(document, result)
                record.merge_field_group_result(result)
                continue
            spec = get_field_group_spec(group_name)
            if spec is None:
                result = FieldGroupResult(
                    field_group=group_name,
                    status="skipped",
                    error=f"unknown field group: {group_name}",
                )
                self._write_cached_result(document, result)
                record.merge_field_group_result(result)
                continue

            if spec.strategy in ("generative_only", "extractive_then_generative"):
                deferred_specs.append(spec)
            else:
                result = await self._run_field_group(spec, document, model_capabilities)
                self._write_cached_result(document, result)
                record.merge_field_group_result(result)

        # Second pass: merge all generative field groups into ONE LLM call.
        # Previously each group made its own LLM call — for arXiv that meant
        # ~10 calls, each sending the full paper text. Now we build a single
        # combined prompt listing all output fields, make one call, and split
        # the result. This is 10x faster and uses 10x fewer tokens.
        if deferred_specs:
            if llm_execution_available(self._model_config):
                merged_results = await self._run_generative_merged(
                    deferred_specs, document, model_capabilities,
                )
                for result in merged_results:
                    self._write_cached_result(document, result)
                    record.merge_field_group_result(result)
            else:
                # No LLM backend — return pending_agent for each group
                for spec in deferred_specs:
                    source_fields = self._collect_source_fields(spec, document)
                    gen_config = spec.generative_config
                    if gen_config is None:
                        result = FieldGroupResult(
                            field_group=spec.name,
                            status="failed",
                            error="generative strategy but no generative_config",
                        )
                    else:
                        prompt = render_prompt(
                            gen_config.prompt_template,
                            source_fields,
                            output_fields=spec.output_fields,
                            field_group_name=spec.name,
                            field_group_description=spec.description,
                        )
                        result = FieldGroupResult(
                            field_group=spec.name,
                            status="pending_agent",
                            agent_prompt=prompt,
                            agent_system_prompt=gen_config.system_prompt,
                            output_fields=[f.name for f in spec.output_fields],
                        )
                    self._write_cached_result(document, result)
                    record.merge_field_group_result(result)

        return record

    async def _run_llm_schema_group(self, document: dict[str, Any]) -> FieldGroupResult:
        start = time.monotonic()
        if self._llm_schema_executor is None:
            return FieldGroupResult(
                field_group="llm_schema",
                status="failed",
                error="llm schema executor not configured",
                latency_ms=int((time.monotonic() - start) * 1000),
            )

        result = await self._llm_schema_executor.execute(document)
        if not result.get("success"):
            return FieldGroupResult(
                field_group="llm_schema",
                status="failed",
                error=result.get("error", "llm schema execution failed"),
                latency_ms=int((time.monotonic() - start) * 1000),
            )

        schema_name = str(result.get("schema_name", "enrich_schema"))
        output_fields = result.get("output_fields") or list(result.get("data", {}).keys())
        data = result.get("data", {})
        fields = [
            EnrichedField(
                field_name=field_name,
                value=data.get(field_name),
                source_type="generative",
                source_details=f"llm_schema:{schema_name}",
                confidence=0.8 if data.get(field_name) is not None else 0.0,
                evidence=["llm_schema"],
            )
            for field_name in output_fields
        ]
        return FieldGroupResult(
            field_group="llm_schema",
            status="success",
            fields=fields,
            latency_ms=int((time.monotonic() - start) * 1000),
        )

    async def _run_field_group(
        self,
        spec: FieldGroupSpec,
        document: dict[str, Any],
        model_capabilities: dict[str, bool] | None = None,
    ) -> FieldGroupResult:
        """Execute a single field group according to its strategy."""
        start = time.monotonic()
        model_capabilities = model_capabilities or {}

        # Check vision capability for multimodal field groups
        if spec.requires_vision and not model_capabilities.get("vision", False):
            return FieldGroupResult(
                field_group=spec.name,
                status="skipped",
                error="Vision required but model lacks vision capability (requires_vision=True)",
                latency_ms=int((time.monotonic() - start) * 1000),
            )

        source_fields = self._collect_source_fields(spec, document)

        # Check required source fields
        if spec.required_source_fields and not spec.source_fields_present(document):
            return FieldGroupResult(
                field_group=spec.name,
                status="skipped",
                error=self._build_missing_source_error(spec, document),
                latency_ms=int((time.monotonic() - start) * 1000),
            )

        strategy = spec.strategy

        if strategy == "passthrough":
            return self._run_passthrough(spec, document, start)

        # ── Step 1: Run extractive if applicable ──
        if strategy in ("extractive_only", "extractive_then_generative"):
            extractive_result = self._run_extractive(spec, source_fields)

            if extractive_result.matched and extractive_result.confidence >= spec.min_extractive_confidence:
                fields = self._extractive_to_fields(spec, extractive_result)
                return FieldGroupResult(
                    field_group=spec.name,
                    status="success",
                    fields=fields,
                    latency_ms=int((time.monotonic() - start) * 1000),
                )

            if strategy == "extractive_only":
                if extractive_result.matched:
                    fields = self._extractive_to_fields(spec, extractive_result)
                    return FieldGroupResult(
                        field_group=spec.name,
                        status="partial",
                        fields=fields,
                        latency_ms=int((time.monotonic() - start) * 1000),
                    )
                return FieldGroupResult(
                    field_group=spec.name,
                    status="failed",
                    error="no extractive match found",
                    latency_ms=int((time.monotonic() - start) * 1000),
                )

        # ── Step 2: Generative needed → return pending_agent for agent execution ──
        if strategy in ("generative_only", "extractive_then_generative"):
            if spec.generative_config is None:
                return FieldGroupResult(
                    field_group=spec.name,
                    status="failed",
                    error="generative strategy but no generative_config",
                    latency_ms=int((time.monotonic() - start) * 1000),
                )

            gen_config = spec.generative_config
            prompt = render_prompt(
                gen_config.prompt_template,
                source_fields,
                output_fields=spec.output_fields,
                field_group_name=spec.name,
                field_group_description=spec.description,
            )
            if llm_execution_available(self._model_config):
                return await self._run_generative(spec, prompt, gen_config.system_prompt, start, document)
            return FieldGroupResult(
                field_group=spec.name,
                status="pending_agent",
                agent_prompt=prompt,
                agent_system_prompt=gen_config.system_prompt,
                output_fields=[f.name for f in spec.output_fields],
                latency_ms=int((time.monotonic() - start) * 1000),
            )

        return FieldGroupResult(
            field_group=spec.name,
            status="failed",
            error=f"unknown strategy: {strategy}",
            latency_ms=int((time.monotonic() - start) * 1000),
        )

    async def _run_generative(
        self,
        spec: FieldGroupSpec,
        prompt: str,
        system_prompt: str | None,
        start: float,
        document: dict[str, Any] | None = None,
    ) -> FieldGroupResult:
        max_tokens = (spec.generative_config.max_tokens if spec.generative_config else 512) or 512
        base_timeout = float(self._model_config.get("timeout", 120.0) or 120.0)
        timeout = max(base_timeout, max_tokens * 0.05 + 30)
        try:
            response = await enrich_with_llm(
                prompt,
                model_config=self._model_config or None,
                system_prompt=system_prompt or "",
                timeout=timeout,
            )
        except Exception as exc:
            return FieldGroupResult(
                field_group=spec.name,
                status="failed",
                error=str(exc),
                latency_ms=int((time.monotonic() - start) * 1000),
            )

        if not response.success:
            return FieldGroupResult(
                field_group=spec.name,
                status="failed",
                error=response.error or "llm enrich failed",
                latency_ms=int((time.monotonic() - start) * 1000),
            )

        source_details = f"llm:{response.method}"
        if response.model:
            source_details = f"{source_details}:{response.model}"
        result = self.fill_pending_agent_result(
            spec.name,
            response.content,
            document=document,
            source_details=source_details,
            model_used=response.model,
            tokens_used=response.tokens_used or None,
            evidence=[f"llm_{response.method}"],
        )
        result.latency_ms = int((time.monotonic() - start) * 1000)
        return result

    async def _run_generative_merged(
        self,
        specs: list[FieldGroupSpec],
        document: dict[str, Any],
        model_capabilities: dict[str, bool] | None = None,
    ) -> list[FieldGroupResult]:
        """Run all generative field groups in ONE LLM call.

        Builds a single prompt that lists every output field from every
        generative spec, sends the document text once, and asks the LLM to
        return a flat JSON object with all fields. The response is then split
        back into per-group FieldGroupResults.

        This replaces the old approach of N independent calls — each resending
        the full document. For arXiv (10+ generative groups) this is ~10x
        faster and uses ~10x fewer tokens.
        """
        start = time.monotonic()
        model_capabilities = model_capabilities or {}

        # Filter specs: skip vision-required groups when model lacks vision,
        # skip specs with missing source fields.
        eligible: list[FieldGroupSpec] = []
        skipped_results: list[FieldGroupResult] = []
        for spec in specs:
            if spec.requires_vision and not model_capabilities.get("vision", False):
                skipped_results.append(FieldGroupResult(
                    field_group=spec.name,
                    status="skipped",
                    error="Vision required but model lacks vision capability",
                ))
                continue
            if spec.required_source_fields and not spec.source_fields_present(document):
                skipped_results.append(FieldGroupResult(
                    field_group=spec.name,
                    status="skipped",
                    error=self._build_missing_source_error(spec, document),
                ))
                continue
            if spec.generative_config is None:
                skipped_results.append(FieldGroupResult(
                    field_group=spec.name,
                    status="failed",
                    error="generative strategy but no generative_config",
                ))
                continue
            eligible.append(spec)

        if not eligible:
            return skipped_results

        # Collect source fields once using a synthetic spec that unions all
        # required_source_fields — avoids calling _collect_source_fields N times.
        all_required: list[str] = []
        seen_fields: set[str] = set()
        for spec in eligible:
            for f in spec.required_source_fields:
                if f not in seen_fields:
                    seen_fields.add(f)
                    all_required.append(f)
        union_spec = FieldGroupSpec(
            name="_merged", description="", required_source_fields=all_required,
            output_fields=[], strategy="generative_only",
        )
        source_fields = self._collect_source_fields(union_spec, document)

        # Build combined output schema — one flat object with all fields,
        # keyed by "{group_name}.{field_name}" to avoid collisions.
        combined_schema: dict[str, Any] = {}
        group_field_map: dict[str, list[str]] = {}  # group → [qualified_keys]
        for spec in eligible:
            qualified_keys: list[str] = []
            for f in spec.output_fields:
                qualified_key = f"{spec.name}.{f.name}"
                combined_schema[qualified_key] = {
                    "type": f.field_type,
                    "description": f.description or f.name,
                }
                qualified_keys.append(qualified_key)
            group_field_map[spec.name] = qualified_keys

        # Build the prompt
        parts = [
            "You are an expert data enrichment engine. Given the source document "
            "below, generate ALL the requested output fields in a single JSON object.",
            "",
            "## Source document",
        ]
        for key, value in source_fields.items():
            text = str(value)
            if len(text) > self._MAX_TEXT_CHARS:
                text = text[:self._MAX_TEXT_CHARS] + f"\n[... truncated at {self._MAX_TEXT_CHARS} chars ...]"
            parts.append(f"### {key}")
            parts.append(text)
            parts.append("")

        parts.append("## Output schema (generate ALL of these fields)")
        parts.append(json.dumps(combined_schema, ensure_ascii=False, indent=2))
        parts.append("")
        parts.append("## Instructions")
        parts.append("- Return valid JSON only, no markdown fences, no commentary.")
        parts.append("- Use exactly the field names shown above (format: group_name.field_name).")
        parts.append("- If a field cannot be determined, return null, [] or {} as appropriate.")
        parts.append("- Do not add extra keys.")

        prompt = "\n".join(parts)

        # Sum up max_tokens from all specs for the combined response
        total_max_tokens = sum(
            (spec.generative_config.max_tokens if spec.generative_config else 512) or 512
            for spec in eligible
        )
        # Cap to avoid unreasonable values, but allow generous budget
        total_max_tokens = min(total_max_tokens, 8192)
        base_timeout = float(self._model_config.get("timeout", 120.0) or 120.0)
        timeout = max(base_timeout, total_max_tokens * 0.05 + 60)

        try:
            response = await enrich_with_llm(
                prompt,
                model_config=self._model_config or None,
                system_prompt=(
                    "You generate concise structured enrichment values from source "
                    "fields. Return only the requested JSON output, no extra commentary."
                ),
                timeout=timeout,
            )
        except Exception as exc:
            logger.warning("Merged generative enrich failed: %s", exc)
            return skipped_results + [
                FieldGroupResult(
                    field_group=spec.name,
                    status="failed",
                    error=str(exc),
                    latency_ms=int((time.monotonic() - start) * 1000),
                )
                for spec in eligible
            ]

        if not response.success:
            logger.warning("Merged generative enrich LLM error: %s", response.error)
            return skipped_results + [
                FieldGroupResult(
                    field_group=spec.name,
                    status="failed",
                    error=response.error or "merged llm enrich failed",
                    latency_ms=int((time.monotonic() - start) * 1000),
                )
                for spec in eligible
            ]

        # Parse the combined response
        parsed = parse_json_response(response.content)
        if not isinstance(parsed, dict) or "raw" in parsed:
            logger.warning("Merged enrich: could not parse JSON from LLM response")
            return skipped_results + [
                FieldGroupResult(
                    field_group=spec.name,
                    status="failed",
                    error="invalid JSON from merged LLM response",
                    latency_ms=int((time.monotonic() - start) * 1000),
                )
                for spec in eligible
            ]

        source_details = f"llm:{response.method}"
        if response.model:
            source_details = f"{source_details}:{response.model}"
        field_evidence = [f"llm_{response.method}_merged"]
        latency = int((time.monotonic() - start) * 1000)

        # Split the flat response back into per-group results
        group_results: list[FieldGroupResult] = []
        for spec in eligible:
            fields: list[EnrichedField] = []
            for output_spec in spec.output_fields:
                qualified_key = f"{spec.name}.{output_spec.name}"
                # Try qualified key first, fall back to bare field name
                value = parsed.get(qualified_key, parsed.get(output_spec.name))
                fields.append(EnrichedField(
                    field_name=output_spec.name,
                    value=value,
                    source_type="generative",
                    source_details=source_details,
                    confidence=0.8 if value is not None else 0.0,
                    evidence=field_evidence,
                    model_used=response.model,
                    tokens_used=response.tokens_used or None,
                ))
            group_results.append(FieldGroupResult(
                field_group=spec.name,
                status="success" if any(f.value is not None for f in fields) else "empty",
                fields=fields,
                latency_ms=latency,
            ))

        logger.info(
            "Merged generative enrich: %d groups in 1 LLM call, %dms",
            len(eligible), latency,
        )
        return skipped_results + group_results

    # Max chars for large text fields to avoid exceeding LLM context
    _MAX_TEXT_CHARS = 30_000

    def _collect_source_fields(self, spec: FieldGroupSpec, document: dict[str, Any]) -> dict[str, Any]:
        """Collect all relevant source fields from the document."""
        source: dict[str, Any] = {}
        for field_name in spec.required_source_fields:
            value = document.get(field_name)
            if value is not None and value != "" and value != [] and value != {}:
                source[field_name] = value
        # plain_text and markdown overlap; keep one to save tokens
        text_key = "plain_text" if document.get("plain_text") else "markdown"
        for key in (text_key, "title", "summary", "headline", "about", "description"):
            if key not in source and key in document:
                value = document[key]
                if value is not None and value != "" and value != [] and value != {}:
                    source[key] = value
        # Truncate very long text to avoid prompt overflow
        for key in ("plain_text", "markdown", "raw_text", "HTML"):
            if key in source and isinstance(source[key], str) and len(source[key]) > self._MAX_TEXT_CHARS:
                source[key] = source[key][:self._MAX_TEXT_CHARS] + f"\n\n[... truncated at {self._MAX_TEXT_CHARS} chars ...]"
        return source

    @staticmethod
    def _build_missing_source_error(spec: FieldGroupSpec, document: dict[str, Any]) -> str:
        if spec.platform == "amazon" and spec.subdataset == "products" and "price" in spec.required_source_fields:
            availability = str(document.get("availability") or "")
            # Include CN/JP out-of-stock phrases for localized Amazon pages
            if re.search(r"unavailable|out of stock|currently unavailable|目前无货|無貨", availability, re.IGNORECASE):
                if spec.name == "amazon_products_pricing":
                    return "pricing unavailable on source page (product unavailable or no offer data)"
                return "price-dependent analysis unavailable on source page (product unavailable or no offer data)"
        return f"missing required source fields: {spec.required_source_fields}"

    def _run_extractive(self, spec: FieldGroupSpec, source_fields: dict[str, Any]) -> ExtractiveResult:
        """Run the extractive enrichment step."""
        if spec.extractive_config is None:
            return ExtractiveResult(matched=False)

        config = spec.extractive_config
        if config.extractor_type == "lookup" and config.lookup_table:
            enricher = self._get_lookup_enricher(config.lookup_table)
            return enricher.enrich(source_fields, config.source_field_key)
        elif config.extractor_type == "regex" and config.patterns_file:
            enricher = self._get_regex_enricher(config.patterns_file)
            return enricher.enrich(source_fields, config.source_field_key)

        return ExtractiveResult(matched=False)

    @staticmethod
    def _extractive_to_fields(spec: FieldGroupSpec, result: ExtractiveResult) -> list[EnrichedField]:
        """Convert an ExtractiveResult into EnrichedField list."""
        fields = []
        for output_spec in spec.output_fields:
            value = result.values.get(output_spec.name)
            if value is None:
                if "extracted_items" in result.values and output_spec.field_type.startswith("array"):
                    value = result.values["extracted_items"]
                elif "categories" in result.values and "categor" in output_spec.name:
                    value = result.values["categories"]
                elif "value" in result.values:
                    value = result.values["value"]
                elif result.values:
                    value = next(iter(result.values.values()))
            fields.append(
                EnrichedField(
                    field_name=output_spec.name,
                    value=value,
                    source_type="lookup" if "lookup" in result.source_details else "extractive",
                    source_details=result.source_details,
                    confidence=result.confidence,
                    evidence=result.evidence,
                )
            )
        return fields

    @staticmethod
    def _run_passthrough(spec: FieldGroupSpec, document: dict[str, Any], start: float) -> FieldGroupResult:
        config = spec.passthrough_config
        if config is None:
            return FieldGroupResult(
                field_group=spec.name,
                status="failed",
                error="passthrough strategy but no passthrough_config",
                latency_ms=int((time.monotonic() - start) * 1000),
            )

        for source_field in config.source_fields:
            value = document.get(source_field)
            if value not in (None, "", [], {}, ()):
                return FieldGroupResult(
                    field_group=spec.name,
                    status="success",
                    fields=[
                        EnrichedField(
                            field_name=config.output_field,
                            value=value,
                            source_type="passthrough",
                            source_details=f"passthrough:{source_field}",
                            confidence=0.6,
                            evidence=[source_field],
                        )
                    ],
                    latency_ms=int((time.monotonic() - start) * 1000),
                )

        return FieldGroupResult(
            field_group=spec.name,
            status="skipped",
            error=f"no routable source fields for {spec.name}",
            latency_ms=int((time.monotonic() - start) * 1000),
        )

    def fill_pending_agent_result(
        self,
        field_group: str,
        llm_response_text: str,
        document: dict[str, Any] | None = None,
        *,
        source_details: str = "agent:claude",
        model_used: str | None = None,
        tokens_used: int | None = None,
        evidence: list[str] | None = None,
    ) -> FieldGroupResult:
        """Fill a pending_agent result with the LLM response from agent execution.

        Called by the agent after it executes the prompt itself.
        """
        spec = get_field_group_spec(field_group)
        if spec is None:
            return FieldGroupResult(
                field_group=field_group,
                status="failed",
                error=f"unknown field group: {field_group}",
            )

        parsed = parse_json_response(llm_response_text)
        if not isinstance(parsed, dict) or "raw" in parsed:
            result = FieldGroupResult(
                field_group=field_group,
                status="failed",
                fields=[
                    EnrichedField(
                        field_name=output_spec.name,
                        value=None,
                        source_type="generative",
                        source_details=source_details,
                        confidence=0.0,
                        evidence=evidence or ["agent_executed"],
                        model_used=model_used,
                        tokens_used=tokens_used,
                    )
                    for output_spec in spec.output_fields
                ],
                error="invalid JSON response from agent",
            )
            if document is not None:
                self._write_cached_result(document, result)
            return result

        fields = []
        parsed_dict = parsed
        field_evidence = evidence or ["agent_executed"]

        for output_spec in spec.output_fields:
            value = parsed_dict.get(output_spec.name)
            fields.append(
                EnrichedField(
                    field_name=output_spec.name,
                    value=value,
                    source_type="generative",
                    source_details=source_details,
                    confidence=0.8 if value is not None else 0.0,
                    evidence=field_evidence,
                    model_used=model_used,
                    tokens_used=tokens_used,
                )
            )

        result = FieldGroupResult(
            field_group=field_group,
            status="success" if any(f.value is not None for f in fields) else "empty",
            fields=fields,
        )
        if document is not None:
            self._write_cached_result(document, result)
        return result

    def _read_cached_result(self, document: dict[str, Any], field_group: str) -> FieldGroupResult | None:
        if self._cache_dir is None:
            return None
        path = self._cache_path(document, field_group)
        if not path.exists():
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
        return FieldGroupResult(
            field_group=payload["field_group"],
            status=payload["status"],
            fields=[EnrichedField(**field) for field in payload.get("fields", [])],
            error=payload.get("error"),
            latency_ms=int(payload.get("latency_ms", 0)),
            cost_usd=payload.get("cost_usd"),
            agent_prompt=payload.get("agent_prompt"),
            agent_system_prompt=payload.get("agent_system_prompt"),
            output_fields=list(payload.get("output_fields", [])),
        )

    def _write_cached_result(self, document: dict[str, Any], result: FieldGroupResult) -> None:
        if self._cache_dir is None:
            return
        if result.status in {"failed", "skipped", "pending_agent"}:
            return
        # Cache "empty" results (LLM legitimately found no data) to avoid re-enrichment
        if result.status == "empty":
            pass  # allow caching
        elif any(f.value is None for f in result.fields):
            return  # partial results — don't cache to allow re-extraction
        try:
            self._cache_path(document, result.field_group).write_text(
                json.dumps(result.to_dict(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError as exc:
            logger.warning("Failed to write enrichment cache for %s: %s", result.field_group, exc)

    def _cache_path(self, document: dict[str, Any], field_group: str) -> Path:
        payload = {
            "field_group": field_group,
            "canonical_url": document.get("canonical_url"),
            "platform": document.get("platform"),
            "resource_type": document.get("resource_type", document.get("entity_type")),
            "plain_text": document.get("plain_text"),
            "markdown": document.get("markdown"),
            "structured": document.get("structured"),
            "config_identity": self._cache_config_identity(field_group),
        }
        digest = hashlib.sha256(
            json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")
        ).hexdigest()
        return self._cache_dir / f"{digest}.json"

    def _cache_config_identity(self, field_group: str) -> dict[str, Any]:
        identity: dict[str, Any] = {
            "model_config": {
                key: self._model_config.get(key)
                for key in ("base_url", "provider", "model", "openclaw_model", "max_tokens", "temperature", "timeout")
                if key in self._model_config
            }
        }

        spec = get_field_group_spec(field_group)
        if spec is not None:
            identity["field_group_spec"] = asdict(spec)

        if field_group == "llm_schema" and self._llm_schema_executor is not None:
            identity["llm_schema"] = self._llm_schema_executor.schema

        return identity
