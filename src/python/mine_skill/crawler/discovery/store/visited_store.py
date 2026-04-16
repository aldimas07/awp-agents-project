from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from crawler.discovery.state.visited import VisitRecord


class InMemoryVisitedStore:
    def __init__(self, path: Path | None = None) -> None:
        self._path = path
        self.records: dict[str, VisitRecord] = {}
        self._load()

    def put(self, record: VisitRecord) -> VisitRecord:
        self.records[record.url_key] = record
        self._save()
        return record

    def get(self, url_key: str) -> VisitRecord | None:
        return self.records.get(url_key)

    def list(self) -> list[VisitRecord]:
        return list(self.records.values())

    def _load(self) -> None:
        if self._path is None or not self._path.exists():
            return
        payload = json.loads(self._path.read_text(encoding="utf-8"))
        for item in payload:
            record = VisitRecord(**item)
            self.records[record.url_key] = record

    def _save(self) -> None:
        if self._path is None:
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = [asdict(record) for record in self.records.values()]
        self._path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
