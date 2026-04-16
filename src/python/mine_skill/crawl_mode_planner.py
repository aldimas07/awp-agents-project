from __future__ import annotations

from run_models import WorkItem


class CrawlModePlanner:
    def choose_command(self, item: WorkItem) -> str:
        if item.crawler_command:
            return item.crawler_command
        if item.source in {"dataset_discovery", "domain_discovery"}:
            return "discover-crawl"
        if item.source == "manual_debug":
            return "crawl"
        # repeat_crawl only needs cleaned_data (fetch + extract) — skip
        # enrich entirely. "crawl" does fetch+extract without enrich,
        # while "run" does the full pipeline including enrich.
        if item.claim_task_type == "repeat_crawl":
            return "crawl"
        return "run"
