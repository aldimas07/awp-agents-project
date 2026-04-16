"""Unified LLM enrich routing for mine.

Preferred order:
1. OpenClaw agent CLI
2. OpenClaw Gateway (`provider=openclaw`)
3. Other OpenAI-compatible APIs
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any

from crawler.enrich.models import LLMResponse

log = logging.getLogger(__name__)


@dataclass(slots=True)
class EnrichResult:
    """Normalized result for any enrich execution path."""

    content: str
    success: bool
    method: str
    error: str | None = None
    model: str | None = None
    tokens_used: int = 0

    def to_llm_response(self, fallback_model: str = "") -> LLMResponse:
        return LLMResponse(
            content=self.content,
            model=self.model or fallback_model or self.method,
            total_tokens=self.tokens_used,
        )


def _requested_mode() -> str:
    value = os.environ.get("MINE_LLM_MODE", "").strip() or os.environ.get("MINE_ENRICH_MODE", "").strip()
    return value.lower() or "auto"


def _openclaw_cli_available() -> bool:
    from crawler.enrich.generative.openclaw_agent import openclaw_cli_available

    return openclaw_cli_available()


def _has_gateway_config(model_config: dict[str, Any] | None) -> bool:
    config = model_config or {}
    return (
        str(config.get("provider", "")).strip().lower() == "openclaw"
        and bool(str(config.get("base_url", "")).strip())
        and bool(str(config.get("model", "")).strip())
    )


def _has_api_config(model_config: dict[str, Any] | None) -> bool:
    config = model_config or {}
    return bool(str(config.get("base_url", "")).strip()) and bool(str(config.get("model", "")).strip())


def llm_execution_available(model_config: dict[str, Any] | None = None) -> bool:
    """Return whether any configured execution path can satisfy an enrich request.

    In auto mode priority is: CLI > gateway > api.
    CLI reuses the model already configured for the OpenClaw agent (e.g. OpenRouter) without a separate API key.
    """
    mode = _requested_mode()
    if mode in {"openclaw_cli", "cli"}:
        return _openclaw_cli_available()
    if mode == "gateway":
        return _has_gateway_config(model_config)
    if mode == "api":
        return _has_api_config(model_config)
    # auto: prefer CLI when OpenClaw is available
    return _openclaw_cli_available() or _has_gateway_config(model_config) or _has_api_config(model_config)


def _should_try_openclaw_cli() -> bool:
    mode = _requested_mode()
    if mode in {"gateway", "api"}:
        return False
    # auto / cli / openclaw_cli: use CLI whenever it is available
    return _openclaw_cli_available()


async def enrich_with_llm(
    prompt: str,
    *,
    model_config: dict[str, Any] | None = None,
    system_prompt: str = "",
    timeout: float = 120.0,
) -> EnrichResult:
    """Execute a single enrich prompt with the preferred routing."""
    config = dict(model_config or {})

    if _should_try_openclaw_cli():
        result = await _enrich_via_openclaw_cli(prompt, system_prompt=system_prompt, timeout=timeout)
        if result.success:
            return result
        log.warning("[LLM] OpenClaw CLI enrich failed: %s", result.error)

    if _has_api_config(config):
        return await _enrich_via_model_config(
            prompt,
            model_config=config,
            system_prompt=system_prompt,
            timeout=timeout,
        )

    return EnrichResult(
        content="",
        success=False,
        method="none",
        error="No LLM method available (OpenClaw CLI unavailable and no model_config fallback)",
    )


async def _enrich_via_openclaw_cli(
    prompt: str,
    *,
    system_prompt: str = "",
    timeout: float = 120.0,
) -> EnrichResult:
    from crawler.enrich.generative.openclaw_agent import EnrichResponse, call_agent

    full_prompt = prompt if not system_prompt else f"{system_prompt}\n\n{prompt}"

    import asyncio

    loop = asyncio.get_running_loop()
    response: EnrichResponse = await loop.run_in_executor(None, lambda: call_agent(full_prompt, timeout=timeout, purge_sessions=False))
    return EnrichResult(
        content=response.content,
        success=response.success,
        method="openclaw_cli",
        error=response.error,
        model=response.model,
        tokens_used=int(response.tokens_used or 0),
    )


async def _enrich_via_model_config(
    prompt: str,
    *,
    model_config: dict[str, Any],
    system_prompt: str = "",
    timeout: float = 120.0,
) -> EnrichResult:
    from crawler.enrich.generative.llm_client import (
        LLMClient,
        LLMConfigurationError,
        LLMEmptyResponseError,
        LLMRequestError,
    )

    config = {**model_config, "timeout": timeout}
    method = "gateway" if str(config.get("provider", "")).strip().lower() == "openclaw" else "api"

    try:
        client = LLMClient.from_model_config(config)
        response: LLMResponse = await client.complete(
            prompt,
            system_prompt=system_prompt,
            max_tokens=int(config.get("max_tokens", 768)),
            temperature=float(config.get("temperature", 0.1)),
        )
    except LLMConfigurationError as exc:
        return EnrichResult(content="", success=False, method=method, error=f"Configuration error: {exc}")
    except (LLMRequestError, LLMEmptyResponseError) as exc:
        return EnrichResult(content="", success=False, method=method, error=str(exc))
    except Exception as exc:  # pragma: no cover - defensive guard
        return EnrichResult(content="", success=False, method=method, error=f"Unexpected error: {exc}")

    return EnrichResult(
        content=response.content,
        success=True,
        method=method,
        model=response.model,
        tokens_used=response.tokens_used,
    )


def available_methods(model_config: dict[str, Any] | None = None) -> list[str]:
    """Return list of available LLM methods for diagnostics."""
    methods: list[str] = []
    if _openclaw_cli_available():
        methods.append("openclaw_cli")
    if _has_gateway_config(model_config):
        methods.append("gateway")
    if _has_api_config(model_config):
        methods.append("api")
    return methods
