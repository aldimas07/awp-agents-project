from __future__ import annotations

import json
import inspect
from pathlib import Path
from typing import Any
from concurrent.futures import ThreadPoolExecutor

from ..models import StructuredFields
from ...schema_runtime import LLMExecutor


class LLMSchemaExtractor:
    def __init__(self, schema_path: Path, model_config: dict[str, Any]):
        self.schema = json.loads(schema_path.read_text(encoding="utf-8"))
        self.executor = LLMExecutor(model_config)

    def execute(self, payload: dict[str, Any]) -> dict[str, Any]:
        result = self.executor.execute_sync(
            schema_name=str(self.schema.get("schema_name", "extract_schema")),
            instruction=str(self.schema.get("instruction", "Extract structured fields")),
            payload=payload,
            system_prompt=str(self.schema.get("system_prompt", "Extract only the requested JSON object. Return valid JSON only.")),
        )
        return {
            "success": result.success,
            "data": result.data,
            "error": result.error,
            "schema_name": result.schema_name,
        }

    def extract(
        self,
        *,
        plain_text: str,
        markdown: str,
        cleaned_html: str,
        metadata: dict[str, Any],
        platform: str,
        resource_type: str,
        canonical_url: str,
    ) -> tuple[StructuredFields | None, dict[str, Any] | None]:
        # Truncate to avoid exceeding LLM context window
        _MAX_LLM_CHARS = 30000
        if plain_text and len(plain_text) > _MAX_LLM_CHARS:
            plain_text = plain_text[:_MAX_LLM_CHARS]
        if markdown and len(markdown) > _MAX_LLM_CHARS:
            markdown = markdown[:_MAX_LLM_CHARS]
        if cleaned_html and len(cleaned_html) > _MAX_LLM_CHARS:
            cleaned_html = cleaned_html[:_MAX_LLM_CHARS]
        result = self.execute(
            {
                "platform": platform,
                "resource_type": resource_type,
                "canonical_url": canonical_url,
                "plain_text": plain_text,
                "markdown": markdown,
                "cleaned_html": cleaned_html,
                "metadata": metadata,
            }
        )
        if inspect.isawaitable(result):
            with ThreadPoolExecutor(max_workers=1) as executor:
                result = executor.submit(lambda: __import__("asyncio").run(result)).result()
        if not result.get("success"):
            return None, {
                "schema_name": result.get("schema_name", "extract_schema"),
                "status": "failed",
                "error": result.get("error", "schema execution failed"),
            }

        data = result.get("data", {})
        fields = data.get("fields", {}) if isinstance(data.get("fields"), dict) else {}
        schema_name = str(result.get("schema_name", "extract_schema"))
        field_sources = {key: f"llm_schema:{schema_name}" for key in fields}
        if data.get("title"):
            field_sources["title"] = f"llm_schema:{schema_name}"
        if data.get("description"):
            field_sources["description"] = f"llm_schema:{schema_name}"
        return StructuredFields(
            platform=platform,
            resource_type=resource_type,
            title=data.get("title"),
            description=data.get("description"),
            canonical_url=canonical_url,
            platform_fields=fields,
            field_sources=field_sources,
        ), None
