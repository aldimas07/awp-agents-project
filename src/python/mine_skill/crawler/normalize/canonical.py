from __future__ import annotations


def build_canonical_record(platform: str, entity_type: str, canonical_url: str) -> dict:
    return {
        "platform": platform,
        "entity_type": entity_type,
        "resource_type": entity_type,
        "canonical_url": canonical_url,
        "status": "success",
        "stage": "normalized",
        "retryable": False,
        "error_code": None,
        "next_action": "none",
        "artifacts": [],
        "errors": [],
        "metadata": {},
        "plain_text": "",
        "markdown": "",
        "document_blocks": [],
        "structured": {},
    }
