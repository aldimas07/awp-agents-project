from __future__ import annotations

import json
import os
from typing import Any
from urllib.parse import urlencode

from crawler.fetch.api_backend import fetch_api_get, fetch_api_post

from .base import (
    PlatformAdapter,
    PlatformDiscoveryPlan,
    PlatformEnrichmentPlan,
    PlatformErrorPlan,
    PlatformExtractPlan,
    PlatformFetchPlan,
    PlatformNormalizePlan,
    default_fetch_executor,
    default_backend_resolver,
    hook_normalizer,
    route_enrichment_groups,
    strategy_extractor,
)

FETCH_PLAN = PlatformFetchPlan(default_backend="api", fallback_backends=("http", "playwright"))
EXTRACT_PLAN = PlatformExtractPlan(strategy="blockchain_scan")
NORMALIZE_PLAN = PlatformNormalizePlan(hook_name="base_chain")
ENRICH_PLAN = PlatformEnrichmentPlan(
    route="onchain_graph",
    field_groups=(
        "base_addresses_basic",
        "base_addresses_activity",
        "base_transactions_basic",
    ),
)


def _resolve_base_backend(record: dict[str, Any], override_backend: str | None = None, retry_count: int = 0) -> str:
    if override_backend:
        return override_backend

    resource_type = record.get("resource_type")
    if resource_type in {"token", "contract"}:
        chain = ("http", "playwright")
        if retry_count <= 0:
            return "http"
        return chain[min(retry_count, len(chain) - 1)]

    return default_backend_resolver(FETCH_PLAN)(record, override_backend, retry_count)


def _fetch_base_api(record: dict, discovered: dict, storage_state_path: str | None) -> dict:
    resource_type = record["resource_type"]
    if resource_type == "address":
        payload = {"jsonrpc": "2.0", "method": "eth_getBalance", "params": [discovered["fields"]["address"], "latest"], "id": 1}
        return fetch_api_post(
            canonical_url=discovered["canonical_url"],
            api_endpoint="https://mainnet.base.org",
            headers={"Content-Type": "application/json"},
            json_payload=payload,
        )
    if resource_type == "transaction":
        payload = {"jsonrpc": "2.0", "method": "eth_getTransactionByHash", "params": [discovered["fields"]["tx_hash"]], "id": 1}
        return fetch_api_post(
            canonical_url=discovered["canonical_url"],
            api_endpoint="https://mainnet.base.org",
            headers={"Content-Type": "application/json"},
            json_payload=payload,
        )
    if resource_type == "token":
        endpoint = _build_etherscan_v2_endpoint(
            module="token",
            action="tokeninfo",
            extra_params={"contractaddress": discovered["fields"]["contract_address"]},
        )
        return fetch_api_get(canonical_url=discovered["canonical_url"], api_endpoint=endpoint)
    if resource_type == "contract":
        endpoint = _build_etherscan_v2_endpoint(
            module="contract",
            action="getsourcecode",
            extra_params={"address": discovered["fields"]["contract_address"]},
        )
        return fetch_api_get(canonical_url=discovered["canonical_url"], api_endpoint=endpoint)
    raise ValueError(f"unsupported api resource for base: {resource_type}")


def _build_etherscan_v2_endpoint(
    *,
    module: str,
    action: str,
    extra_params: dict[str, str],
) -> str:
    api_key = os.environ.get("ETHERSCAN_API_KEY") or os.environ.get("BASESCAN_API_KEY") or ""
    params = {
        "chainid": "8453",
        "module": module,
        "action": action,
        **extra_params,
    }
    if api_key:
        params["apikey"] = api_key
    return "https://api.etherscan.io/v2/api?" + urlencode(params)


def _extract_base(record: dict, fetched: dict) -> dict:
    data = fetched.get("json_data") or {}
    result = data.get("result")
    plain_text = json.dumps(result, ensure_ascii=False, default=str)
    markdown = f"```json\n{plain_text}\n```"
    return {
        "metadata": {
            "title": record["resource_type"],
            "content_type": fetched.get("content_type"),
            "source_url": fetched["url"],
        },
        "plain_text": plain_text,
        "markdown": markdown,
        "document_blocks": [],
        "structured": {"rpc_result": result},
        "extractor": "base_api",
    }


ADAPTER = PlatformAdapter(
    platform="base",
    discovery=PlatformDiscoveryPlan(
        resource_types=("address", "transaction", "token", "contract"),
        canonicalizer="base_chain",
    ),
    fetch=FETCH_PLAN,
    extract=EXTRACT_PLAN,
    normalize=NORMALIZE_PLAN,
    enrich=ENRICH_PLAN,
    error=PlatformErrorPlan(normalized_code="BASE_CHAIN_FETCH_FAILED"),
    resolve_backend_fn=_resolve_base_backend,
    fetch_fn=default_fetch_executor(_fetch_base_api),
    extract_fn=_extract_base,
    normalize_fn=hook_normalizer(NORMALIZE_PLAN.hook_name),
    enrichment_fn=route_enrichment_groups(ENRICH_PLAN),
)
