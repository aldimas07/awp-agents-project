from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_REFERENCES_DIR = Path(__file__).resolve().parents[2] / "references"
_ROUTING_CACHE: dict[str, Any] | None = None


def _load_routing_config() -> dict[str, Any]:
    global _ROUTING_CACHE
    if _ROUTING_CACHE is not None:
        return _ROUTING_CACHE
    config_path = _REFERENCES_DIR / "backend_routing.json"
    if not config_path.exists():
        logger.warning("backend_routing.json not found at %s", config_path)
        _ROUTING_CACHE = {"rules": [], "default": {"initial_backend": "http", "fallback_chain": []}}
        return _ROUTING_CACHE
    _ROUTING_CACHE = json.loads(config_path.read_text(encoding="utf-8"))
    return _ROUTING_CACHE


def _match_rule(rule_match: dict[str, Any], platform: str, resource_type: str | None, requires_auth: bool) -> bool:
    """Check if a routing rule matches the given parameters."""
    if "platform" in rule_match and rule_match["platform"] != platform:
        return False
    if "resource_type" in rule_match and rule_match["resource_type"] != resource_type:
        return False
    if "requires_auth" in rule_match and rule_match["requires_auth"] != requires_auth:
        return False
    return True


def resolve_backend(
    platform: str,
    resource_type: str | None = None,
    requires_auth: bool = False,
) -> tuple[str, list[str]]:
    """Return (initial_backend, fallback_chain) for the given platform/resource_type."""
    config = _load_routing_config()
    rules = config.get("rules", [])
    for rule in rules:
        if _match_rule(rule["match"], platform, resource_type, requires_auth):
            return rule["initial_backend"], rule.get("fallback_chain", [])
    default = config.get("default", {})
    return default.get("initial_backend", "http"), default.get("fallback_chain", [])


def get_escalation_backend(
    platform: str,
    current_backend: str,
    resource_type: str | None = None,
    requires_auth: bool = False,
) -> str | None:
    """Given a failed backend, return the next backend in the fallback chain, or None."""
    initial, fallback_chain = resolve_backend(platform, resource_type, requires_auth)
    all_backends = [initial] + fallback_chain
    try:
        idx = all_backends.index(current_backend)
    except ValueError:
        return fallback_chain[0] if fallback_chain else None
    next_idx = idx + 1
    if next_idx < len(all_backends):
        return all_backends[next_idx]
    return None
