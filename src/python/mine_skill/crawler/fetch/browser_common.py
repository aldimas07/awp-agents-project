from __future__ import annotations

import asyncio
import json
import threading
from pathlib import Path
from queue import Queue
from typing import Any, Callable, TypeVar

T = TypeVar("T")


def run_sync_compatible(callable_: Callable[[], T]) -> T:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return callable_()

    result_queue: Queue[tuple[str, object]] = Queue(maxsize=1)

    def worker() -> None:
        try:
            result_queue.put(("result", callable_()))
        except Exception as exc:  # pragma: no cover - propagated to caller
            result_queue.put(("error", exc))

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    thread.join()
    status, payload = result_queue.get()
    if status == "error":
        raise payload  # type: ignore[misc]
    return payload  # type: ignore[return-value]


def resolve_storage_state_path(storage_state_path: str | None) -> str | None:
    if not storage_state_path:
        return None
    return storage_state_path if Path(storage_state_path).exists() else None


def persist_storage_state(storage_state_path: str | None, payload: dict[str, Any]) -> None:
    if storage_state_path is None:
        return
    storage_state_file = Path(storage_state_path)
    storage_state_file.parent.mkdir(parents=True, exist_ok=True)
    storage_state_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
