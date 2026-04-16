"""Normalize result model shared across all platform normalizers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class NormalizeResult:
    """Platform-agnostic result of URL normalization.

    Attributes:
        entity_type: Lowercased entity kind (profile, company, job, post, etc.).
        canonical_url: Normalized URL with tracking params stripped.
            Empty string when the URL cannot be recognized.
        identity: Primary key fields for this entity, e.g.
            ``{"vanity": "johndoe"}`` or ``{"job_id": "12345"}``.
        original_url: The raw input before normalization.
        notes: Machine-readable tags describing transformations applied
            (e.g. ``"stripped_query"``, ``"normalized_from_posts_path"``).
    """

    entity_type: str
    canonical_url: str
    identity: dict[str, str] = field(default_factory=dict)
    original_url: str = ""
    notes: tuple[str, ...] = ()

    def primary_key(self) -> dict[str, Any]:
        """Unified key dict suitable for DB upserts or logging."""
        return {"kind": self.entity_type, **self.identity}
