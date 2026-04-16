"""Opt-in CSS-based structured extraction for HTML pages."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

from ..models import StructuredFields


class CssExtractionStrategy:
    """Extract structured fields from HTML using an explicit CSS schema."""

    def __init__(self, schema_path: Path):
        self.schema_path = schema_path
        self.schema = json.loads(schema_path.read_text(encoding="utf-8"))

    def extract(
        self,
        *,
        html: str,
        canonical_url: str,
        platform: str,
        resource_type: str,
    ) -> StructuredFields:
        soup = BeautifulSoup(html, "html.parser")
        fields: dict[str, Any] = {}
        field_sources: dict[str, str] = {}

        title = self._extract_value(soup, self.schema.get("title"), canonical_url)
        if title not in (None, "", []):
            field_sources["title"] = self._source_label(self.schema.get("title"))

        description = self._extract_value(soup, self.schema.get("description"), canonical_url)
        if description not in (None, "", []):
            field_sources["description"] = self._source_label(self.schema.get("description"))

        for field_name, spec in self.schema.get("fields", {}).items():
            value = self._extract_value(soup, spec, canonical_url)
            if value in (None, "", []):
                continue
            fields[field_name] = value
            field_sources[field_name] = self._source_label(spec)

        return StructuredFields(
            platform=platform,
            resource_type=resource_type,
            title=str(title) if isinstance(title, str) else None,
            description=str(description) if isinstance(description, str) else None,
            canonical_url=canonical_url,
            platform_fields=fields,
            field_sources=field_sources,
        )

    def _extract_value(self, soup: BeautifulSoup, spec: Any, canonical_url: str) -> Any:
        if not isinstance(spec, dict):
            return None
        selector = spec.get("selector")
        if not selector:
            return None

        nodes = soup.select(selector)
        if not nodes:
            return None

        values = [self._extract_node_value(node, spec, canonical_url) for node in nodes]
        values = [value for value in values if value not in (None, "")]
        if not values:
            return None
        if spec.get("multiple"):
            return values
        return values[0]

    def _extract_node_value(self, node: Tag, spec: dict[str, Any], canonical_url: str) -> str | None:
        attribute = spec.get("attribute")
        if attribute:
            raw = node.get(attribute)
            if raw is None:
                return None
            value = str(raw).strip()
            if attribute in {"href", "src"}:
                return urljoin(canonical_url, value)
            return value
        return node.get_text(" ", strip=True) or None

    def _source_label(self, spec: Any) -> str:
        if not isinstance(spec, dict):
            return "css"
        selector = spec.get("selector", "")
        attribute = spec.get("attribute")
        if attribute:
            return f"css:{selector}@{attribute}"
        return f"css:{selector}"
