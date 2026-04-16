from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Mapping


class CrawlCommand(str, Enum):
    DISCOVER_CRAWL = "discover-crawl"
    CRAWL = "crawl"
    RUN = "run"
    ENRICH = "enrich"


@dataclass(frozen=True, slots=True)
class NormalizedError:
    platform: str
    resource_type: str | None
    operation: str
    normalized_code: str
    retryable: bool
    message: str
    error_type: str | None = None

    @classmethod
    def from_exception(
        cls,
        *,
        platform: str,
        resource_type: str | None,
        operation: str,
        error_code: str,
        exception: Exception,
        retryable: bool,
    ) -> NormalizedError:
        return cls(
            platform=platform,
            resource_type=resource_type,
            operation=operation,
            normalized_code=error_code,
            retryable=retryable,
            message=str(exception),
            error_type=type(exception).__name__,
        )


def _coerce_path(value: Any, field_name: str) -> Path:
    if value is None:
        raise ValueError(f"{field_name} is required")
    if isinstance(value, Path):
        return value
    return Path(str(value))


def _coerce_command(value: Any) -> CrawlCommand:
    if value is None:
        return CrawlCommand.RUN
    if isinstance(value, CrawlCommand):
        return value
    return CrawlCommand(str(value))


@dataclass(frozen=True, slots=True)
class CrawlerConfig:
    command: CrawlCommand
    input_path: Path
    output_dir: Path
    cookies_path: Path | None = None
    css_schema_path: Path | None = None
    extract_llm_schema_path: Path | None = None
    enrich_llm_schema_path: Path | None = None
    model_config_path: Path | None = None
    use_openclaw: bool = False
    auto_login: bool = False
    platform: str | None = None
    backend: str | None = None
    preferred_backend: str | None = None
    resume: bool = False
    artifacts_dir: Path | None = None
    strict: bool = False
    field_groups: tuple[str, ...] = ()
    max_chunk_tokens: int = 512
    chunk_overlap: int = 50
    # Runtime / discovery options
    concurrency: int = 3
    max_depth: int = 2
    max_pages: int = 100
    sitemap_mode: str = "include"

    @classmethod
    def from_mapping(cls, values: Mapping[str, Any]) -> CrawlerConfig:
        return cls(
            command=_coerce_command(values.get("command")),
            input_path=_coerce_path(values.get("input_path"), "input_path"),
            output_dir=_coerce_path(values.get("output_dir"), "output_dir"),
            cookies_path=(
                _coerce_path(values["cookies_path"], "cookies_path")
                if values.get("cookies_path") is not None
                else None
            ),
            css_schema_path=(
                _coerce_path(values["css_schema_path"], "css_schema_path")
                if values.get("css_schema_path") is not None
                else None
            ),
            extract_llm_schema_path=(
                _coerce_path(values["extract_llm_schema_path"], "extract_llm_schema_path")
                if values.get("extract_llm_schema_path") is not None
                else None
            ),
            enrich_llm_schema_path=(
                _coerce_path(values["enrich_llm_schema_path"], "enrich_llm_schema_path")
                if values.get("enrich_llm_schema_path") is not None
                else None
            ),
            model_config_path=(
                _coerce_path(values["model_config_path"], "model_config_path")
                if values.get("model_config_path") is not None
                else None
            ),
            use_openclaw=bool(values.get("use_openclaw", False)),
            auto_login=bool(values.get("auto_login", False)),
            platform=values.get("platform"),
            backend=str(values["backend"]) if values.get("backend") is not None else None,
            preferred_backend=str(values["preferred_backend"]) if values.get("preferred_backend") is not None else None,
            resume=bool(values.get("resume", False)),
            artifacts_dir=(
                _coerce_path(values["artifacts_dir"], "artifacts_dir")
                if values.get("artifacts_dir") is not None
                else None
            ),
            strict=bool(values.get("strict", False)),
            field_groups=tuple(str(value) for value in values.get("field_groups", []) if value),
            max_chunk_tokens=int(values.get("max_chunk_tokens", 512)),
            chunk_overlap=int(values.get("chunk_overlap", 50)),
            concurrency=int(values.get("concurrency", 3)),
            max_depth=int(values.get("max_depth", 2)),
            max_pages=int(values.get("max_pages", 100)),
            sitemap_mode=str(values.get("sitemap_mode", "include")),
        )
