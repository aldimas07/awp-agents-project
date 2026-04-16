from __future__ import annotations

from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from crawler.enrich.generative.llm_client import parse_json_response
from crawler.enrich.generative.llm_enrich import enrich_with_llm, llm_execution_available


def extract_json_object(content: str) -> dict[str, Any]:
    parsed = parse_json_response(content)
    return parsed if isinstance(parsed, dict) else {"items": parsed}


@dataclass(slots=True)
class SchemaExecutionResult:
    success: bool
    data: dict[str, Any]
    error: str | None = None
    schema_name: str = ""

    def to_error_dict(self) -> dict[str, Any]:
        return {
            "schema_name": self.schema_name,
            "status": "failed",
            "error": self.error or "schema execution failed",
        }


class LLMExecutor:
    def __init__(self, model_config: dict[str, Any]):
        self.model_config = model_config

    async def execute(
        self,
        *,
        schema_name: str,
        instruction: str,
        payload: dict[str, Any],
        system_prompt: str = "Extract only the requested JSON object. Return valid JSON only.",
    ) -> SchemaExecutionResult:
        if not llm_execution_available(self.model_config):
            return SchemaExecutionResult(
                success=False,
                data={},
                error="No LLM enrich method available",
                schema_name=schema_name,
            )

        prompt = (
            f"Schema name: {schema_name}\n"
            f"Instruction: {instruction}\n"
            f"Payload:\n{payload}"
        )
        try:
            response = await enrich_with_llm(
                prompt,
                model_config=self.model_config or None,
                system_prompt=system_prompt,
                timeout=float(self.model_config.get("timeout", 60.0) or 60.0),
            )
            if not response.success:
                return SchemaExecutionResult(
                    success=False,
                    data={},
                    error=response.error or "schema execution failed",
                    schema_name=schema_name,
                )
            return SchemaExecutionResult(
                success=True,
                data=extract_json_object(response.content),
                schema_name=schema_name,
            )
        except Exception as exc:
            return SchemaExecutionResult(success=False, data={}, error=str(exc), schema_name=schema_name)

    def execute_sync(
        self,
        *,
        schema_name: str,
        instruction: str,
        payload: dict[str, Any],
        system_prompt: str = "Extract only the requested JSON object. Return valid JSON only.",
    ) -> SchemaExecutionResult:
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(
                lambda: __import__("asyncio").run(
                    self.execute(
                        schema_name=schema_name,
                        instruction=instruction,
                        payload=payload,
                        system_prompt=system_prompt,
                    )
                )
            )
            return future.result()
