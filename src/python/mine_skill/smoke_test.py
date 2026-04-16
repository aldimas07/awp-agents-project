from __future__ import annotations

import argparse
import json
from typing import Any

from host_diagnostics import collect_host_diagnostics
from skill_runtime import render_first_load_experience


def run_smoke_test() -> dict[str, Any]:
    welcome = render_first_load_experience()
    diagnostics = collect_host_diagnostics()
    return {
        "ok": bool(welcome.strip()),
        "welcome_contains_mine": "Welcome to Mine" in welcome,
        "welcome_contains_version_check": "Version check" in welcome,
        "host_platform": diagnostics["platform_family"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Lightweight Mine smoke test.")
    parser.add_argument("--json", action="store_true", help="Print JSON output.")
    args = parser.parse_args()

    payload = run_smoke_test()
    if args.json:
        print(json.dumps(payload, ensure_ascii=False))
    else:
        print("Mine smoke test")
        print(f"- welcome rendered: {payload['welcome_contains_mine']}")
        print(f"- version check rendered: {payload['welcome_contains_version_check']}")
        print(f"- host platform: {payload['host_platform']}")
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
