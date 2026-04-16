from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)
from typing import TYPE_CHECKING, Any

from crawler.contracts import CrawlCommand, CrawlerConfig
from crawler.core.auth import (
    build_auth_required_error,
    build_error_from_fetch_error,
    classify_auth_failure,
    refresh_storage_state_path,
    resolve_storage_state_path,
)
from crawler.enrich.input_normalizer import build_enrich_input
from crawler.fetch.error_classifier import FetchError
from crawler.output import read_json_file, read_jsonl_file

if TYPE_CHECKING:
    from crawler.discovery.contracts import DiscoveryCandidate, DiscoveryRecord


def run_command(config: CrawlerConfig) -> tuple[list[dict], list[dict]]:
    """Run the crawler pipeline.

    Uses the default fetch/extract/enrich pipeline for all crawl, run, and enrich commands.
    """
    if config.command is CrawlCommand.DISCOVER_CRAWL:
        return _run_discovery_crawl_pipeline(config)
    return _run_new_pipeline(config)


def _run_discovery_crawl_pipeline(config: CrawlerConfig) -> tuple[list[dict], list[dict]]:
    """Run the discovery crawl pipeline."""
    return asyncio.run(_run_discovery_crawl_pipeline_async(config))


async def _run_discovery_crawl_pipeline_async(config: CrawlerConfig) -> tuple[list[dict], list[dict]]:
    """Async implementation of discovery crawl pipeline."""
    from crawler.discovery.adapters.registry import get_discovery_adapter
    from crawler.discovery.contracts import CrawlOptions, DiscoveryCandidate, DiscoveryMode, DiscoveryRecord
    from crawler.discovery.runner import run_discover_crawl
    from crawler.fetch.engine import FetchEngine
    from crawler.fetch.session_store import SessionStore
    from crawler.platforms.registry import get_platform_adapter

    errors: list[dict[str, Any]] = []

    input_records = _read_jsonl(config.input_path)
    options = CrawlOptions(
        max_depth=config.max_depth,
        max_pages=config.max_pages,
        sitemap_mode=config.sitemap_mode,
        max_concurrency=config.concurrency,
    )

    # Build candidates from input
    seeds: list[DiscoveryCandidate] = []
    for input_record in input_records:
        seeds.extend(_build_discovery_candidates(input_record, get_discovery_adapter))

    session_root = config.output_dir / ".sessions"
    session_root.mkdir(parents=True, exist_ok=True)

    session_store = SessionStore(session_root)

    async with FetchEngine(session_root) as fetch_engine:
        async def fetch_fn(target: DiscoveryCandidate | str) -> dict[str, Any]:
            candidate_fields: dict[str, Any] = {}
            storage_state_path: str | None = None
            if isinstance(target, DiscoveryCandidate):
                url = target.canonical_url or ""
                platform = target.platform
                resource_type = target.resource_type
                candidate_fields = dict(target.fields)
            else:
                url = str(target)
                platform = "generic"
                resource_type = "page"
            adapter = get_platform_adapter(platform)
            requires_auth = bool(getattr(adapter, "requires_auth", False))
            storage_state_path = resolve_storage_state_path(
                config=config,
                platform=platform,
                requires_auth=requires_auth,
                session_store=session_store,
            )
            if requires_auth and storage_state_path is None:
                auth_error = build_auth_required_error(
                    platform=platform,
                    resource_type=resource_type,
                    auto_login_enabled=config.auto_login,
                )
                err = RuntimeError(auth_error["message"])
                err.fetch_error = FetchError(  # type: ignore[attr-defined]
                    auth_error["error_code"],
                    auth_error["next_action"].replace(" ", "_"),
                    auth_error["message"],
                    auth_error["retryable"],
                )
                raise err

            last_exc: Exception | None = None
            for fetch_attempt in range(2):
                try:
                    preferred_backend = getattr(adapter, "default_backend", None)
                    fallback_chain = getattr(adapter, "fallback_backends", ())
                    record = {
                        "platform": platform,
                        "resource_type": resource_type,
                        **candidate_fields,
                    }
                    discovered = {
                        "canonical_url": url,
                        "fields": candidate_fields,
                    }
                    api_fetcher = None
                    if preferred_backend == "api":
                        api_fetcher = lambda canonical_url, *, _record=record, _discovered=discovered, _adapter=adapter, _storage_state_path=storage_state_path: _adapter.fetch_record(
                            _record,
                            {**_discovered, "canonical_url": canonical_url},
                            "api",
                            _storage_state_path,
                        )
                    result = await fetch_engine.fetch(
                        url=url,
                        platform=platform,
                        resource_type=resource_type,
                        requires_auth=requires_auth,
                        preferred_backend=preferred_backend,
                        fallback_chain=fallback_chain,
                        api_fetcher=api_fetcher,
                    )
                    return result.to_legacy_dict()
                except Exception as exc:
                    last_exc = exc
                    fetch_error = getattr(exc, "fetch_error", None)
                    should_refresh = (
                        fetch_attempt == 0
                        and config.auto_login
                        and requires_auth
                        and fetch_error is not None
                        and fetch_error.error_code == "AUTH_EXPIRED"
                    )
                    if not should_refresh:
                        raise
                    refreshed_storage_state_path = refresh_storage_state_path(
                        config=config,
                        platform=platform,
                        requires_auth=requires_auth,
                        session_store=session_store,
                    )
                    if refreshed_storage_state_path is None:
                        raise
                    storage_state_path = refreshed_storage_state_path
                    continue
            raise last_exc or RuntimeError(f"discover fetch failed for {url}")

        try:
            records = await run_discover_crawl(
                seeds=seeds,
                fetch_fn=fetch_fn,
                options=options,
                adapter_resolver=get_discovery_adapter,
                state_dir=config.output_dir / ".discovery_state",
                resume=config.resume,
                errors=errors,
            )
        except Exception as exc:
            fetch_error = getattr(exc, "fetch_error", None)
            if fetch_error is not None:
                errors.append(
                    build_error_from_fetch_error(
                        platform="generic",
                        resource_type="page",
                        fetch_error=fetch_error,
                        stage="discovery_crawl",
                        message=str(exc),
                        exception=exc,
                    )
                )
            else:
                errors.append({
                    "platform": "generic",
                    "resource_type": "page",
                    "stage": "discovery_crawl",
                    "status": "failed",
                    "error_code": "DISCOVERY_CRAWL_FAILED",
                    "retryable": False,
                    "next_action": "inspect error and retry",
                    "message": str(exc),
                })
            records = []

    return records, errors

