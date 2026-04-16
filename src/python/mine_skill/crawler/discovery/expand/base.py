"""Expand result model shared across all platform expanders."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ExpandResult:
    """Result of page expansion."""

    urls: list[str] = field(default_factory=list)
    buckets: dict[str, list[str]] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
