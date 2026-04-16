from __future__ import annotations

import argparse
import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Sequence

from .core.pipeline import run_command
from .contracts import CrawlerConfig, CrawlCommand
from .output import read_json_file, read_jsonl_file
from .output.jsonl_writer import write_jsonl
from .output.summary_writer import build_summary, write_manifest, write_summary


def _parse_command(value: str) -> CrawlCommand:  # Parse CLI string into CrawlCommand enum
    try:
        return CrawlCommand(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"invalid command {value!r}; expected one of: discover-crawl, crawl, run, enrich, fill-enrichment"
        ) from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="crawler")
    subparsers = parser.add_subparsers(dest="command", required=True)

    for command in CrawlCommand:
        subparser = subparsers.add_parser(command.value)
        subparser.set_defaults(command=command)
        subparser.add_argument("--input", dest="input_path", type=Path, required=True)
        subparser.add_argument("--output", dest="output_dir", type=Path, required=True)
        subparser.add_argument("--cookies", dest="cookies_path", type=Path)
        subparser.add_argument(
            "--css-schema",
            dest="css_schema_path",
            type=Path,
            help="Path to a JSON file describing opt-in CSS field extraction for HTML pages",
        )
        subparser.add_argument("--extract-llm-schema", dest="extract_llm_schema_path", type=Path)
        subparser.add_argument("--enrich-llm-schema", dest="enrich_llm_schema_path", type=Path)
        subparser.add_argument("--model-config", dest="model_config_path", type=Path)
        subparser.add_argument(
            "--use-openclaw",
            action="store_true",
            help="Use a locally running OpenClaw Gateway with auto-discovered auth token",
        )
        subparser.add_argument(
            "--auto-login",
            action="store_true",
            help="For auth-gated platforms, run the built-in browser login flow and export session state",
        )
        subparser.add_argument("--platform")
        subparser.add_argument("--backend")
        subparser.add_argument("--preferred-backend", dest="preferred_backend")
        subparser.add_argument("--resume", action="store_true")
        subparser.add_argument("--artifacts-dir", dest="artifacts_dir", type=Path)
        subparser.add_argument("--strict", action="store_true")
        subparser.add_argument("--field-group", dest="field_groups", action="append", default=[])
        subparser.add_argument(
            "--max-chunk-tokens",
            dest="max_chunk_tokens",
            type=int,
            default=512,
            help="Maximum tokens per chunk for ExtractPipeline (default: 512)",
        )
        subparser.add_argument(
            "--chunk-overlap",
            dest="chunk_overlap",
            type=int,
            default=50,
            help="Overlap tokens between chunks (default: 50)",
        )
        subparser.add_argument(
            "--concurrency",
            type=int,
            default=3,
            help="Max parallel record processing (default: 3)",
        )
        # Discovery options (for discover-crawl)
        subparser.add_argument(
            "--max-depth",
            dest="max_depth",
            type=int,
            default=2,
            help="Maximum crawl depth for discovery (default: 2)",
        )
        subparser.add_argument(
            "--max-pages",
            dest="max_pages",
            type=int,
            default=100,
            help="Maximum pages to discover (default: 100)",
        )
        subparser.add_argument(
            "--sitemap-mode",
            dest="sitemap_mode",
            choices=["include", "only", "skip"],
            default="include",
            help="Sitemap handling mode (default: include)",
        )

    # fill-enrichment command: agent fills pending_agent results with LLM responses
    fill_parser = subparsers.add_parser(
        "fill-enrichment",
        help="Fill pending_agent enrichment results with agent-executed LLM responses",
    )
    fill_parser.set_defaults(command="fill-enrichment")
    fill_parser.add_argument("--records", dest="records_path", type=Path, required=True,
                             help="Path to records.jsonl with pending_agent results")
    fill_parser.add_argument("--responses", dest="responses_path", type=Path, required=True,
                             help="Path to JSON file with LLM responses keyed by record identifier and field_group")

    export_parser = subparsers.add_parser(
        "export-submissions",
        help="Convert crawler records.jsonl into Platform Service CreateSubmissionsRequest JSON",
    )
    export_parser.set_defaults(command="export-submissions")
    export_parser.add_argument("--input", dest="input_path", type=Path, required=True)
    export_parser.add_argument("--output", dest="output_path", type=Path, required=True)
    export_parser.add_argument("--dataset-id", dest="dataset_id", required=True)
    export_parser.add_argument(
        "--generated-at",
        dest="generated_at",
        help="Fallback crawl timestamp for records missing crawl_timestamp; defaults to sibling run_manifest.json generated_at when available",
    )

    return parser


def parse_args(argv: Sequence[str] | None = None) -> CrawlerConfig:
    namespace = build_parser().parse_args(argv)
    values = vars(namespace).copy()
    command = values.pop("command")
    if isinstance(command, CrawlCommand):
        values["command"] = command
    else:
        values["command"] = _parse_command(str(command))
    return CrawlerConfig.from_mapping(values)


