from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Iterable


def _atomic_write_lines(path: Path, lines: Iterable[str]) -> None:
    """Write lines to a file atomically via temp file + rename."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            fd = -1  # os.fdopen takes ownership
            for line in lines:
                f.write(line)
        os.replace(tmp, str(path))
    except BaseException:
        if fd >= 0:
            os.close(fd)
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def write_jsonl(path: Path, records: Iterable[dict], *, append: bool = False) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if append:
        # Append mode: direct write (atomic rename not possible)
        with path.open("a", encoding="utf-8") as handle:
            for record in records:
                handle.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
    else:
        _atomic_write_lines(
            path,
            (json.dumps(record, ensure_ascii=False, default=str) + "\n" for record in records),
        )
    return path
