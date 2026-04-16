from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable, Protocol

from crawler.enrich.models import EnrichedRecord, FieldGroupResult
from crawler.enrich.pipeline import EnrichPipeline


class LLMCallable(Protocol):
    async def __call__(self, prompt: str, system: str | None = None) -> str: ...


class AgentProtocol(Protocol):
    async def generate(self, prompt: str, system: str | None = None) -> str: ...

    def supports_vision(self) -> bool: ...


class AgentEnrichmentExecutor:
    """Execute enrichment and automatically resolve pending generative groups."""

    def __init__(
        self,
        *,
        llm_call: LLMCallable | None = None,
        agent: AgentProtocol | None = None,
        use_subagents: bool = False,
        spawn_subagent: Callable[[str, str, str | None], Awaitable[str]] | None = None,
        model_capabilities: dict[str, bool] | None = None,
    ) -> None:
        if llm_call is None and agent is None:
            raise ValueError("llm_call or agent is required")
        if use_subagents and spawn_subagent is None:
            raise ValueError("spawn_subagent is required when use_subagents=True")

        self._llm_call = llm_call
        self._agent = agent
        self._use_subagents = use_subagents
        self._spawn_subagent = spawn_subagent
        self._model_capabilities = model_capabilities or {}
        self._pipeline = EnrichPipeline()

    @property
    def model_capabilities(self) -> dict[str, bool]:
        if self._model_capabilities:
            return self._model_capabilities
        if self._agent and hasattr(self._agent, "supports_vision"):
            return {"vision": self._agent.supports_vision()}
        return {}

    async def _call_llm(self, prompt: str, system: str | None = None) -> str:
        if self._llm_call is not None:
            return await self._llm_call(prompt, system)
        if self._agent is not None:
            return await self._agent.generate(prompt, system)
        raise RuntimeError("no LLM call available")

    async def enrich(
        self,
        document: dict[str, Any],
        field_groups: list[str],
        parallel: bool = True,
    ) -> EnrichedRecord:
        result = await self._pipeline.enrich(
            document,
            field_groups,
            model_capabilities=self.model_capabilities,
        )

        pending_groups = [
            group for group in result.enrichment_results.values() if group.status == "pending_agent"
        ]
        if not pending_groups:
            return result

        if self._use_subagents and parallel and len(pending_groups) > 1:
            responses = await self._execute_parallel(pending_groups)
        else:
            responses = await self._execute_serial(pending_groups)

        for group, response in zip(pending_groups, responses):
            filled = self._pipeline.fill_pending_agent_result(group.field_group, response, document=document)
            self._update_field_group_result(result, group.field_group, filled)

        return result

    async def _execute_serial(self, pending_groups: list[FieldGroupResult]) -> list[str]:
        responses: list[str] = []
        for group in pending_groups:
            responses.append(await self._call_llm(group.agent_prompt or "", group.agent_system_prompt))
        return responses

    async def _execute_parallel(self, pending_groups: list[FieldGroupResult]) -> list[str]:
        if self._spawn_subagent is None:
            return await self._execute_serial(pending_groups)
        tasks = [
            self._spawn_subagent(
                f"enrich_{group.field_group}",
                group.agent_prompt or "",
                group.agent_system_prompt,
            )
            for group in pending_groups
        ]
        return await asyncio.gather(*tasks)

    def _update_field_group_result(
        self,
        record: EnrichedRecord,
        field_group: str,
        filled: FieldGroupResult,
    ) -> None:
        record.enrichment_results[field_group] = filled
        if filled.fields:
            for field in filled.fields:
                if field.value is not None:
                    record.enriched_fields[field.field_name] = field.value

    async def auto_enrich(self, document: dict[str, Any]) -> EnrichedRecord:
        """Use platform defaults first, then fall back to registry-wide auto scoping."""
        from crawler.enrich.schemas.field_group_registry import FIELD_GROUP_REGISTRY
        from crawler.platforms.registry import get_platform_adapter

        platform = str(document.get("platform") or "").lower()
        resource_type = str(document.get("resource_type") or "").lower()

        try:
            adapter = get_platform_adapter(platform)
        except Exception:
            adapter = None

        if adapter is not None:
            request = adapter.build_enrichment_request(document)
            adapter_groups = request.get("field_groups") if isinstance(request, dict) else ()
            if isinstance(adapter_groups, (list, tuple)) and adapter_groups:
                return await self.enrich(document, list(adapter_groups), parallel=True)

        field_groups: list[str] = []
        for name, spec in FIELD_GROUP_REGISTRY.items():
            if not spec.applies_to(platform, resource_type):
                continue
            if spec.requires_vision and not self.model_capabilities.get("vision"):
                continue
            field_groups.append(name)

        return await self.enrich(document, field_groups, parallel=True)


async def enrich_with_llm(
    document: dict[str, Any],
    field_groups: list[str],
    llm_call: LLMCallable,
    model_capabilities: dict[str, bool] | None = None,
) -> EnrichedRecord:
    executor = AgentEnrichmentExecutor(
        llm_call=llm_call,
        model_capabilities=model_capabilities,
    )
    return await executor.enrich(document, field_groups)
