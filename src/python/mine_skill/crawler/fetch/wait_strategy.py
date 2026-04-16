from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_REFERENCES_DIR = Path(__file__).resolve().parents[2] / "references"
_CONFIG_CACHE: dict[str, Any] | None = None


def _load_config() -> dict[str, Any]:
    global _CONFIG_CACHE
    if _CONFIG_CACHE is not None:
        return _CONFIG_CACHE
    config_path = _REFERENCES_DIR / "wait_strategies.json"
    if not config_path.exists():
        logger.warning("wait_strategies.json not found at %s", config_path)
        _CONFIG_CACHE = {}
        return _CONFIG_CACHE
    _CONFIG_CACHE = json.loads(config_path.read_text(encoding="utf-8"))
    return _CONFIG_CACHE


def get_wait_config(platform: str, resource_type: str) -> dict[str, Any]:
    """Return the wait strategy config for a platform/resource_type pair."""
    config = _load_config()
    defaults = config.get("_defaults", {})
    platform_config = config.get(platform, {})
    resource_config = platform_config.get(resource_type, {})
    merged = {**defaults, **resource_config}
    return merged


async def apply_wait_strategy(page: Any, platform: str, resource_type: str) -> tuple[str, int]:
    """Apply wait strategy on a Playwright page. Returns (strategy_name, elapsed_ms)."""
    config = get_wait_config(platform, resource_type)
    max_wait = config.get("max_wait_ms", 10000)
    strategy_parts: list[str] = []
    start = time.monotonic()

    selector = config.get("wait_for_selector")
    if selector:
        try:
            await page.wait_for_selector(selector, timeout=max_wait)
            strategy_parts.append(f"selector:{selector}")
        except Exception:
            logger.debug("wait_for_selector timed out for %s/%s: %s", platform, resource_type, selector)
            strategy_parts.append(f"selector_timeout:{selector}")

    if config.get("wait_for_network_quiet"):
        remaining = max(1000, max_wait - int((time.monotonic() - start) * 1000))
        try:
            await page.wait_for_load_state("networkidle", timeout=remaining)
            strategy_parts.append("network_quiet")
        except Exception:
            logger.debug("network_quiet timed out for %s/%s", platform, resource_type)
            strategy_parts.append("network_quiet_timeout")

    if config.get("scroll_to_load"):
        scroll_count = config.get("scroll_count", 2)
        for i in range(scroll_count):
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            try:
                await page.wait_for_timeout(800)
            except Exception:
                pass
        strategy_parts.append(f"scroll:{scroll_count}")

    elapsed_ms = int((time.monotonic() - start) * 1000)
    strategy_name = "+".join(strategy_parts) if strategy_parts else "none"
    return strategy_name, elapsed_ms


def apply_wait_strategy_sync(page: Any, platform: str, resource_type: str) -> tuple[str, int]:
    """Synchronous version that works with sync Playwright pages."""
    config = get_wait_config(platform, resource_type)
    max_wait = config.get("max_wait_ms", 10000)
    strategy_parts: list[str] = []
    start = time.monotonic()

    selector = config.get("wait_for_selector")
    if selector:
        try:
            page.wait_for_selector(selector, timeout=max_wait)
            strategy_parts.append(f"selector:{selector}")
        except Exception:
            logger.debug("wait_for_selector timed out for %s/%s: %s", platform, resource_type, selector)
            strategy_parts.append(f"selector_timeout:{selector}")

    if config.get("wait_for_network_quiet"):
        remaining = max(1000, max_wait - int((time.monotonic() - start) * 1000))
        try:
            page.wait_for_load_state("networkidle", timeout=remaining)
            strategy_parts.append("network_quiet")
        except Exception:
            logger.debug("network_quiet timed out for %s/%s", platform, resource_type)
            strategy_parts.append("network_quiet_timeout")

    if config.get("scroll_to_load"):
        scroll_count = config.get("scroll_count", 2)
        for i in range(scroll_count):
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            try:
                page.wait_for_timeout(800)
            except Exception:
                pass
        strategy_parts.append(f"scroll:{scroll_count}")

    elapsed_ms = int((time.monotonic() - start) * 1000)
    strategy_name = "+".join(strategy_parts) if strategy_parts else "none"
    return strategy_name, elapsed_ms
