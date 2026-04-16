from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from crawler.enrich.models import ExtractiveResult


def _normalize_key(key: str) -> str:
    """Normalize a lookup key for fuzzy matching."""
    return key.strip().lower().replace("-", " ").replace("_", " ")


class LookupEnricher:
    """Enrich fields via lookup table: exact match -> fuzzy match -> fail."""

    def __init__(self, lookup_table_path: str) -> None:
        self.path = lookup_table_path
        self.lookup_table: dict[str, Any] = self._load_table(lookup_table_path)
        self._normalized_index: dict[str, str] = {
            _normalize_key(k): k for k in self.lookup_table
        }

    @staticmethod
    def _load_table(path: str) -> dict[str, Any]:
        resolved = Path(path)
        if not resolved.exists():
            base = Path(__file__).resolve().parent.parent.parent.parent / "references" / "lookup_tables"
            resolved = base / Path(path).name
        if not resolved.exists():
            return {}
        return json.loads(resolved.read_text(encoding="utf-8"))

    def enrich(self, source_fields: dict[str, Any], source_field_key: str | None = None) -> ExtractiveResult:
        """Look up values from the table.

        Strategy: exact match -> normalized fuzzy match -> no match.
        """
        raw_value = self._extract_lookup_value(source_fields, source_field_key)
        if raw_value is None:
            return ExtractiveResult(
                matched=False,
                source_details=f"lookup:{self.path}",
                evidence=list(source_fields.keys()),
            )

        # Exact match
        if raw_value in self.lookup_table:
            entry = self.lookup_table[raw_value]
            return self._build_result(entry, raw_value, confidence=1.0)

        # Normalized fuzzy match
        normalized = _normalize_key(raw_value)
        if normalized in self._normalized_index:
            original_key = self._normalized_index[normalized]
            entry = self.lookup_table[original_key]
            return self._build_result(entry, raw_value, confidence=0.85)

        # Prefix match: find longest matching prefix
        best_match = self._prefix_match(normalized)
        if best_match is not None:
            original_key, score = best_match
            entry = self.lookup_table[original_key]
            return self._build_result(entry, raw_value, confidence=score)

        return ExtractiveResult(
            matched=False,
            confidence=0.0,
            source_details=f"lookup:{self.path}",
            evidence=[raw_value],
        )

    def _extract_lookup_value(self, source_fields: dict[str, Any], source_field_key: str | None) -> str | None:
        if source_field_key and source_field_key in source_fields:
            val = source_fields[source_field_key]
            return str(val).strip() if val else None
        for val in source_fields.values():
            if val and isinstance(val, str):
                return val.strip()
        return None

    def _prefix_match(self, normalized: str) -> tuple[str, float] | None:
        best_key: str | None = None
        best_len = 0
        for norm_key, original_key in self._normalized_index.items():
            if normalized.startswith(norm_key) or norm_key.startswith(normalized):
                overlap = min(len(norm_key), len(normalized))
                if overlap > best_len and overlap >= 4:
                    best_len = overlap
                    best_key = original_key
        if best_key is None:
            return None
        score = best_len / max(len(normalized), 1)
        return best_key, min(score * 0.8, 0.75)

    def _build_result(self, entry: Any, raw_value: str, confidence: float) -> ExtractiveResult:
        if isinstance(entry, dict):
            return ExtractiveResult(
                matched=True,
                values=dict(entry),
                confidence=confidence,
                source_details=f"lookup:{self.path}",
                evidence=[raw_value],
            )
        return ExtractiveResult(
            matched=True,
            values={"value": entry},
            confidence=confidence,
            source_details=f"lookup:{self.path}",
            evidence=[raw_value],
        )