def main(argv: Sequence[str] | None = None) -> int:
    namespace = build_parser().parse_args(argv)

    # Handle fill-enrichment command separately
    if namespace.command == "fill-enrichment":
        return _fill_enrichment(namespace.records_path, namespace.responses_path)
    if namespace.command == "export-submissions":
        return _export_submissions(namespace.input_path, namespace.output_path, namespace.dataset_id, namespace.generated_at)

    config = parse_args(argv)
    config.output_dir.mkdir(parents=True, exist_ok=True)
    records, errors = run_command(config)

    write_jsonl(config.output_dir / "records.jsonl", records, append=config.resume)
    write_jsonl(config.output_dir / "errors.jsonl", errors, append=config.resume)
    retryable_errors = [error for error in errors if error.get("retryable")]
    if retryable_errors:
        write_jsonl(config.output_dir / "dlq.jsonl", retryable_errors, append=config.resume)
    summary = build_summary(records, errors)
    write_summary(config.output_dir / "summary.json", summary)
    write_manifest(
        config.output_dir / "run_manifest.json",
        {
            "command": config.command.value,
            "input_path": str(config.input_path),
            "output_dir": str(config.output_dir),
            "artifacts_dir": str(config.artifacts_dir or (config.output_dir / "artifacts")),
            "resume": config.resume,
            "strict": config.strict,
            "backend": config.backend,
            "concurrency": config.concurrency,
            "generated_at": datetime.now(UTC).isoformat(),
        },
    )
    write_manifest(
        config.output_dir / "runtime_metrics.json",
        {
            "records_succeeded": len(records),
            "records_failed": len(errors),
            "retryable_errors": len(retryable_errors),
            "concurrency": config.concurrency,
            "resume": config.resume,
            "generated_at": datetime.now(UTC).isoformat(),
        },
    )
    if errors and config.command in {CrawlCommand.ENRICH, CrawlCommand.RUN}:
        return 1
    return 1 if config.strict and errors else 0


def _fill_enrichment(records_path: Path, responses_path: Path) -> int:
    """Fill pending_agent enrichment results with agent-executed LLM responses.

    Args:
        records_path: Path to records.jsonl with pending_agent results
        responses_path: Path to JSON with responses keyed by "{record_id}:{field_group}"

    Returns:
        0 on success, 1 on error
    """
    from .enrich.pipeline import EnrichPipeline

    if not records_path.exists():
        print(f"Error: records file not found: {records_path}")
        return 1
    if not responses_path.exists():
        print(f"Error: responses file not found: {responses_path}")
        return 1

    # Load responses
    responses = read_json_file(responses_path)

    # Load and update records
    pipeline = EnrichPipeline(cache_dir=records_path.parent / ".cache" / "enrich")
    updated_records = []
    filled_count = 0

    for record in read_jsonl_file(records_path):
        enrichment = record.get("enrichment", {})
        candidate_ids = []
        for candidate in (
            record.get("doc_id"),
            enrichment.get("doc_id") if isinstance(enrichment, dict) else None,
            record.get("canonical_url"),
        ):
            if candidate and candidate not in candidate_ids:
                candidate_ids.append(candidate)

        # Check each enrichment result for pending_agent status
        if "enrichment" in record and "enrichment_results" in record["enrichment"]:
            for field_group, result in record["enrichment"]["enrichment_results"].items():
                if result.get("status") == "pending_agent":
                    response_text = None
                    for candidate_id in candidate_ids:
                        key = f"{candidate_id}:{field_group}"
                        if key in responses:
                            response_text = responses[key]
                            break
                    if response_text is not None:
                        # Fill with agent response
                        filled = pipeline.fill_pending_agent_result(field_group, response_text, document=record)
                        record["enrichment"]["enrichment_results"][field_group] = filled.to_dict()
                        # Also update enriched_fields
                        for field in filled.fields:
                            record["enrichment"].setdefault("enriched_fields", {})[field.field_name] = field.value
                        filled_count += 1

        updated_records.append(record)

    # Write back atomically
    content = "\n".join(json.dumps(r, ensure_ascii=False) for r in updated_records) + "\n"
    fd, tmp = tempfile.mkstemp(dir=str(records_path.parent), suffix=".tmp")
    try:
        os.write(fd, content.encode("utf-8"))
        os.close(fd)
        fd = -1
        os.replace(tmp, str(records_path))
    except BaseException:
        if fd >= 0:
            os.close(fd)
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    print(f"Filled {filled_count} pending_agent enrichment results")
    return 0


def _export_submissions(
    input_path: Path,
    output_path: Path,
    dataset_id: str,
    generated_at: str | None,
) -> int:
    from .submission_export import export_submission_request

    export_submission_request(
        input_path=input_path,
        output_path=output_path,
        dataset_id=dataset_id,
        generated_at=generated_at,
    )
    return 0
