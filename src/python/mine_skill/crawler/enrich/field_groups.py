from __future__ import annotations

from crawler.enrich.schemas.field_group_registry import list_field_groups


def supported_field_groups() -> list[str]:
    return list_field_groups()
