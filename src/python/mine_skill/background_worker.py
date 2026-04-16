from __future__ import annotations

import ctypes
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


def _creationflags() -> int:
    flags = 0
    for name in ("DETACHED_PROCESS", "CREATE_NEW_PROCESS_GROUP", "CREATE_NO_WINDOW"):
        flags |= int(getattr(subprocess, name, 0))
    return flags


def process_is_running(pid: int) -> bool:
    if pid <= 0:
        return False
    if sys.platform == "win32":
        return _process_is_running_windows(pid)
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _process_is_running_windows(pid: int) -> bool:
    kernel32 = getattr(ctypes, "windll", None)
    if kernel32 is None:
        return False
    api = getattr(kernel32, "kernel32", None)
    if api is None:
        return False
    synchronize = 0x00100000
    query_limited_information = 0x1000
    still_active = 259
    handle = api.OpenProcess(synchronize | query_limited_information, False, pid)
    if not handle:
        return False
    try:
        exit_code = ctypes.c_ulong()
        ok = api.GetExitCodeProcess(handle, ctypes.byref(exit_code))
        return bool(ok) and exit_code.value == still_active
    finally:
        api.CloseHandle(handle)


def terminate_process(pid: int) -> bool:
    if not process_is_running(pid):
        return False
    try:
        if sys.platform == "win32":
            return _terminate_process_windows(pid)
        else:
            os.kill(pid, signal.SIGTERM)
        return True
    except OSError:
        return False


def _terminate_process_windows(pid: int) -> bool:
    kernel32 = getattr(ctypes, "windll", None)
    if kernel32 is None:
        return False
    api = getattr(kernel32, "kernel32", None)
    if api is None:
        return False
    terminate_access = 0x0001
    synchronize = 0x00100000
    query_limited_information = 0x1000
    handle = api.OpenProcess(terminate_access | synchronize | query_limited_information, False, pid)
    if not handle:
        return False
    try:
        ok = api.TerminateProcess(handle, 1)
        return bool(ok)
    finally:
        api.CloseHandle(handle)


def start_background_worker(
    *,
    project_root: Path,
    script_path: Path,
    interval: int = 60,
) -> dict[str, Any]:
    session_id = f"mine-{int(time.time())}"
    output_root = Path(os.environ.get("CRAWLER_OUTPUT_ROOT", str(project_root / "output" / "agent-runs"))).resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    log_path = output_root / f"{session_id}.log"
    from common import resolve_worker_python, worker_subprocess_env
    python_bin = resolve_worker_python(project_root)
    command = [python_bin, "-u", str(script_path), "run-worker", str(interval), "0"]
    env = worker_subprocess_env()

    with log_path.open("a", encoding="utf-8") as handle:
        process = subprocess.Popen(
            command,
            cwd=project_root,
            stdout=handle,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            env=env,
            start_new_session=True,
            creationflags=_creationflags(),
        )

    return {
        "session_id": session_id,
        "pid": process.pid,
        "command": command,
        "log_path": str(log_path),
        "started_at": int(time.time()),
    }