def _run_new_pipeline(config: CrawlerConfig) -> tuple[list[dict], list[dict]]:
    """Run the new 3-layer pipeline: FetchEngine -> ExtractPipeline -> EnrichPipeline."""
    return asyncio.run(_run_new_pipeline_async(config))


async def _run_new_pipeline_async(config: CrawlerConfig) -> tuple[list[dict], list[dict]]:
    """Async implementation of the new pipeline."""
    import logging
    import signal

    from crawler.core.progress import ProgressTracker
    from crawler.extract.pipeline import ExtractPipeline
    from crawler.enrich.pipeline import EnrichPipeline
    from crawler.fetch.engine import FetchEngine
    from crawler.fetch.session_store import SessionStore
    from crawler.discovery.url_builder import build_seed_records
    from crawler.platforms.registry import get_platform_adapter
    from crawler.normalize.canonical import build_canonical_record
    from crawler.output.artifact_writer import write_artifact_bytes, write_artifact_json, write_artifact_text
    from crawler.schema_runtime.model_config import load_model_config

    logger = logging.getLogger(__name__)
    results: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    # Read input records
    records = _read_jsonl(config.input_path)

    model_config = load_model_config(config.model_config_path, use_openclaw=config.use_openclaw)
    enrich_pipeline = EnrichPipeline(
        enrich_llm_schema_path=config.enrich_llm_schema_path,
        model_config=model_config,
        cache_dir=config.output_dir / ".cache" / "enrich",
    )
    if config.command is CrawlCommand.ENRICH:
        return await _run_new_enrich_only_pipeline(records, config, enrich_pipeline)

    deduped_records: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    for record in records:
        seeds = build_seed_records(record)
        canonical_url = seeds[0].canonical_url if seeds else None
        if canonical_url and canonical_url in seen_urls:
            continue
        if canonical_url:
            seen_urls.add(canonical_url)
        deduped_records.append(record)
    records = deduped_records

    # Initialize pipelines
    session_root = config.output_dir / ".sessions"
    session_root.mkdir(parents=True, exist_ok=True)
    artifact_root = config.artifacts_dir or (config.output_dir / "artifacts")
    session_store = SessionStore(session_root)
    extract_pipeline = ExtractPipeline(
        max_chunk_tokens=config.max_chunk_tokens,
        min_chunk_tokens=100,
        overlap_tokens=config.chunk_overlap,
        css_schema_path=config.css_schema_path,
        extract_llm_schema_path=config.extract_llm_schema_path,
        model_config=model_config,
    )

    # Always track progress; only load prior state when --resume is set.
    progress = ProgressTracker(config.output_dir, load_existing=config.resume)
    if not config.resume:
        progress.reset()

    # Flush progress on termination for graceful shutdown.
    _prev_handler = signal.getsignal(signal.SIGINT)
    _prev_term_handler = signal.getsignal(signal.SIGTERM) if hasattr(signal, "SIGTERM") else None

    def _flush_and_delegate(sig: int, frame: Any) -> None:
        signal_name = signal.Signals(sig).name if sig in signal.Signals._value2member_map_ else str(sig)
        logger.info("%s received, flushing progress before exit", signal_name)
        progress.flush()
        previous = _prev_handler if sig == signal.SIGINT else _prev_term_handler
        if callable(previous) and previous not in (signal.SIG_DFL, signal.SIG_IGN):
            previous(sig, frame)
            return
        if sig == signal.SIGTERM:
            raise SystemExit(0)
        raise KeyboardInterrupt

    signal.signal(signal.SIGINT, _flush_and_delegate)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _flush_and_delegate)

    # Concurrency control
    semaphore = asyncio.Semaphore(config.concurrency)

    async def _process_one(idx: int, record: dict) -> tuple[dict | None, dict | None]:
        """Process a single record. Returns (result, error)."""
        platform = record.get("platform", "unknown")
        resource_type = record.get("resource_type", "unknown")
        storage_state_path: str | None = None

        try:
            # Step 1: URL Discovery
            adapter = get_platform_adapter(platform)
            seed_records = build_seed_records(record)
            if not seed_records:
                logger.warning("[%d] No seed records generated for %s", idx, record.get("url", "?"))
                return None, None
            discovered = _discovered_from_seed(seed_records[0])
            url = discovered["canonical_url"]

            # Skip if already completed (resume mode)
            if progress.is_done(url):
                logger.info("[%d] Skipping (already done): %s", idx, url)
                return None, None

            slug = _make_slug(idx, url)

            # Step 2: Fetch (using new FetchEngine)
            requires_auth = getattr(adapter, "requires_auth", False)
            storage_state_path = resolve_storage_state_path(
                config=config,
                platform=platform,
                requires_auth=requires_auth,
                session_store=session_store,
            )
            if requires_auth and storage_state_path is None:
                return None, build_auth_required_error(
                    platform=platform,
                    resource_type=resource_type,
                    auto_login_enabled=config.auto_login,
                )

            # For API backends, we need the adapter's API fetcher.
            # --backend forces a single backend (no fallback); --preferred-backend
            # sets the initial backend while keeping the adapter fallback chain.
            effective_override = config.backend
            effective_preferred = config.preferred_backend if config.backend is None else None
            initial_backend = adapter.resolve_backend(record, config.backend or config.preferred_backend, retry_count=0)
            adapter_fallback = list(getattr(adapter, "fallback_backends", ()))
            last_fetch_exc: Exception | None = None
            for fetch_attempt in range(2):
                try:
                    if initial_backend == "api":
                        raw_result = await fetch_engine.fetch(
                            url=url,
                            platform=platform,
                            resource_type=resource_type,
                            requires_auth=requires_auth,
                            override_backend=effective_override,
                            preferred_backend=effective_preferred or (initial_backend if effective_override is None else None),
                            fallback_chain=adapter_fallback,
                            api_fetcher=lambda _url, **_kwargs: adapter.fetch_record(
                                record,
                                discovered,
                                "api",
                                storage_state_path,
                            ),
                        )
                    else:
                        raw_result = await fetch_engine.fetch(
                            url=url,
                            platform=platform,
                            resource_type=resource_type,
                            requires_auth=requires_auth,
                            override_backend=effective_override,
                            preferred_backend=effective_preferred,
                            fallback_chain=adapter_fallback if (effective_preferred or effective_override is None) else None,
                        )
                    fetch_result = raw_result.to_legacy_dict()
                    break
                except Exception as exc:
                    last_fetch_exc = exc
                    fetch_error = getattr(exc, "fetch_error", None)
                    should_refresh = (
                        fetch_attempt == 0
                        and config.auto_login
                        and requires_auth
                        and fetch_error is not None
                        and fetch_error.error_code == "AUTH_EXPIRED"
                    )
                    if not should_refresh:
                        raise
                    refreshed_storage_state_path = refresh_storage_state_path(
                        config=config,
                        platform=platform,
                        requires_auth=requires_auth,
                        session_store=session_store,
                    )
                    if refreshed_storage_state_path is None:
                        raise
                    storage_state_path = refreshed_storage_state_path
                    logger.info("Refreshed %s session after auth expiry, retrying %s", platform, url)
            else:
                raise last_fetch_exc or RuntimeError(f"fetch failed for {url}")

            # Persist fetch artifacts
            fetch_artifacts = _persist_fetch_artifacts_new(
                artifact_root=artifact_root,
                slug=slug,
                fetched=fetch_result,
                root_for_rel=config.output_dir,
            )

            # Step 3: Extract (using new ExtractPipeline)
            extracted_doc = await asyncio.to_thread(
                extract_pipeline.extract,
                fetch_result,
                platform,
                resource_type,
            )
            legacy_extracted = _build_legacy_compatible_extracted(
                adapter=adapter,
                record=record,
                discovered=discovered,
                fetch_result=fetch_result,
                extracted_doc=extracted_doc,
            )
            # Persist extraction artifacts
            extraction_artifacts = _persist_extraction_artifacts(
                artifact_root=artifact_root,
                slug=slug,
                extracted=extracted_doc,
                root_for_rel=config.output_dir,
            )

            normalized_structured = adapter.normalize_record(
                record,
                discovered,
                legacy_extracted,
                {"document_blocks": extracted_doc.structured.platform_fields.get("pdf_document_blocks", [])},
            )

            # Step 4: Enrich (if field_groups specified or running full pipeline).
            # "none" is a sentinel: the worker passes --field-group none when no
            # LLM backend is available, explicitly skipping enrichment so the
            # subprocess doesn't block for minutes timing out on every field group.
            _skip_enrich = len(config.field_groups) == 1 and config.field_groups[0] == "none"
            if config.command in (CrawlCommand.RUN, CrawlCommand.ENRICH) and not _skip_enrich:
                enrichment_request = adapter.build_enrichment_request(record, config.field_groups)
                field_groups = list(enrichment_request.get("field_groups") or ["summaries"])
                # Prepare document for enrichment
                enrich_seed = {
                    "doc_id": extracted_doc.doc_id,
                    "canonical_url": url,
                    "platform": platform,
                    "resource_type": resource_type,
                    "plain_text": extracted_doc.full_text,
                    "markdown": extracted_doc.full_markdown,
                    "structured": extracted_doc.structured.platform_fields,
                    "title": extracted_doc.structured.title,
                    "description": extracted_doc.structured.description,
                }
                if isinstance(normalized_structured, dict):
                    enrich_seed.update({key: value for key, value in normalized_structured.items() if value not in (None, "", [], {})})
                    structured_fields = enrich_seed.get("structured")
                    if isinstance(structured_fields, dict):
                        enrich_seed["structured"] = {
                            **structured_fields,
                            **{key: value for key, value in normalized_structured.items() if value not in (None, "", [], {})},
                        }
                enrich_input = _build_enrich_input_from_record(enrich_seed)
                enriched = await enrich_pipeline.enrich(enrich_input, field_groups)
                enrichment_result = enriched.to_dict()
            else:
                enrichment_result = None

            # Build final record
            normalized = build_canonical_record(
                platform=platform,
                entity_type=resource_type,
                canonical_url=url,
            )
            normalized["artifacts"] = fetch_artifacts + extraction_artifacts
            normalized["discovery"] = discovered
            normalized["source"] = record
            normalized["metadata"] = legacy_extracted.get("metadata", {})
            normalized["plain_text"] = extracted_doc.full_text
            normalized["markdown"] = extracted_doc.full_markdown
            normalized["structured"] = dict(extracted_doc.structured.platform_fields)
            normalized["document_blocks"] = legacy_extracted.get("document_blocks", [])
            if legacy_extracted.get("extractor") not in (None, ""):
                normalized["extractor"] = legacy_extracted["extractor"]
            normalized["chunks"] = [chunk.to_dict() for chunk in extracted_doc.chunks]
            normalized["extraction_quality"] = {
                "content_ratio": extracted_doc.quality.content_ratio,
                "noise_removed": extracted_doc.quality.noise_removed,
                "chunking_strategy": extracted_doc.quality.chunking_strategy,
                "total_chunks": extracted_doc.total_chunks,
            }
            if isinstance(normalized_structured, dict):
                structured_fields = normalized.get("structured")
                if isinstance(structured_fields, dict):
                    sync_excluded_fields = {
                        "title",
                        "summary",
                        "abstract",
                        "URL",
                        "canonical_url",
                        "dedup_key",
                        "raw_text",
                        "HTML",
                        "pdf_document_blocks",
                    }
                    for key, value in normalized_structured.items():
                        if key in sync_excluded_fields or value in (None, "", [], {}):
                            continue
                        structured_fields[key] = value
                normalized.update({key: value for key, value in normalized_structured.items() if key not in normalized})
            if enrichment_result:
                normalized["enrichment"] = enrichment_result

            # Attach content-level warnings from fetch
            if raw_result.fetch_error:
                normalized["fetch_warning"] = {
                    "error_code": raw_result.fetch_error.error_code,
                    "agent_hint": raw_result.fetch_error.agent_hint,
                    "message": raw_result.fetch_error.message,
                }

            # Track progress with char count for real-time UX
            plain_text = normalized.get("plain_text", "")
            char_count = len(plain_text) if isinstance(plain_text, str) else 0
            progress.mark_done(url, char_count=char_count, status="ok")
            return normalized, None

        except Exception as exc:
            auth_error = classify_auth_failure(
                platform=platform,
                resource_type=resource_type,
                exception=exc,
                has_session=storage_state_path is not None,
                stage="new_pipeline",
            )
            if auth_error is not None:
                auth_error["canonical_url"] = record.get("canonical_url")
                return None, auth_error

            fetch_error = getattr(exc, "fetch_error", None)
            if fetch_error is not None:
                error = build_error_from_fetch_error(
                    platform=platform,
                    resource_type=resource_type,
                    fetch_error=fetch_error,
                    stage="new_pipeline",
                    message=str(exc),
                    exception=exc,
                )
                error["canonical_url"] = record.get("canonical_url")
                return None, error

            return None, {
                "platform": platform,
                "resource_type": resource_type,
                "stage": "new_pipeline",
                "status": "failed",
                "error_code": f"{platform.upper()}_PIPELINE_FAILED",
                "retryable": False,
                "next_action": "inspect error and retry",
                "canonical_url": record.get("canonical_url"),
                "message": str(exc),
            }

    try:
        async with FetchEngine(session_root) as fetch_engine:
            async def _guarded(idx: int, record: dict) -> tuple[dict | None, dict | None]:
                async with semaphore:
                    return await _process_one(idx, record)

            tasks = [_guarded(idx, rec) for idx, rec in enumerate(records, start=1)]
            outcomes = await asyncio.gather(*tasks, return_exceptions=True)

            for outcome in outcomes:
                if isinstance(outcome, BaseException):
                    errors.append({
                        "stage": "new_pipeline",
                        "status": "failed",
                        "error_code": "UNEXPECTED_ERROR",
                        "retryable": False,
                        "next_action": "inspect",
                        "message": str(outcome),
                    })
                else:
                    result, error = outcome
                    if result is not None:
                        results.append(result)
                    if error is not None:
                        errors.append(error)
    finally:
        progress.flush()
        signal.signal(signal.SIGINT, _prev_handler)
        if hasattr(signal, "SIGTERM") and _prev_term_handler is not None:
            signal.signal(signal.SIGTERM, _prev_term_handler)
    return results, errors


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return read_jsonl_file(path)


