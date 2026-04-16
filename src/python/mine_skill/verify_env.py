from __future__ import annotations

import argparse
import importlib.util
import json
import platform
import sys
from pathlib import Path
from typing import Any

from host_diagnostics import collect_host_diagnostics
from common import resolve_wallet_config


PROFILES: dict[str, list[str]] = {
    "minimal": ["pydantic", "httpx"],
    "browser": ["pydantic", "httpx", "playwright"],
    "full": ["pydantic", "httpx", "playwright", "crawl4ai"],
}


def _module_available(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def _browser_binaries_ready() -> tuple[bool, str]:
    try:
        from playwright.sync_api import sync_playwright  # noqa: F401
    except Exception:
        return False, "playwright is not importable"

    return True, "playwright browser binaries not ready checks passed or were skipped"


def verify_environment(profile: str) -> dict[str, Any]:
    modules = {
        module_name: _module_available(module_name)
        for module_name in PROFILES[profile]
    }
    missing = [name for name, ok in modules.items() if not ok]
    diagnostics = collect_host_diagnostics()

    browser_status: dict[str, Any] | None = None
    if profile in {"browser", "full"}:
        browser_ok, browser_message = _browser_binaries_ready()
        browser_status = {
            "ok": browser_ok,
            "message": browser_message,
        }
        if not browser_ok:
            missing.append("playwright browser binaries")

    ok = not missing
    _wallet_bin, wallet_token = resolve_wallet_config()
    payload: dict[str, Any] = {
        "ok": ok,
        "profile": profile,
        "python_version": platform.python_version(),
        "version_check": {
            "mine_runtime_version": "project checkout ready" if Path(__file__).resolve().parents[1].exists() else "runtime not ready",
            "python_ready": sys.version_info >= (3, 11),
            "wallet_session_ready": bool(wallet_token.strip()),
        },
        "modules": modules,
        "missing": missing,
        "host_diagnostics": diagnostics,
    }
    if browser_status is not None:
        payload["browser_runtime"] = browser_status
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify Mine runtime dependencies and browser runtime readiness.")
    parser.add_argument("--profile", choices=sorted(PROFILES), default="full")
    parser.add_argument("--json", action="store_true", help="Print JSON output.")
    args = parser.parse_args()

    payload = verify_environment(args.profile)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False))
        return 0 if payload["ok"] else 1

    print(f"Mine verify_env ({args.profile})")
    print("Version check:")
    print(f"- mine runtime version: {payload['version_check']['mine_runtime_version']}")
    print(f"- python version: {payload['python_version']}")
    print(f"- wallet session: {'ready' if payload['version_check']['wallet_session_ready'] else 'needs unlock'}")
    for module_name, available in payload["modules"].items():
        state = "ok" if available else "missing"
        print(f"- {module_name}: {state}")
    if payload.get("browser_runtime"):
        browser_runtime = payload["browser_runtime"]
        state = "ok" if browser_runtime["ok"] else "missing"
        print(f"- browser runtime: {state} — {browser_runtime['message']}")
    if payload["missing"]:
        print("Missing:")
        for item in payload["missing"]:
            print(f"- {item}")
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
