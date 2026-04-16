from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass(frozen=True, slots=True)
class OutputFieldSpec:
    """Specification for one output field of a field group."""

    name: str
    field_type: str = "string"
    description: str = ""
    required: bool = True


@dataclass(frozen=True, slots=True)
class ExtractiveConfig:
    """Configuration for the extractive enrichment step."""

    extractor_type: Literal["lookup", "regex"]
    lookup_table: str | None = None
    patterns_file: str | None = None
    source_field_key: str | None = None
    min_confidence: float = 0.8


@dataclass(frozen=True, slots=True)
class GenerativeConfig:
    """Configuration for the generative enrichment step."""

    prompt_template: str
    model: str = ""
    max_tokens: int = 512
    temperature: float = 0.2
    system_prompt: str = "You generate concise structured enrichment values from source fields. Return only the requested output, no extra commentary."


@dataclass(frozen=True, slots=True)
class PassthroughConfig:
    """Configuration for lightweight field groups that reuse existing fields."""

    source_fields: list[str]
    output_field: str


@dataclass(frozen=True, slots=True)
class FieldGroupSpec:
    """Complete specification for a field group."""

    name: str
    description: str
    required_source_fields: list[str]
    output_fields: list[OutputFieldSpec]
    strategy: Literal["extractive_only", "generative_only", "extractive_then_generative", "passthrough"]
    extractive_config: ExtractiveConfig | None = None
    generative_config: GenerativeConfig | None = None
    passthrough_config: PassthroughConfig | None = None
    min_extractive_confidence: float = 0.8
    # Optional flags
    requires_vision: bool = False  # Whether the model needs vision (multimodal)
    platform: str = ""  # Target platform: linkedin, arxiv, wikipedia, amazon, base
    subdataset: str = ""  # Sub-dataset: profiles, company, jobs, posts, products, reviews, sellers, transactions, addresses, contracts, defi
    auto_platforms: tuple[str, ...] = field(default_factory=tuple)
    auto_resource_types: tuple[str, ...] = field(default_factory=tuple)

    def source_fields_present(self, record: dict[str, Any]) -> bool:
        """Check if the required source fields are present in the record."""
        for field_name in self.required_source_fields:
            value = record.get(field_name)
            if value is None or value == "" or value == [] or value == {}:
                return False
        return True

    def applies_to(self, platform: str, resource_type: str) -> bool:
        normalized_platform = (platform or "").strip().lower()
        normalized_resource_type = (resource_type or "").strip().lower()

        if self.platform and normalized_platform and self.platform.lower() != normalized_platform:
            return False
        if self.subdataset and normalized_resource_type and self.subdataset.lower() != normalized_resource_type:
            return False
        if self.auto_platforms and normalized_platform and normalized_platform not in {value.lower() for value in self.auto_platforms}:
            return False
        if self.auto_resource_types and normalized_resource_type and normalized_resource_type not in {
            value.lower() for value in self.auto_resource_types
        }:
            return False
        return True


# Import platform-specific field groups
from crawler.enrich.schemas.linkedin_field_groups import LINKEDIN_FIELD_GROUPS
from crawler.enrich.schemas.academic_field_groups import ACADEMIC_FIELD_GROUPS
from crawler.enrich.schemas.amazon_field_groups import AMAZON_FIELD_GROUPS
from crawler.enrich.schemas.base_field_groups import BASE_FIELD_GROUPS


# Legacy/generic field groups (kept for backward compatibility)
_LEGACY_FIELD_GROUPS: dict[str, FieldGroupSpec] = {
    "about_summary": FieldGroupSpec(
        name="about_summary",
        description="Generate a concise professional summary from the about/bio section",
        required_source_fields=["about", "headline"],
        output_fields=[
            OutputFieldSpec(name="about_summary", field_type="string", description="Concise professional summary"),
            OutputFieldSpec(name="about_topics", field_type="array<string>", description="Key topics mentioned"),
            OutputFieldSpec(name="about_sentiment", field_type="string", description="Overall sentiment of about section"),
        ],
        strategy="generative_only",
        generative_config=GenerativeConfig(
            prompt_template="about_summary.jinja2",
            max_tokens=512,
            temperature=0.2,
        ),
        auto_platforms=("linkedin",),
        auto_resource_types=("profile", "company"),
    ),
    "standardized_job_title": FieldGroupSpec(
        name="standardized_job_title",
        description="Standardize job titles using O*NET-SOC taxonomy with lookup then LLM fallback",
        required_source_fields=["headline"],
        output_fields=[
            OutputFieldSpec(name="standardized_job_title", field_type="string", description="O*NET standardized title"),
            OutputFieldSpec(name="seniority_level", field_type="string", description="Inferred seniority level"),
            OutputFieldSpec(name="job_function_category", field_type="string", description="Broad function category"),
        ],
        strategy="extractive_then_generative",
        extractive_config=ExtractiveConfig(
            extractor_type="lookup",
            lookup_table="onet_job_mapping.json",
            source_field_key="headline",
            min_confidence=0.8,
        ),
        generative_config=GenerativeConfig(
            prompt_template="job_standardization.jinja2",
            max_tokens=256,
            temperature=0.1,
        ),
        min_extractive_confidence=0.8,
        auto_platforms=("linkedin",),
        auto_resource_types=("job",),
    ),
    "skills_extraction": FieldGroupSpec(
        name="skills_extraction",
        description="Extract and categorize skills from profile text using patterns then LLM",
        required_source_fields=["plain_text"],
        output_fields=[
            OutputFieldSpec(name="skills_extracted", field_type="array<string>", description="Extracted skill names"),
            OutputFieldSpec(name="skill_categories", field_type="array<string>", description="Skill category labels"),
        ],
        strategy="extractive_then_generative",
        extractive_config=ExtractiveConfig(
            extractor_type="regex",
            patterns_file="skill_patterns.json",
            source_field_key="plain_text",
            min_confidence=0.7,
        ),
        generative_config=GenerativeConfig(
            prompt_template="skills_extraction.jinja2",
            max_tokens=512,
            temperature=0.2,
        ),
        min_extractive_confidence=0.7,
        auto_platforms=("linkedin",),
        auto_resource_types=("profile",),
    ),
    "summaries": FieldGroupSpec(
        name="summaries",
        description="Produce a concise factual summary from available text fields",
        required_source_fields=[],
        output_fields=[
            OutputFieldSpec(name="summary", field_type="string", description="Concise factual summary"),
        ],
        strategy="generative_only",
        generative_config=GenerativeConfig(
            prompt_template="summaries.jinja2",
            max_tokens=512,
            temperature=0.2,
        ),
        auto_platforms=("generic",),
        auto_resource_types=("page",),
    ),
    "classifications": FieldGroupSpec(
        name="classifications",
        description="Classify the record into the most specific category",
        required_source_fields=[],
        output_fields=[
            OutputFieldSpec(name="classification", field_type="string", description="Category classification"),
        ],
        strategy="extractive_only",
        extractive_config=ExtractiveConfig(
            extractor_type="lookup",
            lookup_table="onet_job_mapping.json",
            source_field_key="resource_type",
            min_confidence=0.5,
        ),
        auto_platforms=("generic",),
        auto_resource_types=("page",),
    ),
    "linkables": FieldGroupSpec(
        name="linkables",
        description="Return the strongest cross-system identifier for the record",
        required_source_fields=[],
        output_fields=[
            OutputFieldSpec(name="linkable_identifier", field_type="string", description="Cross-system identifier"),
        ],
        strategy="extractive_only",
        extractive_config=ExtractiveConfig(
            extractor_type="regex",
            patterns_file="skill_patterns.json",
            source_field_key="canonical_url",
            min_confidence=0.9,
        ),
        auto_platforms=("linkedin", "amazon", "arxiv", "wikipedia", "base"),
    ),
}

