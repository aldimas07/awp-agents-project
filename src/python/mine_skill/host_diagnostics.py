from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
from typing import Any


def detect_platform_family() -> str:
    system = platform.system().lower()
    if "linux" in system:
        return "linux"
    if "darwin" in system or "mac" in system:
        return "darwin"
    if "windows" in system:
        return "windows"
    return "unknown"


def _command_available(name: str) -> bool:
    return shutil.which(name) is not None


def _run_success(command: list[str]) -> bool:
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return completed.returncode == 0


def collect_host_diagnostics() -> dict[str, Any]:
    family = detect_platform_family()
    checks: list[dict[str, Any]] = []
    guidance: list[str] = []

    if family == "linux":
        libnss3 = any(
            os.path.exists(candidate)
            for candidate in (
                "/usr/lib/libnss3.so",
                "/usr/lib64/libnss3.so",
                "/lib/x86_64-linux-gnu/libnss3.so",
            )
        )
        checks.append(
            {
                "name": "libnss3.so",
                "ok": libnss3,
                "detail": "Required by Chromium/Playwright on many Linux hosts.",
            }
        )
        if not libnss3:
            guidance.append("Install libnss3.so or the distro package that provides NSS browser libraries.")
    elif family == "darwin":
        xcode_ok = _run_success(["xcode-select", "-p"])
        checks.append(
            {
                "name": "xcode-select",
                "ok": xcode_ok,
                "detail": "Recommended for browser/runtime build dependencies on macOS.",
            }
        )
        if not xcode_ok:
            guidance.append("Run `xcode-select --install` to prepare browser/runtime dependencies.")
    elif family == "windows":
        checks.append(
            {
                "name": "Visual C++ Redistributable",
                "ok": _command_available("where"),
                "detail": "Recommended for browser automation dependencies on Windows.",
            }
        )
        guidance.append("If browser startup fails on Windows, install the latest Visual C++ Redistributable.")
    else:
        checks.append(
            {
                "name": "platform-detection",
                "ok": False,
                "detail": "Unsupported platform family; run Mine verification manually.",
            }
        )
        guidance.append("Mine host diagnostics could not classify this OS family.")

    checks.append(
        {
            "name": "python3",
            "ok": _command_available("python3") or _command_available("python"),
            "detail": "Python is required for Mine runtime scripts.",
        }
    )

    ok = all(bool(item.get("ok")) for item in checks if item.get("name") != "Visual C++ Redistributable")
    return {
        "ok": ok,
        "platform_family": family,
        "checks": checks,
        "guidance": guidance,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Host diagnostics for Mine bootstrap and browser runtime checks.")
    parser.add_argument("--json", action="store_true", help="Print JSON output.")
    args = parser.parse_args()

    payload = collect_host_diagnostics()
    if args.json:
        print(json.dumps(payload, ensure_ascii=False))
        return 0

    print(f"Host diagnostics ({payload['platform_family']})")
    for item in payload["checks"]:
        state = "ok" if item.get("ok") else "missing"
        print(f"- {item['name']}: {state} — {item.get('detail', '')}")
    if payload["guidance"]:
        print("Guidance:")
        for line in payload["guidance"]:
            print(f"- {line}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
