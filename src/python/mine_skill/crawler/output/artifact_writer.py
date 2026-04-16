from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _prepare_path(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def write_artifact_bytes(path: Path, data: bytes) -> Path:
    _prepare_path(path).write_bytes(data)
    return path


def write_artifact_text(path: Path, text: str) -> Path:
    _prepare_path(path).write_text(text, encoding="utf-8")
    return path


def write_artifact_json(path: Path, payload: dict[str, Any]) -> Path:
    return write_artifact_text(path, json.dumps(payload, ensure_ascii=False, indent=2, default=str))
