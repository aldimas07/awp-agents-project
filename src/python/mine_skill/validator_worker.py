from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from common import resolve_validator_state_root
from worker_state import ValidatorStateStore

SCRIPT_DIR = Path(__file__).resolve().parent


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
    import ctypes

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


def _creationflags() -> int:
    flags = 0
    for name in ("DETACHED_PROCESS", "CREATE_NEW_PROCESS_GROUP", "CREATE_NO_WINDOW"):
        flags |= int(getattr(subprocess, name, 0))
    return flags


def generate_session_id() -> str:
    return f"validator-{int(time.time())}"


def start_background(state_root: Path | None = None) -> dict[str, Any]:
    root = state_root or resolve_validator_state_root()
    store = ValidatorStateStore(root)

    bg = store.load_background_session()
    existing_pid = int(bg.get("pid") or 0)
    if existing_pid and process_is_running(existing_pid):
        return {
            "status": "already_running",
            "session_id": str(bg.get("session_id") or ""),
            "pid": existing_pid,
        }

    session_id = generate_session_id()
    script_path = SCRIPT_DIR / "run_tool.py"
    project_root = SCRIPT_DIR.parent
    output_root = root.parent
    output_root.mkdir(parents=True, exist_ok=True)
    log_path = output_root / f"{session_id}.log"

    from common import resolve_worker_python, worker_subprocess_env
    python_bin = resolve_worker_python(project_root)
    command = [python_bin, "-u", str(script_path), "run-validator-worker", session_id]
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

    store.save_background_session(pid=process.pid, session_id=session_id)

    return {
        "status": "started",
        "session_id": session_id,
        "pid": process.pid,
        "log_path": str(log_path),
    }


def stop_background(state_root: Path | None = None) -> dict[str, Any]:
    root = state_root or resolve_validator_state_root()
    store = ValidatorStateStore(root)

    bg = store.load_background_session()
    pid = int(bg.get("pid") or 0)
    session_id = str(bg.get("session_id") or "")

    if not pid:
        return {"status": "not_running"}

    if not process_is_running(pid):
        store.clear_background_session()
        return {"status": "already_stopped", "session_id": session_id, "pid": pid}

    try:
        if sys.platform == "win32":
            _terminate_process_windows(pid)
        else:
            import signal

            os.kill(pid, signal.SIGTERM)
    except OSError:
        pass

    store.clear_background_session()
    return {"status": "stopped", "session_id": session_id, "pid": pid}


def _terminate_process_windows(pid: int) -> bool:
    import ctypes

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


def get_status(state_root: Path | None = None) -> dict[str, Any]:
    root = state_root or resolve_validator_state_root()
    store = ValidatorStateStore(root)

    bg = store.load_background_session()
    pid = int(bg.get("pid") or 0)
    session_id = str(bg.get("session_id") or "")
    started_at = int(bg.get("started_at") or 0)

    if not pid:
        return {"status": "not_running"}

    running = process_is_running(pid)
    if not running:
        store.clear_background_session()

    return {
        "status": "running" if running else "stopped",
        "session_id": session_id,
        "pid": pid,
        "started_at": started_at,
    }
