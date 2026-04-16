"""Lightweight progress tracker – persists completed URLs to JSON for resume."""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_FLUSH_EVERY = 10


class ProgressTracker:
    """Track completed URLs so a crawl can resume after interruption."""

    def __init__(
        self,
        output_dir: Path,
        *,
        enabled: bool = True,
        load_existing: bool = True,
    ) -> None:
        self._path = Path(output_dir) / "progress.json"
        self._enabled = enabled
        self._done: set[str] = set()
        self._done_detail: list[dict[str, Any]] = []  # For real-time UX
        self._current_url: str | None = None
        self._current_phase: str = "idle"
        self._dirty = False
        self._marks_since_flush = 0

        if enabled and load_existing and self._path.exists():
            self._load()

    # ------------------------------------------------------------------
    def is_done(self, url: str) -> bool:
        if not self._enabled:
            return False
        return url in self._done

    def set_phase(self, phase: str) -> None:
        """Set current crawling phase (discovery, dedup, pow, crawling, structuring, submitting)."""
        if not self._enabled:
            return
        if self._current_phase != phase:
            self._current_phase = phase
            self._dirty = True

    def set_current_url(self, url: str | None) -> None:
        """Set the URL currently being processed."""
        if not self._enabled:
            return
        if self._current_url != url:
            self._current_url = url
            self._dirty = True

    def mark_done(self, url: str, *, char_count: int | None = None, status: str = "ok") -> None:
        """Mark a URL as completed with optional metadata for real-time UX."""
        if not self._enabled:
            return
        if url in self._done:
            return
        self._done.add(url)
        # Record detail for real-time display
        detail: dict[str, Any] = {
            "url": url,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "status": status,
        }
        if char_count is not None:
            detail["char_count"] = char_count
        self._done_detail.append(detail)
        self._dirty = True
        self._marks_since_flush += 1
        if self._marks_since_flush >= _FLUSH_EVERY:
            self.flush()

    def mark_failed(self, url: str, *, error_message: str | None = None) -> None:
        """Mark a URL as failed (for display only, not marked as done for resume)."""
        if not self._enabled:
            return
        # Don't add to _done so it can be retried on resume
        detail: dict[str, Any] = {
            "url": url,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "status": "failed",
        }
        if error_message:
            detail["error"] = error_message
        self._done_detail.append(detail)
        self._dirty = True
        self._marks_since_flush += 1
        if self._marks_since_flush >= _FLUSH_EVERY:
            self.flush()

    def flush(self) -> None:
        if not self._enabled:
            return
        if not self._dirty:
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "completed_urls": sorted(self._done),
            "count": len(self._done),
            "last_updated": datetime.now(timezone.utc).isoformat(),
            "current_phase": self._current_phase,
            "current_url": self._current_url,
            "completed_detail": self._done_detail[-100:],  # Keep last 100 for real-time UX
        }
        data = json.dumps(payload, indent=2, ensure_ascii=False)
        # Atomic write via temp file + rename
        fd, tmp = tempfile.mkstemp(dir=str(self._path.parent), suffix=".tmp")
        try:
            os.write(fd, data.encode("utf-8"))
            os.close(fd)
            fd = -1
            os.replace(tmp, str(self._path))
        except BaseException:
            if fd >= 0:
                os.close(fd)
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
        self._dirty = False
        self._marks_since_flush = 0

    def reset(self) -> None:
        if not self._enabled:
            return
        self._done.clear()
        self._done_detail.clear()
        self._current_url = None
        self._current_phase = "idle"
        self._dirty = False
        self._marks_since_flush = 0
        if self._path.exists():
            self._path.unlink()

    # ------------------------------------------------------------------
    def _load(self) -> None:
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            self._done = set(data.get("completed_urls", []))
            self._current_phase = data.get("current_phase", "idle")
            self._current_url = data.get("current_url")
            detail = data.get("completed_detail", [])
            self._done_detail = detail if isinstance(detail, list) else []
        except (json.JSONDecodeError, OSError):
            self._done = set()
            self._done_detail = []
            self._current_phase = "idle"
            self._current_url = None
