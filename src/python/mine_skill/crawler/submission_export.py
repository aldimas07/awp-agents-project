from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .output import read_json_file, read_jsonl_file
from .schema_contract import flatten_record_for_schema


def build_submission_request(
    records: list[dict[str, Any]],
    *,
    dataset_id: str,
    generated_at: str | None = None,
) -> dict[str, Any]:
    entries: list[dict[str, Any]] = []

    for record in records:
        url = str(record.get("canonical_url") or record.get("url") or "").strip()
        if not url:
            continue  # skip records with no URL

        crawl_timestamp = str(record.get("crawl_timestamp") or generated_at or "").strip()
        if not crawl_timestamp:
            continue  # skip records with no timestamp

        structured_data = _build_structured_data(record)

        cleaned_data = record.get("plain_text")
        if cleaned_data in (None, ""):
            cleaned_data = record.get("cleaned_data")
        if cleaned_data in (None, ""):
            cleaned_data = record.get("markdown")

        entries.append(
            {
                "url": url,
                "cleaned_data": "" if cleaned_data is None else str(cleaned_data),
                "structured_data": structured_data,
                "crawl_timestamp": crawl_timestamp,
            }
        )

    return {
        "dataset_id": dataset_id,
        "entries": entries,
    }


def export_submission_request(
    *,
    input_path: Path,
    output_path: Path,
    dataset_id: str,
    generated_at: str | None = None,
) -> Path:
    records = read_jsonl_file(input_path)
    payload = build_submission_request(
        records,
        dataset_id=dataset_id,
        generated_at=generated_at or _load_generated_at_fallback(input_path),
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return output_path


def _load_generated_at_fallback(input_path: Path) -> str | None:
    manifest_path = input_path.parent / "run_manifest.json"
    if not manifest_path.exists():
        return None
    payload = read_json_file(manifest_path)
    if not isinstance(payload, dict):
        return None
    generated_at = payload.get("generated_at")
    if generated_at in (None, ""):
        return None
    return str(generated_at)


def _build_structured_data(record: dict[str, Any]) -> dict[str, Any]:
    try:
        return flatten_record_for_schema(record)
    except (ValueError, OSError):
        structured_data = record.get("structured")
        return structured_data if isinstance(structured_data, dict) else {}
