from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from crawler.discovery.state.checkpoint import Checkpoint


class InMemoryCheckpointStore:
    def __init__(self, path: Path | None = None) -> None:
        self._path = path
        self.checkpoints: dict[str, Checkpoint] = {}
        self._load()

    def put(self, checkpoint_id: str, checkpoint: Checkpoint) -> Checkpoint:
        if checkpoint.checkpoint_id is not None and checkpoint.checkpoint_id != checkpoint_id:
            raise ValueError("checkpoint_id does not match checkpoint.checkpoint_id")
        self.checkpoints[checkpoint_id] = checkpoint
        self._save()
        return checkpoint

    def get(self, checkpoint_id: str) -> Checkpoint | None:
        return self.checkpoints.get(checkpoint_id)

    def _load(self) -> None:
        if self._path is None or not self._path.exists():
            return
        payload = json.loads(self._path.read_text(encoding="utf-8"))
        for item in payload:
            checkpoint = Checkpoint(**item)
            if checkpoint.checkpoint_id is not None:
                self.checkpoints[checkpoint.checkpoint_id] = checkpoint

    def _save(self) -> None:
        if self._path is None:
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = [asdict(checkpoint) for checkpoint in self.checkpoints.values()]
        self._path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