def _discovered_from_seed(seed) -> dict[str, Any]:
    return {
        "platform": seed.platform,
        "resource_type": seed.resource_type,
        "canonical_url": seed.canonical_url,
        "artifacts": dict(seed.metadata.get("artifacts", {})),
        "fields": dict(seed.identity),
    }


def _build_discovery_candidates(
    input_record: dict[str, Any],
    adapter_resolver: Any,
) -> list[Any]:
    from crawler.discovery.contracts import DiscoveryCandidate, DiscoveryMode

    platform = str(input_record.get("platform") or "generic")
    resource_type = str(input_record.get("resource_type") or "page")
    adapter = adapter_resolver(platform)
    url = input_record.get("url") or input_record.get("canonical_url")

    normalize_url = getattr(adapter, "normalize_url", None)
    if url and callable(normalize_url):
        normalized = adapter.normalize_url(str(url))
        if normalized.entity_type != "unknown" and normalized.canonical_url:
            return [
                DiscoveryCandidate(
                    platform=platform,
                    resource_type=resource_type or normalized.entity_type,
                    canonical_url=normalized.canonical_url,
                    seed_url=normalized.canonical_url,
                    fields=dict(normalized.identity),
                    discovery_mode=DiscoveryMode.CANONICALIZED_INPUT,
                    score=1.0,
                    score_breakdown={"direct_input": 1.0},
                    hop_depth=0,
                    parent_url=None,
                    metadata={},
                )
            ]

    try:
        seed_records = adapter.build_seed_records(input_record)
    except Exception as exc:
        logger.warning("build_seed_records failed for %s: %s", input_record.get("url", "?"), exc)
        seed_records = []
    if seed_records:
        return [_candidate_from_discovery_record(seed) for seed in seed_records]

    if not url:
        return []
    canonical_url = str(url)
    return [
        DiscoveryCandidate(
            platform=platform,
            resource_type=resource_type,
            canonical_url=canonical_url,
            seed_url=canonical_url,
            fields={},
            discovery_mode=DiscoveryMode.DIRECT_INPUT,
            score=1.0,
            score_breakdown={"direct_input": 1.0},
            hop_depth=0,
            parent_url=None,
            metadata={},
        )
    ]


