from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any

from run_models import WorkItem


class WorkerStateStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        # Protects all file read-modify-write operations. The submit thread,
        # repeat_crawl thread, and main iteration thread all access the same
        # JSON files concurrently.
        self._file_lock = threading.Lock()
        self._backlog_path = self.root / "backlog.json"
        self._auth_pending_path = self.root / "auth_pending.json"
        self._submit_pending_path = self.root / "submit_pending.json"
        self._dataset_cursors_path = self.root / "dataset_cursors.json"
        self._session_path = self.root / "session.json"
        self._background_session_path = self.root / "background_session.json"
        self._dataset_cooldowns_path = self.root / "dataset_cooldowns.json"
        self._lock_path = self.root / "worker.lock.json"
        self._session_cache: dict[str, Any] | None = None
        self._session_dirty = False
        self._memory_state: dict[str, dict[str, Any] | None] = {
            "pow_challenge": None,
            "current_batch": None,
        }

    def load_backlog(self) -> list[WorkItem]:
        return [WorkItem.from_dict(item) for item in self._read_list(self._backlog_path)]

    def enqueue_backlog(self, items: list[WorkItem]) -> None:
        with self._file_lock:
            payload = self._read_list(self._backlog_path)
            merged = {str(item.get("item_id") or ""): item for item in payload if item.get("item_id")}
            for item in items:
                merged[item.item_id] = item.to_dict()
            self._write_json(self._backlog_path, list(merged.values()))

    def pop_backlog(self, limit: int) -> list[WorkItem]:
        with self._file_lock:
            items = self.load_backlog()
            popped = items[:limit]
            remaining = items[limit:]
            self._write_json(self._backlog_path, [item.to_dict() for item in remaining])
            return popped

    def load_auth_pending(self) -> list[dict[str, Any]]:
        return self._read_list(self._auth_pending_path)

    def upsert_auth_pending(self, item: WorkItem, error: dict[str, Any], *, retry_after_seconds: int) -> None:
        with self._file_lock:
            payload = self._read_list(self._auth_pending_path)
            merged = {str(entry.get("item_id") or ""): entry for entry in payload if entry.get("item_id")}
            merged[item.item_id] = {
                "item_id": item.item_id,
                "item": item.to_dict(),
                "error": dict(error),
                "available_at": int(time.time()) + max(0, retry_after_seconds),
                "updated_at": int(time.time()),
            }
            self._write_json(self._auth_pending_path, list(merged.values()))

    def clear_auth_pending(self, item_id: str) -> None:
        with self._file_lock:
            payload = [entry for entry in self._read_list(self._auth_pending_path) if str(entry.get("item_id")) != item_id]
            self._write_json(self._auth_pending_path, payload)

    def pop_due_auth_pending(self, limit: int, *, now: int | None = None) -> list[WorkItem]:
        with self._file_lock:
            current = int(time.time()) if now is None else now
            payload = self._read_list(self._auth_pending_path)
            due: list[dict[str, Any]] = []
            remaining: list[dict[str, Any]] = []
            for entry in payload:
                available_at = int(entry.get("available_at") or 0)
                in_flight = entry.get("in_flight")
                in_flight_since = int(entry.get("in_flight_since") or 0)
                if in_flight and in_flight_since and (current - in_flight_since) > 600:
                    entry["in_flight"] = False
                    in_flight = False
                if available_at <= current and not in_flight and len(due) < limit:
                    entry["in_flight"] = True
                    entry["in_flight_since"] = current
                    due.append(entry)
                remaining.append(entry)
            self._write_json(self._auth_pending_path, remaining)
            return [WorkItem.from_dict(dict(entry.get("item") or {})) for entry in due]

    def enqueue_submit_pending(self, item: WorkItem, payload: dict[str, Any]) -> None:
        with self._file_lock:
            entries = self._read_list(self._submit_pending_path)
            merged = {str(e.get("item_id") or ""): e for e in entries if e.get("item_id")}
            merged[item.item_id] = {
                "item_id": item.item_id,
                "item": item.to_dict(),
                "payload": payload,
                "updated_at": int(time.time()),
            }
            self._write_json(self._submit_pending_path, list(merged.values()))

    def load_submit_pending(self) -> list[dict[str, Any]]:
        with self._file_lock:
            return self._read_list(self._submit_pending_path)

    def clear_submit_pending(self, item_id: str) -> None:
        with self._file_lock:
            payload = [entry for entry in self._read_list(self._submit_pending_path) if str(entry.get("item_id")) != item_id]
            self._write_json(self._submit_pending_path, payload)

    def should_schedule_dataset(self, dataset_id: str, *, min_interval_seconds: int, now: int | None = None) -> bool:
        current = int(time.time()) if now is None else now
        cursors = self._read_object(self._dataset_cursors_path)
        last_run = int((cursors.get(dataset_id) or {}).get("last_scheduled_at") or 0)
        return current - last_run >= max(0, min_interval_seconds)

    def mark_dataset_scheduled(self, dataset_id: str, *, now: int | None = None) -> None:
        current = int(time.time()) if now is None else now
        cursors = self._read_object(self._dataset_cursors_path)
        cursors[dataset_id] = {"last_scheduled_at": current}
        self._write_json(self._dataset_cursors_path, cursors)

    def load_session(self) -> dict[str, Any]:
        with self._file_lock:
            if self._session_cache is None:
                self._session_cache = self._normalize_session(self._read_object(self._session_path))
            return self._normalize_session(self._session_cache)

    def load_background_session(self) -> dict[str, Any]:
        payload = self._read_object(self._background_session_path)
        return dict(payload) if isinstance(payload, dict) else {}

    def save_background_session(self, payload: dict[str, Any]) -> dict[str, Any]:
        current = self.load_background_session()
        current.update(payload)
        self._write_json(self._background_session_path, current)
        return dict(current)

    def clear_background_session(self) -> bool:
        try:
            self._background_session_path.unlink()
        except FileNotFoundError:
            return False
        return True

    def save_session(self, partial: dict[str, Any], *, flush: bool = True) -> dict[str, Any]:
        with self._file_lock:
            session = self._load_session_unlocked()
            for key in ("session_totals", "last_summary", "settlement", "reward_summary"):
                value = partial.get(key)
                if isinstance(value, dict):
                    merged = dict(session.get(key) or {})
                    merged.update(value)
                    session[key] = merged
            for key, value in partial.items():
                if key in {"session_totals", "last_summary", "settlement", "reward_summary"} and isinstance(value, dict):
                    continue
                session[key] = value
            self._session_cache = self._normalize_session(session)
            self._session_dirty = True
            if flush:
                return self._flush_session_unlocked()
            return self._normalize_session(self._session_cache)

    def _load_session_unlocked(self) -> dict[str, Any]:
        """Load session without acquiring _file_lock (caller must hold it)."""
        if self._session_cache is None:
            self._session_cache = self._normalize_session(self._read_object(self._session_path))
        return self._normalize_session(self._session_cache)

    def _flush_session_unlocked(self) -> dict[str, Any]:
        """Flush session without acquiring _file_lock (caller must hold it)."""
        session = self._load_session_unlocked()
        if self._session_dirty:
            self._write_json(self._session_path, session)
            self._session_dirty = False
        return session

    def flush_session(self) -> dict[str, Any]:
        with self._file_lock:
            return self._flush_session_unlocked()

    def load_lock(self) -> dict[str, Any] | None:
        payload = self._read_object(self._lock_path)
        owner = payload.get("owner")
        if not owner:
            return None
        return {
            "owner": str(owner),
            "acquired_at": int(payload.get("acquired_at") or 0),
            "updated_at": int(payload.get("updated_at") or 0),
        }

    def acquire_lock(self, owner: str, *, now: int | None = None, stale_after_seconds: int = 300) -> bool:
        current = int(time.time()) if now is None else now
        existing = self.load_lock()
        if existing is not None:
            if existing["owner"] != owner and current - int(existing.get("updated_at") or 0) < max(0, stale_after_seconds):
                return False
            acquired_at = int(existing.get("acquired_at") or current) if existing["owner"] == owner else current
        else:
            acquired_at = current
        self._write_json(self._lock_path, {
            "owner": owner,
            "acquired_at": acquired_at,
            "updated_at": current,
        })
        return True

    def release_lock(self, owner: str | None = None) -> bool:
        existing = self.load_lock()
        if existing is None:
            return False
        if owner is not None and existing["owner"] != owner:
            return False
        try:
            self._lock_path.unlink()
        except FileNotFoundError:
            return False
        return True

    def set_pow_challenge(self, challenge: dict[str, Any] | None) -> None:
        self._memory_state["pow_challenge"] = dict(challenge) if isinstance(challenge, dict) else None

    def get_pow_challenge(self) -> dict[str, Any] | None:
        payload = self._memory_state.get("pow_challenge")
        return dict(payload) if isinstance(payload, dict) else None

    def clear_pow_challenge(self) -> None:
        self._memory_state["pow_challenge"] = None

    def set_current_batch(self, batch: dict[str, Any] | None) -> None:
        self._memory_state["current_batch"] = dict(batch) if isinstance(batch, dict) else None

    def get_current_batch(self) -> dict[str, Any] | None:
        payload = self._memory_state.get("current_batch")
        return dict(payload) if isinstance(payload, dict) else None

    def clear_current_batch(self) -> None:
        self._memory_state["current_batch"] = None

    def _session_defaults(self) -> dict[str, Any]:
        return {
            "mining_state": "idle",
            "selected_dataset_ids": [],
            "miner_registered": False,
            "wallet_addr": None,
            "active_datasets": [],
            "reward_summary": {},
            "stop_conditions": {},
            "stop_reason": None,
            "session_totals": {
                "processed_items": 0,
                "submitted_items": 0,
                "failed_items": 0,
            },
            "last_summary": {},
            "last_heartbeat_at": None,
            "credit_score": None,
            "credit_tier": None,
            "epoch_id": None,
            "epoch_submitted": 0,
            "epoch_target": 80,
            "settlement": {},
            "token_expires_at": None,
            "last_control_action": None,
            "last_state_change_at": None,
            "last_activity_at": None,
            "last_iteration": 0,
            "last_wait_seconds": 0,
        }

    def _normalize_session(self, session: dict[str, Any]) -> dict[str, Any]:
        defaults = self._session_defaults()
        merged = {**defaults, **session}
        for key in ("selected_dataset_ids", "active_datasets"):
            if not isinstance(merged.get(key), list):
                merged[key] = []
            else:
                merged[key] = list(merged[key])
        stop_conditions = merged.get("stop_conditions")
        if isinstance(stop_conditions, dict):
            merged["stop_conditions"] = dict(stop_conditions)
        else:
            merged["stop_conditions"] = {}
        for key in ("last_summary", "settlement", "reward_summary"):
            if not isinstance(merged.get(key), dict):
                merged[key] = {}
            else:
                merged[key] = dict(merged[key])
        if isinstance(merged.get("session_totals"), dict):
            merged["session_totals"] = {**defaults["session_totals"], **merged["session_totals"]}
        else:
            merged["session_totals"] = dict(defaults["session_totals"])
        if not isinstance(merged.get("miner_registered"), bool):
            merged["miner_registered"] = bool(merged.get("miner_registered"))
        wallet_addr = merged.get("wallet_addr")
        merged["wallet_addr"] = wallet_addr if isinstance(wallet_addr, str) and wallet_addr else None
        stop_reason = merged.get("stop_reason")
        merged["stop_reason"] = stop_reason if isinstance(stop_reason, str) and stop_reason else None
        return merged

    def mark_dataset_cooldown(
        self,
        dataset_id: str,
        *,
        retry_after_seconds: int,
        reason: str,
        now: int | None = None,
    ) -> None:
        with self._file_lock:
            current = int(time.time()) if now is None else now
            payload = self._read_object(self._dataset_cooldowns_path)
            payload[dataset_id] = {
                "available_at": current + max(0, retry_after_seconds),
                "reason": reason,
                "updated_at": current,
            }
            self._write_json(self._dataset_cooldowns_path, payload)

    def is_dataset_available(self, dataset_id: str, *, now: int | None = None) -> bool:
        current = int(time.time()) if now is None else now
        payload = self._read_object(self._dataset_cooldowns_path)
        entry = payload.get(dataset_id)
        if not isinstance(entry, dict):
            return True
        return int(entry.get("available_at") or 0) <= current

    def active_dataset_cooldowns(self, *, now: int | None = None) -> dict[str, dict[str, Any]]:
        current = int(time.time()) if now is None else now
        payload = self._read_object(self._dataset_cooldowns_path)
        return {
            dataset_id: dict(entry)
            for dataset_id, entry in payload.items()
            if isinstance(entry, dict) and int(entry.get("available_at") or 0) > current
        }

    def _read_list(self, path: Path) -> list[dict[str, Any]]:
        payload = self._read_json(path)
        return payload if isinstance(payload, list) else []

    def _read_object(self, path: Path) -> dict[str, Any]:
        payload = self._read_json(path)
        return payload if isinstance(payload, dict) else {}

    def _read_json(self, path: Path) -> Any:
        if not path.exists():
            return self._default_json_payload(path)
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            corrupt_path = path.with_name(f"{path.name}.corrupt-{time.time_ns()}")
            try:
                path.replace(corrupt_path)
            except OSError:
                pass
            return self._default_json_payload(path)

    def _write_json(self, path: Path, payload: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = path.with_name(f".{path.name}.tmp-{os.getpid()}-{time.time_ns()}")
        try:
            temp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            temp_path.replace(path)
        except OSError:
            temp_path.unlink(missing_ok=True)
            raise

    def _default_json_payload(self, path: Path) -> Any:
        if path in {self._backlog_path, self._auth_pending_path, self._submit_pending_path}:
            return []
        return {}


class ValidatorStateStore:
    """Persists validator session state across restarts."""

    SESSION_FILE = "validator_session.json"
    BACKGROUND_FILE = "validator_background.json"

    def __init__(self, state_root: Path) -> None:
        self._state_root = Path(state_root)
        self._state_root.mkdir(parents=True, exist_ok=True)

    @property
    def state_root(self) -> Path:
        return self._state_root

    def _session_path(self) -> Path:
        return self._state_root / self.SESSION_FILE

    def _background_path(self) -> Path:
        return self._state_root / self.BACKGROUND_FILE

    def save_session(self, data: dict[str, Any]) -> None:
        self._write_json(self._session_path(), data)

    def load_session(self) -> dict[str, Any]:
        return self._read_json(self._session_path())

    def update_session(self, **updates: Any) -> None:
        current = self.load_session()
        current.update(updates)
        self.save_session(current)

    def save_background_session(self, *, pid: int, session_id: str) -> None:
        self._write_json(self._background_path(), {
            "pid": pid,
            "session_id": session_id,
            "started_at": int(time.time()),
        })

    def load_background_session(self) -> dict[str, Any]:
        return self._read_json(self._background_path())

    def clear_background_session(self) -> None:
        path = self._background_path()
        if path.exists():
            path.unlink()

    def _write_json(self, path: Path, data: dict[str, Any]) -> None:
        temp_path = path.with_name(f".{path.name}.tmp-{os.getpid()}-{time.time_ns()}")
        try:
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            temp_path.replace(path)
        except OSError:
            temp_path.unlink(missing_ok=True)
            raise

    def _read_json(self, path: Path) -> dict[str, Any]:
        if not path.exists():
            return {}
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data if isinstance(data, dict) else {}
        except (json.JSONDecodeError, OSError):
            return {}
