from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from crawler.enrich.models import ExtractiveResult


@lru_cache(maxsize=256)
def _compile(pattern: str) -> re.Pattern[str]:
    return re.compile(pattern, re.IGNORECASE)


class RegexEnricher:
    """Enrich fields by matching regex patterns against source text."""

    def __init__(self, patterns_file: str) -> None:
        self.path = patterns_file
        self.patterns: list[dict[str, Any]] = self._load_patterns(patterns_file)

    @staticmethod
    def _load_patterns(path: str) -> list[dict[str, Any]]:
        resolved = Path(path)
        if not resolved.exists():
            base = Path(__file__).resolve().parent.parent.parent.parent / "references"
            resolved = base / Path(path).name
        if not resolved.exists():
            return []
        data = json.loads(resolved.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return data
        if isinstance(data, dict) and "patterns" in data:
            return data["patterns"]
        return []

    def enrich(self, source_fields: dict[str, Any], source_field_key: str | None = None) -> ExtractiveResult:
        """Apply regex patterns against source text fields."""
        text = self._extract_text(source_fields, source_field_key)
        if not text:
            return ExtractiveResult(
                matched=False,
                source_details=f"regex:{self.path}",
                evidence=list(source_fields.keys()),
            )

        all_matches: list[str] = []
        categories: set[str] = set()
        evidence: list[str] = []

        for pattern_entry in self.patterns:
            regex_str = pattern_entry.get("pattern", "")
            category = pattern_entry.get("category", "unknown")
            label = pattern_entry.get("label", "")
            if not regex_str:
                continue
            try:
                compiled = _compile(regex_str)
                found = compiled.findall(text)
                if found:
                    for match in found:
                        match_str = match if isinstance(match, str) else str(match)
                        if match_str and match_str not in all_matches:
                            all_matches.append(match_str)
                    categories.add(category)
                    evidence.append(f"pattern:{label or regex_str}")
            except re.error:
                continue

        if not all_matches:
            return ExtractiveResult(
                matched=False,
                confidence=0.0,
                source_details=f"regex:{self.path}",
                evidence=[],
            )

        confidence = min(0.5 + 0.1 * len(all_matches), 0.9)
        return ExtractiveResult(
            matched=True,
            values={
                "extracted_items": all_matches,
                "categories": sorted(categories),
            },
            confidence=confidence,
            source_details=f"regex:{self.path}",
            evidence=evidence,
        )

    @staticmethod
    def _extract_text(source_fields: dict[str, Any], source_field_key: str | None) -> str:
        if source_field_key and source_field_key in source_fields:
            val = source_fields[source_field_key]
            return str(val) if val else ""
        parts = []
        for val in source_fields.values():
            if isinstance(val, str) and val.strip():
                parts.append(val)
        return "\n".join(parts)
