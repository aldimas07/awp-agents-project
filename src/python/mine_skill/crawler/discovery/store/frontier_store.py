from __future__ import annotations

import json
from dataclasses import asdict, replace
from pathlib import Path

from crawler.discovery.state.frontier import FrontierEntry, FrontierStatus


class InMemoryFrontierStore:
    def __init__(self, path: Path | None = None) -> None:
        self._path = path
        self.entries: dict[str, FrontierEntry] = {}
        self._load()

    def put(self, entry: FrontierEntry) -> FrontierEntry:
        self.entries[entry.frontier_id] = entry
        self._save()
        return entry

    def get(self, frontier_id: str) -> FrontierEntry | None:
        return self.entries.get(frontier_id)

    def list(self) -> list[FrontierEntry]:
        return list(self.entries.values())

    def list_queued(self) -> list[FrontierEntry]:
        return [entry for entry in self.entries.values() if entry.status is FrontierStatus.QUEUED]

    def lease(self, frontier_id: str) -> FrontierEntry | None:
        entry = self.entries.get(frontier_id)
        if entry is None or entry.status is not FrontierStatus.QUEUED:
            return None
        leased = replace(entry, status=FrontierStatus.LEASED, attempt=entry.attempt + 1)
        self.entries[frontier_id] = leased
        self._save()
        return leased

    def mark_done(self, frontier_id: str) -> FrontierEntry | None:
        entry = self.entries.get(frontier_id)
        if entry is None:
            return None
        done = replace(entry, status=FrontierStatus.DONE)
        self.entries[frontier_id] = done
        self._save()
        return done

    def mark_dead(self, frontier_id: str) -> FrontierEntry | None:
        entry = self.entries.get(frontier_id)
        if entry is None:
            return None
        dead = replace(entry, status=FrontierStatus.DEAD)
        self.entries[frontier_id] = dead
        self._save()
        return dead

    def mark_retry(
        self, frontier_id: str, not_before: str, error: dict | None = None,
    ) -> FrontierEntry | None:
        entry = self.entries.get(frontier_id)
        if entry is None:
            return None
        retry = replace(
            entry,
            status=FrontierStatus.RETRY_WAIT,
            not_before=not_before,
            last_error=error,
        )
        self.entries[frontier_id] = retry
        self._save()
        return retry

    def prune_terminal(self, keep: int = 500) -> int:
        """Remove oldest DONE/DEAD entries when they exceed *keep* count."""
        terminal = [
            e for e in self.entries.values()
            if e.status in (FrontierStatus.DONE, FrontierStatus.DEAD)
        ]
        if len(terminal) <= keep:
            return 0
        # Sort by frontier_id (creation order) and remove oldest excess
        terminal.sort(key=lambda e: e.frontier_id)
        to_remove = terminal[: len(terminal) - keep]
        for entry in to_remove:
            del self.entries[entry.frontier_id]
        if to_remove:
            self._save()
        return len(to_remove)

    def promote_retryable(self, now_iso: str) -> int:
        """Move retryable entries back to QUEUED.  Return count promoted."""
        retryable = [
            entry
            for entry in self.entries.values()
            if entry.status is FrontierStatus.RETRY_WAIT
            and entry.not_before is not None
            and entry.not_before <= now_iso
        ]
        for entry in retryable:
            promoted = replace(entry, status=FrontierStatus.QUEUED, not_before=None)
            self.entries[entry.frontier_id] = promoted
        if retryable:
            self._save()
        return len(retryable)

    def _load(self) -> None:
        if self._path is None or not self._path.exists():
            return
        payload = json.loads(self._path.read_text(encoding="utf-8"))
        for item in payload:
            item["status"] = FrontierStatus(item["status"])
            entry = FrontierEntry(**item)
            self.entries[entry.frontier_id] = entry

    def _save(self) -> None:
        if self._path is None:
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = [asdict(entry) for entry in self.entries.values()]
        self._path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
