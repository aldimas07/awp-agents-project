from __future__ import annotations

import asyncio
from typing import Any, Callable

from crawler.enrich.models import EnrichedRecord, FieldGroupResult


class BatchEnrichmentExecutor:
    """Execute enrichment across many records with controlled concurrency."""

    def __init__(
        self,
        pipeline: Any,  # EnrichPipeline - forward ref to avoid circular import
        max_concurrency: int = 10,
        batch_size: int = 50,
        max_total_tokens: int | None = None,
        on_progress: Callable[[int, int], None] | None = None,
    ) -> None:
        self.pipeline = pipeline
        self.max_concurrency = max_concurrency
        self.batch_size = batch_size
        self.max_total_tokens = max_total_tokens
        self.on_progress = on_progress

    async def execute_batch(
        self,
        records: list[dict[str, Any]],
        field_groups: list[str],
    ) -> list[EnrichedRecord]:
        """Enrich all records in batches with bounded concurrency."""
        results: list[EnrichedRecord] = []
        total = len(records)
        completed = 0
        consumed_tokens = 0
        token_samples: list[int] = []

        for batch_start in range(0, total, self.batch_size):
            batch = records[batch_start : batch_start + self.batch_size]
            if self.max_total_tokens is not None:
                for i, rec in enumerate(batch):
                    if token_samples:
                        avg_tokens = max(1, sum(token_samples) // len(token_samples))
                        if consumed_tokens + avg_tokens > self.max_total_tokens:
                            results.append(self._budget_skipped_record(rec, field_groups, batch_start + i))
                            completed += 1
                            if self.on_progress:
                                self.on_progress(completed, total)
                            continue
                    try:
                        result = await self.pipeline.enrich(rec, field_groups)
                    except Exception:
                        result = EnrichedRecord(
                            doc_id=rec.get("doc_id", f"error-{batch_start + i}"),
                            source_url=rec.get("canonical_url", ""),
                            platform=rec.get("platform", "unknown"),
                            resource_type=rec.get("resource_type", "unknown"),
                        )
                    results.append(result)
                    used = self._tokens_used(result)
                    if used > 0:
                        token_samples.append(used)
                        consumed_tokens += used
                    completed += 1
                    if self.on_progress:
                        self.on_progress(completed, total)
                continue

            semaphore = asyncio.Semaphore(self.max_concurrency)

            async def _enrich_one(record: dict[str, Any]) -> EnrichedRecord:
                async with semaphore:
                    return await self.pipeline.enrich(record, field_groups)

            batch_results = await asyncio.gather(
                *[_enrich_one(rec) for rec in batch],
                return_exceptions=True,
            )

            for i, result in enumerate(batch_results):
                if isinstance(result, Exception):
                    rec = batch[i]
                    results.append(
                        EnrichedRecord(
                            doc_id=rec.get("doc_id", f"error-{batch_start + i}"),
                            source_url=rec.get("canonical_url", ""),
                            platform=rec.get("platform", "unknown"),
                            resource_type=rec.get("resource_type", "unknown"),
                        )
                    )
                else:
                    results.append(result)

                completed += 1
                if self.on_progress:
                    self.on_progress(completed, total)

        return results

    async def execute_single(
        self,
        record: dict[str, Any],
        field_groups: list[str],
    ) -> EnrichedRecord:
        """Enrich a single record."""
        return await self.pipeline.enrich(record, field_groups)

    @staticmethod
    def _tokens_used(record: EnrichedRecord) -> int:
        total = 0
        for result in record.enrichment_results.values():
            for field in result.fields:
                total += field.tokens_used or 0
        return total

    @staticmethod
    def _budget_skipped_record(
        record: dict[str, Any],
        field_groups: list[str],
        index: int,
    ) -> EnrichedRecord:
        enriched = EnrichedRecord(
            doc_id=record.get("doc_id", f"budget-{index}"),
            source_url=record.get("canonical_url", ""),
            platform=record.get("platform", "unknown"),
            resource_type=record.get("resource_type", "unknown"),
        )
        if field_groups:
            enriched.enrichment_results[field_groups[0]] = FieldGroupResult(
                field_group=field_groups[0],
                status="skipped",
                error="token budget exceeded",
            )
        return enriched
