from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass(slots=True)
class EnrichedField:
    """A single enriched field with provenance tracking."""

    field_name: str
    value: Any
    source_type: Literal["extractive", "generative", "lookup", "passthrough"]
    source_details: str
    confidence: float
    evidence: list[str] = field(default_factory=list)
    prompt_template: str | None = None
    model_used: str | None = None
    tokens_used: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "field_name": self.field_name,
            "value": self.value,
            "source_type": self.source_type,
            "source_details": self.source_details,
            "confidence": self.confidence,
            "evidence": self.evidence,
            "prompt_template": self.prompt_template,
            "model_used": self.model_used,
            "tokens_used": self.tokens_used,
        }


@dataclass(slots=True)
class FieldGroupResult:
    """Result of enriching a single field group.

    Status values:
    - success: All fields enriched successfully
    - partial: Some fields enriched, others failed
    - failed: Enrichment failed
    - skipped: Missing required source fields
    - pending_agent: Needs LLM but no API configured; prompt provided for agent execution
    """

    field_group: str
    status: Literal["success", "partial", "failed", "skipped", "pending_agent", "completed"]
    fields: list[EnrichedField] = field(default_factory=list)
    error: str | None = None
    latency_ms: int = 0
    cost_usd: float | None = None
    agent_prompt: str | None = None
    agent_system_prompt: str | None = None
    agent_response: str | None = None
    output_fields: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "field_group": self.field_group,
            "status": self.status,
            "fields": [f.to_dict() for f in self.fields],
            "error": self.error,
            "latency_ms": self.latency_ms,
            "cost_usd": self.cost_usd,
        }
        if self.status in ("pending_agent", "completed"):
            result["agent_prompt"] = self.agent_prompt
            result["agent_system_prompt"] = self.agent_system_prompt
            result["output_fields"] = self.output_fields
        if self.agent_response is not None:
            result["agent_response"] = self.agent_response
        return result


@dataclass(slots=True)
class ContentChunk:
    """A chunk of content from the source document."""

    chunk_id: str
    text: str
    chunk_type: str = "text"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class StructuredFields:
    """Structured fields extracted from a document."""

    fields: dict[str, Any] = field(default_factory=dict)

    def get(self, key: str, default: Any = None) -> Any:
        return self.fields.get(key, default)


@dataclass(slots=True)
class EnrichedRecord:
    """Complete enriched record combining source data with enrichment results."""

    doc_id: str
    source_url: str
    platform: str
    resource_type: str
    chunks: list[ContentChunk] = field(default_factory=list)
    structured: StructuredFields = field(default_factory=StructuredFields)
    enrichment_results: dict[str, FieldGroupResult] = field(default_factory=dict)
    enriched_fields: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "doc_id": self.doc_id,
            "source_url": self.source_url,
            "platform": self.platform,
            "resource_type": self.resource_type,
            "enrichment_results": {
                k: v.to_dict() for k, v in self.enrichment_results.items()
            },
            "enriched_fields": self.enriched_fields,
        }

    def merge_field_group_result(self, result: FieldGroupResult) -> None:
        """Merge a FieldGroupResult into this record."""
        self.enrichment_results[result.field_group] = result
        for enriched_field in result.fields:
            if enriched_field.value is not None:
                self.enriched_fields[enriched_field.field_name] = enriched_field.value


@dataclass(frozen=True, slots=True)
class ExtractiveResult:
    """Result from an extractive enricher (lookup or regex)."""

    matched: bool
    values: dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.0
    evidence: list[str] = field(default_factory=list)
    source_details: str = ""


@dataclass(frozen=True, slots=True)
class LLMResponse:
    """Response from an LLM call."""

    content: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0

    @property
    def tokens_used(self) -> int:
        return self.total_tokens
