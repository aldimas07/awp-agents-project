from __future__ import annotations

import json
from pathlib import Path


def build_summary(records: list[dict], errors: list[dict]) -> dict:
    records_total = len(records) + len(errors)
    return {
        "status": "failed" if records_total and not records else ("partial_success" if errors else "success"),
        "records_total": records_total,
        "records_succeeded": len(records),
        "records_failed": len(errors),
        "next_action": "inspect errors.jsonl" if errors else "none",
    }


def write_summary(path: Path, summary: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")


def write_manifest(path: Path, manifest: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
