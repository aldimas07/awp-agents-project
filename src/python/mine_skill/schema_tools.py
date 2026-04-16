from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_DIR = ROOT / "schema(1)"
BUNDLE_PATH = SCHEMA_DIR / "_all_schemas.json"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from crawler.enrich.schemas.field_group_registry import FIELD_GROUP_REGISTRY

FIELD_GROUP_DATASET_MAP: dict[tuple[str, str], str] = {
    ("linkedin", "profile"): "linkedin_profiles",
    ("linkedin", "company"): "linkedin_company",
    ("linkedin", "job"): "linkedin_jobs",
    ("linkedin", "post"): "linkedin_posts",
    ("amazon", "product"): "amazon_products",
    ("amazon", "review"): "amazon_reviews",
    ("amazon", "seller"): "amazon_sellers",
    ("arxiv", "paper"): "arxiv",
    ("wikipedia", "article"): "wikipedia",
}

DATE_FIELDS = {"submission_date", "update_date", "date_posted", "article_creation_date", "date_first_available"}
DATE_TIME_FIELDS = {"created_at", "updated_at", "last_major_edit"}
SCORE_BOUNDS: dict[str, tuple[int | float, int | float]] = {
    "engagement_rate": (0, 1),
    "verified_purchase_ratio": (0, 1),
    "fake_review_risk_score": (0, 1),
    "neutrality_score": (0, 1),
    "edit_controversy_score": (0, 1),
    "self_promotion_score": (0, 1),
    "translation_coverage_score": (0, 1),
    "information_freshness_score": (0, 1),
    "seller_health_score": (0, 1),
    "dispute_rate_estimated": (0, 1),
    "review_quality_score": (0, 1),
    "authenticity_score": (0, 1),
    "information_density": (0, 1),
    "author_authority_score": (0, 1),
    "engagement_quality_score": (0, 1),
    "influence_score": (0, 1),
    "interdisciplinary_score": (0, 1),
    "deal_quality_score": (0, 1),
    "listing_quality_score": (0, 1),
    "visual_quality_score": (0, 1),
    "trending_topic_relevance": (0, 1),
    "rating": (0, 5),
    "avg_product_rating": (0, 5),
    "mathematical_complexity_score": (1, 5),
}


class DuplicateKeyError(ValueError):
    pass


@dataclass(slots=True)
class ValidationIssue:
    schema: str
    category: str
    detail: str


def _json_pairs_no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise DuplicateKeyError(key)
        result[key] = value
    return result


def load_schema(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_json_pairs_no_duplicates)


def schema_files() -> list[Path]:
    return sorted(path for path in SCHEMA_DIR.glob("*.schema.json") if path.name != "_all_schemas.json")


def _normalize_property(name: str, spec: dict[str, Any]) -> None:
    prop_type = spec.get("type")
    prop_types = prop_type if isinstance(prop_type, list) else [prop_type]

    if "string" in prop_types:
        if name in DATE_FIELDS and "format" not in spec:
            spec["format"] = "date"
        if name in DATE_TIME_FIELDS and "format" not in spec:
            spec["format"] = "date-time"

    if any(value in prop_types for value in ("number", "integer")) and name in SCORE_BOUNDS:
        minimum, maximum = SCORE_BOUNDS[name]
        spec.setdefault("minimum", minimum)
        spec.setdefault("maximum", maximum)

    if name.endswith("_embedding") and prop_type == "array" and isinstance(spec.get("items"), dict):
        spec.setdefault("minItems", 768)
        spec.setdefault("maxItems", 768)

    if name.endswith("_embeddings") and prop_type == "array" and isinstance(spec.get("items"), dict):
        inner = spec["items"]
        if inner.get("type") == "array" and isinstance(inner.get("items"), dict):
            inner.setdefault("minItems", 768)
            inner.setdefault("maxItems", 768)

    if prop_type == "object" and "properties" not in spec and "additionalProperties" not in spec:
        spec["additionalProperties"] = True

    if prop_type == "array" and isinstance(spec.get("items"), dict):
        items = spec["items"]
        if items.get("type") == "object" and "properties" not in items and "additionalProperties" not in items:
            items["additionalProperties"] = True

    for key in ("properties",):
        nested = spec.get(key)
        if isinstance(nested, dict):
            for nested_name, nested_spec in nested.items():
                if isinstance(nested_spec, dict):
                    _normalize_property(nested_name, nested_spec)

    items = spec.get("items")
    if isinstance(items, dict) and "properties" in items:
        for nested_name, nested_spec in items["properties"].items():
            if isinstance(nested_spec, dict):
                _normalize_property(nested_name, nested_spec)


def normalize_schema(schema: dict[str, Any]) -> dict[str, Any]:
    properties = schema.get("properties")
    if isinstance(properties, dict):
        for name, spec in properties.items():
            if isinstance(spec, dict):
                _normalize_property(name, spec)
    return schema


def generate_bundle() -> dict[str, Any]:
    bundle: dict[str, Any] = {}
    for path in schema_files():
        bundle[path.stem.removesuffix(".schema")] = load_schema(path)
    return bundle


def collect_gap_issues() -> list[ValidationIssue]:
    schemas = {path.stem.removesuffix(".schema"): load_schema(path) for path in schema_files()}
    issues: list[ValidationIssue] = []

    for spec in FIELD_GROUP_REGISTRY.values():
        dataset_name = FIELD_GROUP_DATASET_MAP.get((spec.platform, spec.subdataset))
        if dataset_name is None:
            continue
        schema = schemas.get(dataset_name)
        if not schema:
            issues.append(ValidationIssue(dataset_name, "missing_schema", f"{spec.name} has no matching schema"))
            continue
        properties = schema.get("properties", {})
        for field in spec.output_fields:
            if field.name not in properties:
                issues.append(ValidationIssue(dataset_name, "missing_field", f"{spec.name} -> {field.name}"))
    return issues


def validate_schemas() -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    for path in schema_files():
        try:
            load_schema(path)
        except DuplicateKeyError as exc:
            issues.append(ValidationIssue(path.name, "duplicate_key", str(exc)))
    issues.extend(collect_gap_issues())
    return issues


def cmd_sync() -> int:
    for path in schema_files():
        schema = normalize_schema(load_schema(path))
        path.write_text(json.dumps(schema, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    bundle = generate_bundle()
    BUNDLE_PATH.write_text(json.dumps(bundle, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    issues = validate_schemas()
    if issues:
        print(json.dumps([asdict(issue) for issue in issues], ensure_ascii=False, indent=2))
        return 1

    print(
        json.dumps(
            {
                "synced_files": len(schema_files()),
                "bundle": str(BUNDLE_PATH.relative_to(ROOT)),
                "issues": [],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def cmd_validate() -> int:
    issues = validate_schemas()
    print(json.dumps([asdict(issue) for issue in issues], ensure_ascii=False, indent=2))
    return 1 if issues else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Schema maintenance tools for schema(1)")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("sync", help="normalize schemas, rebuild _all_schemas.json, and validate")
    subparsers.add_parser("validate", help="validate duplicate keys and field-group gaps")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "sync":
        return cmd_sync()
    if args.command == "validate":
        return cmd_validate()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