def _candidate_from_discovery_record(seed: DiscoveryRecord) -> DiscoveryCandidate:
    from crawler.discovery.contracts import DiscoveryCandidate

    return DiscoveryCandidate(
        platform=seed.platform,
        resource_type=seed.resource_type,
        canonical_url=seed.canonical_url,
        seed_url=seed.canonical_url,
        fields=dict(seed.identity),
        discovery_mode=seed.discovery_mode,
        score=1.0,
        score_breakdown={"direct_input": 1.0},
        hop_depth=0,
        parent_url=None,
        metadata=dict(seed.metadata),
    )


def _build_enrich_input_from_record(record: dict[str, Any]) -> dict[str, Any]:
    return build_enrich_input(record)


async def _run_new_enrich_only_pipeline(
    records: list[dict[str, Any]],
    config: CrawlerConfig,
    enrich_pipeline,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    from crawler.platforms.registry import get_platform_adapter

    results: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    field_groups = list(config.field_groups) if config.field_groups else ["summaries"]

    for record in records:
        try:
            adapter = get_platform_adapter(record["platform"])
            enrich_input = _build_enrich_input_from_record(record)
            enriched = dict(record)
            enrichment_request = adapter.build_enrichment_request(record, config.field_groups)
            effective_field_groups = list(enrichment_request.get("field_groups") or field_groups)
            enriched["enrichment"] = (await enrich_pipeline.enrich(enrich_input, effective_field_groups)).to_dict()
            results.append(enriched)
        except Exception as exc:
            errors.append({
                "platform": record.get("platform", "unknown"),
                "resource_type": record.get("resource_type") or record.get("entity_type"),
                "stage": "enrich",
                "status": "failed",
                "error_code": "ENRICHMENT_FAILED",
                "retryable": False,
                "next_action": "inspect record and model config",
                "message": str(exc),
            })

    return results, errors


def _make_slug(index: int, url: str) -> str:
    tail = url.rstrip("/").split("/")[-1] or f"record-{index}"
    slug = "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "_" for ch in tail)
    return slug or f"record-{index}"


def _artifact_relpath(path: Path, root: Path) -> str:
    return path.relative_to(root.parent).as_posix()


def _persist_fetch_artifacts_new(
    *,
    artifact_root: Path,
    slug: str,
    fetched: dict[str, Any],
    root_for_rel: Path,
) -> list[dict[str, Any]]:
    """Persist fetch artifacts (similar to dispatcher but simpler)."""
    from crawler.output.artifact_writer import write_artifact_bytes, write_artifact_json, write_artifact_text

    written: list[dict[str, Any]] = []
    content_type = fetched.get("content_type", "")
    is_api_payload = fetched.get("backend") == "api" or fetched.get("json_data") is not None

    if is_api_payload:
        if fetched.get("json_data") is not None:
            json_path = artifact_root / slug / "api_response.json"
            write_artifact_json(json_path, fetched["json_data"])
            written.append({
                "kind": "api_response",
                "path": _artifact_relpath(json_path, root_for_rel),
                "content_type": "application/json",
            })
    else:
        # HTML content
        if fetched.get("html"):
            html_path = artifact_root / slug / "page.html"
            write_artifact_text(html_path, fetched["html"])
            written.append({
                "kind": "html",
                "path": _artifact_relpath(html_path, root_for_rel),
                "content_type": content_type or "text/html",
            })

    # Screenshot
    screenshot = fetched.get("screenshot") or fetched.get("screenshot_bytes")
    if screenshot:
        screenshot_path = artifact_root / slug / "screenshot.png"
        write_artifact_bytes(screenshot_path, screenshot)
        written.append({
            "kind": "screenshot",
            "path": _artifact_relpath(screenshot_path, root_for_rel),
            "content_type": "image/png",
        })

    # Fetch metadata
    metadata_path = artifact_root / slug / "fetch.json"
    write_artifact_json(metadata_path, {
        "url": fetched.get("url"),
        "final_url": fetched.get("final_url"),
        "status_code": fetched.get("status_code"),
        "backend": fetched.get("backend"),
        "content_type": content_type,
        "timing": fetched.get("timing"),
    })
    written.append({
        "kind": "fetch",
        "path": _artifact_relpath(metadata_path, root_for_rel),
        "content_type": "application/json",
    })

    return written


def _build_legacy_compatible_extracted(
    *,
    adapter,
    record: dict[str, Any],
    discovered: dict[str, Any],
    fetch_result: dict[str, Any],
    extracted_doc: Any,
) -> dict[str, Any]:
    if getattr(adapter, "default_backend", None) == "api":
        extracted = adapter.extract_content(record, fetch_result)
        if isinstance(extracted, dict):
            metadata = extracted.get("metadata") if isinstance(extracted.get("metadata"), dict) else {}
            metadata.setdefault("title", extracted_doc.structured.title)
            metadata.setdefault("description", extracted_doc.structured.description)
            extracted["metadata"] = metadata
            extracted.setdefault("plain_text", extracted_doc.full_text)
            extracted.setdefault("markdown", extracted_doc.full_markdown)
            existing_structured = extracted.get("structured") if isinstance(extracted.get("structured"), dict) else {}
            merged_structured = dict(extracted_doc.structured.platform_fields)
            for key, value in existing_structured.items():
                if value not in (None, "", [], {}):
                    merged_structured[key] = value
                else:
                    merged_structured.setdefault(key, value)
            extracted["structured"] = merged_structured
            extracted.setdefault("document_blocks", [])
            return extracted

    metadata = {
        "title": extracted_doc.structured.title,
        "description": extracted_doc.structured.description,
        "content_type": fetch_result.get("content_type"),
        "source_url": extracted_doc.source_url,
    }
    return {
        "metadata": metadata,
        "plain_text": extracted_doc.full_text,
        "markdown": extracted_doc.full_markdown,
        "structured": extracted_doc.structured.platform_fields,
        "document_blocks": [],
    }


def _persist_extraction_artifacts(
    *,
    artifact_root: Path,
    slug: str,
    extracted: Any,  # ExtractedDocument
    root_for_rel: Path,
) -> list[dict[str, Any]]:
    """Persist extraction artifacts."""
    from crawler.output.artifact_writer import write_artifact_bytes, write_artifact_json, write_artifact_text

    written: list[dict[str, Any]] = []

    # Markdown content
    markdown_path = artifact_root / slug / "content.md"
    write_artifact_text(markdown_path, extracted.full_markdown)
    written.append({
        "kind": "markdown",
        "path": _artifact_relpath(markdown_path, root_for_rel),
        "content_type": "text/markdown",
    })

    # Plain text
    text_path = artifact_root / slug / "content.txt"
    write_artifact_text(text_path, extracted.full_text)
    written.append({
        "kind": "plain_text",
        "path": _artifact_relpath(text_path, root_for_rel),
        "content_type": "text/plain",
    })

    if getattr(extracted, "cleaned_html", ""):
        cleaned_html_path = artifact_root / slug / "cleaned.html"
        write_artifact_text(cleaned_html_path, extracted.cleaned_html)
        written.append({
            "kind": "cleaned_html",
            "path": _artifact_relpath(cleaned_html_path, root_for_rel),
            "content_type": "text/html",
        })

    parser_metadata = getattr(extracted, "parser_metadata", {}) or {}
    if parser_metadata:
        parser_metadata_path = artifact_root / slug / "parser_metadata.json"
        write_artifact_json(parser_metadata_path, parser_metadata)
        written.append({
            "kind": "parser_metadata",
            "path": _artifact_relpath(parser_metadata_path, root_for_rel),
            "content_type": "application/json",
        })

    for name, payload in (getattr(extracted, "binary_artifacts", {}) or {}).items():
        if not payload:
            continue
        binary_path = artifact_root / slug / f"{name}.bin"
        if name == "raw_pdf":
            binary_path = artifact_root / slug / "source.pdf"
        write_artifact_bytes(binary_path, payload)
        written.append({
            "kind": name,
            "path": _artifact_relpath(binary_path, root_for_rel),
            "content_type": "application/pdf" if name == "raw_pdf" else "application/octet-stream",
        })

    # Chunks as JSON
    chunks_path = artifact_root / slug / "chunks.json"
    write_artifact_json(chunks_path, [c.to_dict() for c in extracted.chunks])
    written.append({
        "kind": "chunks",
        "path": _artifact_relpath(chunks_path, root_for_rel),
        "content_type": "application/json",
    })

    # Structured fields
    structured_path = artifact_root / slug / "structured.json"
    write_artifact_json(structured_path, {
        "title": extracted.structured.title,
        "description": extracted.structured.description,
        "canonical_url": extracted.structured.canonical_url,
        "platform_fields": extracted.structured.platform_fields,
        "field_sources": extracted.structured.field_sources,
    })
    written.append({
        "kind": "structured",
        "path": _artifact_relpath(structured_path, root_for_rel),
        "content_type": "application/json",
    })

    return written
