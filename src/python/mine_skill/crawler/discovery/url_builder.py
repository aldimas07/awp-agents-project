from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import quote

from crawler.discovery.contracts import DiscoveryMode, DiscoveryRecord


ROOT_DIR = Path(__file__).resolve().parents[2]
TEMPLATE_PATH = ROOT_DIR / "references" / "url_templates.json"
FIELD_MAPPING_PATH = ROOT_DIR / "references" / "field_mappings.json"


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _find_field(record: dict, aliases: dict, target_field: str) -> str:
    for candidate in aliases.get(target_field, [target_field]):
        value = record.get(candidate)
        if value:
            return str(value)
    raise KeyError(target_field)


def _normalize_value(field: str, value: str) -> str:
    if field == "title":
        return quote(value.replace(" ", "_"), safe="_()")
    if field in {"query"}:
        return quote(value, safe="")
    if field == "search_type":
        mapping = {
            "company": "companies",
            "companies": "companies",
            "profile": "people",
            "people": "people",
            "job": "jobs",
            "jobs": "jobs",
            "post": "content",
            "content": "content",
        }
        normalized = mapping.get(value.lower().strip())
        if normalized is None:
            raise ValueError(f"unsupported linkedin search_type: {value}")
        return normalized
    return value


def build_url(record: dict) -> dict:
    platform = record.get("platform", "")
    resource_type = record.get("resource_type", "")
    if not platform or not resource_type:
        raise ValueError(f"record missing platform or resource_type: {list(record.keys())}")
    templates = _load_json(TEMPLATE_PATH)
    mappings = _load_json(FIELD_MAPPING_PATH)
    platform_templates = templates.get(platform)
    if not platform_templates or resource_type not in platform_templates:
        raise ValueError(f"no URL template for {platform}/{resource_type}")
    template_config = platform_templates[resource_type]
    alias_config = mappings.get(platform, {}).get(resource_type, {})

    fields: dict[str, str] = {}
    for field_name in template_config.get("required_fields", []):
        value = _find_field(record, alias_config, field_name)
        fields[field_name] = _normalize_value(field_name, value)

    canonical_url = template_config["canonical_template"].format(**fields)
    artifacts = {
        name: template.format(**fields)
        for name, template in template_config.get("artifact_templates", {}).items()
    }

    return {
        "platform": platform,
        "resource_type": resource_type,
        "canonical_url": canonical_url,
        "artifacts": artifacts,
        "fields": fields,
    }


def build_seed_records(record: dict) -> list[DiscoveryRecord]:
    url = record.get("url")
    if isinstance(url, str) and url:
        inferred = _infer_identity_from_url(record, url)
        if inferred is not None:
            return [
                DiscoveryRecord(
                    platform=str(record.get("platform") or "generic"),
                    resource_type=str(record.get("resource_type") or "page"),
                    discovery_mode=DiscoveryMode.CANONICALIZED_INPUT,
                    canonical_url=inferred["canonical_url"],
                    identity=inferred["identity"],
                    source_seed=record,
                    discovered_from=None,
                    metadata={"artifacts": dict(record.get("artifacts") or {})},
                )
            ]

    if record.get("canonical_url"):
        canonical_url = str(record["canonical_url"])
        identity = {
            key: str(value)
            for key, value in record.items()
            if key not in {"plain_text", "markdown", "structured", "metadata", "artifacts"}
            and value not in (None, "", [], {})
        }
        return [
            DiscoveryRecord(
                platform=str(record.get("platform") or "generic"),
                resource_type=str(record.get("resource_type") or "page"),
                discovery_mode=DiscoveryMode.CANONICALIZED_INPUT,
                canonical_url=canonical_url,
                identity=identity or {"canonical_url": canonical_url},
                source_seed=record,
                discovered_from=None,
                metadata={"artifacts": dict(record.get("artifacts") or {})},
            )
        ]

    discovered = build_url(record)
    return [
        DiscoveryRecord(
            platform=str(discovered.get("platform") or record.get("platform") or "generic"),
            resource_type=str(discovered.get("resource_type") or record.get("resource_type") or "page"),
            discovery_mode=DiscoveryMode.TEMPLATE_CONSTRUCTION,
            canonical_url=discovered["canonical_url"],
            identity=dict(discovered["fields"]),
            source_seed=record,
            discovered_from=None,
            metadata={"artifacts": discovered["artifacts"]},
        )
    ]


def _infer_identity_from_url(record: dict, url: str) -> dict[str, object] | None:
    platform = str(record.get("platform") or "")
    resource_type = str(record.get("resource_type") or "")
    if platform != "linkedin":
        return None

    patterns = (
        ("profile", r"^https://www\.linkedin\.com/in/([^/]+)/?$", "public_identifier"),
        ("company", r"^https://www\.linkedin\.com/company/([^/]+)/?$", "company_slug"),
        ("job", r"^https://www\.linkedin\.com/jobs/view/(\d+)/?$", "job_id"),
        ("post", r"^https://www\.linkedin\.com/feed/update/(urn:li:activity:\d+)/?$", "activity_urn"),
    )
    for expected_type, pattern, field_name in patterns:
        if resource_type != expected_type:
            continue
        match = re.match(pattern, url)
        if match:
            return {
                "canonical_url": url,
                "identity": {field_name: match.group(1)},
            }
    return None