_PASSTHROUGH_FIELD_GROUPS: dict[str, FieldGroupSpec] = {
    "multimodal": FieldGroupSpec(
        name="multimodal",
        description="Reuse the strongest available multimodal signal from existing fields.",
        required_source_fields=[],
        output_fields=[OutputFieldSpec(name="multimodal_signal", description="Primary multimodal signal")],
        strategy="passthrough",
        passthrough_config=PassthroughConfig(
            source_fields=["image_url", "media_url", "thumbnail"],
            output_field="multimodal_signal",
        ),
        auto_platforms=("linkedin", "amazon", "arxiv", "wikipedia", "base"),
    ),
    "behavior": FieldGroupSpec(
        name="behavior",
        description="Reuse the strongest available behavioral signal from existing fields.",
        required_source_fields=[],
        output_fields=[OutputFieldSpec(name="behavior_signal", description="Primary behavioral signal")],
        strategy="passthrough",
        passthrough_config=PassthroughConfig(
            source_fields=["behavior", "activity", "actions"],
            output_field="behavior_signal",
        ),
        auto_platforms=("linkedin",),
        auto_resource_types=("profile", "post"),
    ),
    "risk": FieldGroupSpec(
        name="risk",
        description="Reuse the strongest available risk signal from existing fields.",
        required_source_fields=[],
        output_fields=[OutputFieldSpec(name="risk_signal", description="Primary risk signal")],
        strategy="passthrough",
        passthrough_config=PassthroughConfig(
            source_fields=["risk", "severity", "issue"],
            output_field="risk_signal",
        ),
        auto_platforms=("amazon", "linkedin", "base"),
        auto_resource_types=("seller", "company", "address", "contract", "defi"),
    ),
    "code": FieldGroupSpec(
        name="code",
        description="Reuse the strongest available code-related signal from existing fields.",
        required_source_fields=[],
        output_fields=[OutputFieldSpec(name="code_signal", description="Primary code signal")],
        strategy="passthrough",
        passthrough_config=PassthroughConfig(
            source_fields=["code_url", "repo", "language", "filename"],
            output_field="code_signal",
        ),
        auto_platforms=("arxiv", "base"),
        auto_resource_types=("paper", "contract"),
    ),
    "figures": FieldGroupSpec(
        name="figures",
        description="Reuse the strongest available figure or chart signal from existing fields.",
        required_source_fields=[],
        output_fields=[OutputFieldSpec(name="figure_signal", description="Primary figure or chart signal")],
        strategy="passthrough",
        passthrough_config=PassthroughConfig(
            source_fields=["figure_url", "figure_caption", "figure_id"],
            output_field="figure_signal",
        ),
        auto_platforms=("arxiv", "wikipedia"),
        auto_resource_types=("paper", "article"),
    ),
}

# Combine all field groups into the main registry
FIELD_GROUP_REGISTRY: dict[str, FieldGroupSpec] = {
    **_LEGACY_FIELD_GROUPS,
    **_PASSTHROUGH_FIELD_GROUPS,
    **LINKEDIN_FIELD_GROUPS,
    **ACADEMIC_FIELD_GROUPS,
    **AMAZON_FIELD_GROUPS,
    **BASE_FIELD_GROUPS,
}


def get_field_group_spec(name: str) -> FieldGroupSpec | None:
    """Get a field group spec by name."""
    return FIELD_GROUP_REGISTRY.get(name)


def list_field_groups() -> list[str]:
    """List all registered field group names."""
    return list(FIELD_GROUP_REGISTRY.keys())
