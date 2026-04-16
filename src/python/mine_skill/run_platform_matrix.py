from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOCAL_TASKS = PROJECT_ROOT / "local_tasks"
OUTPUT_ROOT = PROJECT_ROOT / "output" / "platform-matrix"


DEFAULT_CASES: list[dict[str, str]] = [
    {
        "name": "wikipedia_openai",
        "task_type": "local_file",
        "task_path": "local_tasks/wikipedia-openai-local.json",
        "platform": "wikipedia",
    },
    {
        "name": "arxiv_transformers",
        "task_type": "local_file",
        "task_path": "local_tasks/arxiv-transformers-local.json",
        "platform": "arxiv",
    },
    {
        "name": "generic_python_docs",
        "task_type": "local_file",
        "task_path": "local_tasks/generic-python-docs-local.json",
        "platform": "generic",
    },
    {
        "name": "amazon_echo",
        "task_type": "local_file",
        "task_path": "local_tasks/amazon-echo-local.json",
        "platform": "amazon",
    },
]


def _safe_name(raw: str) -> str:
    return "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in raw).strip("_") or "case"


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _summarize_case(case: dict[str, str]) -> dict[str, Any]:
    name = _safe_name(case["name"])
    task_type = case["task_type"]
    task_path = PROJECT_ROOT / case["task_path"]
    if not task_path.exists():
        return {
            "name": name,
            "platform": case.get("platform"),
            "status": "failed",
            "reason": f"task file not found: {task_path}",
        }

    output_dir = OUTPUT_ROOT / name
    output_dir.mkdir(parents=True, exist_ok=True)

    command = [
        sys.executable,
        str(PROJECT_ROOT / "scripts" / "run_tool.py"),
        "process-task-file",
        task_type,
        str(task_path),
    ]
    proc = subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    case_result: dict[str, Any] = {
        "name": name,
        "platform": case.get("platform"),
        "task_type": task_type,
        "task_path": str(task_path),
        "returncode": proc.returncode,
        "stdout": proc.stdout.strip(),
        "stderr": proc.stderr.strip(),
    }

    # Current runtime writes into output/agent-runs/local_file/<derived-name>
    derived_output_dir = PROJECT_ROOT / "output" / "agent-runs" / "local_file" / f"{task_type}_{Path(task_path).stem}"
    case_result["derived_output_dir"] = str(derived_output_dir)

    summary_path = derived_output_dir / "summary.json"
    records_path = derived_output_dir / "records.jsonl"
    errors_path = derived_output_dir / "errors.jsonl"

    if summary_path.exists():
        summary = _read_json(summary_path)
        case_result["summary"] = summary
        case_result["status"] = summary.get("status", "unknown")
    else:
        case_result["status"] = "failed"
        case_result["reason"] = "summary.json not found"

    case_result["has_records"] = records_path.exists() and records_path.stat().st_size > 0
    case_result["has_errors"] = errors_path.exists() and errors_path.stat().st_size > 0

    if case_result["has_records"]:
        case_result["record_preview"] = records_path.read_text(encoding="utf-8").splitlines()[:1]
    if case_result["has_errors"]:
        case_result["error_preview"] = errors_path.read_text(encoding="utf-8").splitlines()[:3]

    return case_result


def run_cases(cases: list[dict[str, str]]) -> dict[str, Any]:
    results = [_summarize_case(case) for case in cases]
    return {
        "ok": all(item.get("status") == "success" for item in results),
        "cases": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a real collection matrix against local task files.")
    parser.add_argument("--json", action="store_true", help="Print JSON result")
    args = parser.parse_args()

    payload = run_cases(DEFAULT_CASES)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        for item in payload["cases"]:
            print(f"{item['name']}: {item.get('status')} (records={item.get('has_records')}, errors={item.get('has_errors')})")
            if item.get("error_preview"):
                print("  errors:", item["error_preview"][0])
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
