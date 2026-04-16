"""OpenClaw agent CLI execution for LLM enrichment.

This module is the preferred execution path for mine LLM enrich calls. It
mirrors the OpenClaw worker approach:

- resolve the OpenClaw binary up front
- use a dedicated agent instead of `main`
- create the agent if missing
- purge session transcripts before and after every CLI call
- parse structured JSON responses when available
- back off briefly after rate-limit style failures
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

DEFAULT_CLI_TIMEOUT: int = 120
DEFAULT_AGENT_ID: str = "mine-enrich"
DEFAULT_RATE_LIMIT_BACKOFF_SECONDS: int = 60

_RATE_LIMIT_HINTS = ("429", "rate limit", "extra usage", "too many requests")

_openclaw_bin: str = ""
_agent_id: str = ""
_rate_limit_until: float = 0.0
_agent_lock = threading.Lock()


@dataclass(slots=True)
class EnrichResponse:
    """Response from OpenClaw CLI style agent enrichment."""

    content: str
    success: bool
    source: str
    error: str | None = None
    model: str | None = None
    tokens_used: int | None = None


class OpenClawAgentError(RuntimeError):
    """Raised when the OpenClaw agent CLI call fails."""


def openclaw_cli_available() -> bool:
    """Return whether an OpenClaw CLI binary is available."""
    return bool(_resolve_openclaw_path(required=False))


def _configured_agent_id() -> str:
    explicit = os.environ.get("MINE_ENRICH_AGENT_ID", "").strip()
    if explicit:
        return explicit
    suffix = os.environ.get("MINE_ENRICH_AGENT_SUFFIX", "").strip()
    return f"{DEFAULT_AGENT_ID}-{suffix}" if suffix else DEFAULT_AGENT_ID


def _workspace_for_agent(agent_id: str) -> str:
    return str(Path.home() / ".openclaw" / f"workspace-{agent_id}")


def _session_dir_for_agent(agent_id: str) -> Path:
    return Path.home() / ".openclaw" / "agents" / agent_id / "sessions"


def _resolve_openclaw_path(*, required: bool = True) -> str:
    """Find the OpenClaw binary using the same heuristics as OpenClaw worker."""
    global _openclaw_bin

    if _openclaw_bin:
        return _openclaw_bin

    configured = os.environ.get("OPENCLAW_BIN", "").strip()
    if configured:
        candidate = Path(configured).expanduser()
        if candidate.is_file():
            _openclaw_bin = str(candidate)
            return _openclaw_bin

    for name in ("openclaw", "openclaw.mjs", "openclaw.cmd"):
        path = shutil.which(name)
        if path:
            _openclaw_bin = path
            log.info("[AGENT] openclaw found: %s", path)
            return _openclaw_bin

    search_dirs = [
        os.path.expanduser("~/.local/bin"),
        "/usr/local/bin",
        os.path.expanduser("~/.openclaw/bin"),
        os.path.expanduser("~/bin"),
        os.path.expanduser("~/.openclaw"),
        "/usr/bin",
        os.path.expanduser("~/AppData/Roaming/npm"),
        "C:/nvm4w/nodejs",
    ]
    for directory in search_dirs:
        for name in ("openclaw", "openclaw.mjs", "openclaw.cmd"):
            candidate = Path(directory) / name
            if candidate.is_file():
                _openclaw_bin = str(candidate)
                log.info("[AGENT] openclaw found at: %s", candidate)
                return _openclaw_bin

    fallback_candidates = [
        os.path.expanduser("~/.openclaw/openclaw.mjs"),
        os.path.expanduser("~/.openclaw/node_modules/.bin/openclaw"),
        os.path.expanduser("~/.npm-global/bin/openclaw"),
        "/usr/lib/node_modules/openclaw/openclaw.mjs",
    ]
    for raw_candidate in fallback_candidates:
        candidate = Path(raw_candidate)
        if candidate.is_file():
            _openclaw_bin = str(candidate)
            log.info("[AGENT] openclaw found at: %s", candidate)
            return _openclaw_bin

    if required:
        raise OpenClawAgentError("openclaw command not found")
    return ""


def _agent_exists(agent_id: str) -> bool:
    openclaw = _resolve_openclaw_path(required=False)
    if not openclaw:
        return False
    try:
        result = subprocess.run(
            [openclaw, "agents", "list"],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return False
    return result.returncode == 0 and agent_id in result.stdout


def _create_agent(agent_id: str) -> bool:
    openclaw = _resolve_openclaw_path(required=False)
    if not openclaw:
        return False
    try:
        result = subprocess.run(
            [
                openclaw,
                "agents",
                "add",
                agent_id,
                "--workspace",
                _workspace_for_agent(agent_id),
                "--non-interactive",
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
        log.warning("[AGENT] failed to create agent %s: %s", agent_id, exc)
        return False

    if result.returncode == 0:
        log.info("[AGENT] created agent: %s", agent_id)
        return True

    log.warning("[AGENT] failed to create agent %s: %s", agent_id, (result.stderr or "").strip()[:200])
    return False


def _purge_agent_sessions(agent_id: str) -> None:
    """Delete OpenClaw transcript files so each call starts clean."""
    session_dir = _session_dir_for_agent(agent_id)
    if not session_dir.is_dir():
        return

    count = 0
    for path in session_dir.iterdir():
        try:
            if path.name == "sessions.json":
                path.write_text("{}", encoding="utf-8")
                count += 1
            elif path.is_file() and (path.name.endswith(".jsonl") or path.name.endswith(".lock")):
                path.unlink()
                count += 1
        except OSError:
            pass

    if count:
        log.info("[AGENT] purged %d session files from %s", count, session_dir)


def ensure_agent() -> str:
    """Ensure the dedicated enrich agent exists."""
    global _agent_id

    with _agent_lock:
        if _agent_id:
            return _agent_id

        agent_id = _configured_agent_id()
        _resolve_openclaw_path()
        if _agent_exists(agent_id):
            log.info("[AGENT] found existing agent: %s", agent_id)
        else:
            log.info("[AGENT] agent '%s' not found, creating...", agent_id)
            _create_agent(agent_id)
        _agent_id = agent_id
        return _agent_id


def _mark_rate_limited(stderr: str) -> None:
    global _rate_limit_until

    message = stderr.lower()
    if any(hint in message for hint in _RATE_LIMIT_HINTS):
        with _agent_lock:
            _rate_limit_until = time.monotonic() + DEFAULT_RATE_LIMIT_BACKOFF_SECONDS
        log.warning("[AGENT] rate limit detected, backing off %ss", DEFAULT_RATE_LIMIT_BACKOFF_SECONDS)


def _terminate_process(proc: subprocess.Popen[str]) -> None:
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()


def _extract_content(text: str) -> str:
    """Extract assistant text from raw or structured OpenClaw output."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return text.strip()

    if isinstance(data, dict):
        output = data.get("output")
        if isinstance(output, list):
            parts: list[str] = []
            for item in output:
                if not isinstance(item, dict):
                    continue
                content = item.get("content")
                if isinstance(content, list):
                    for block in content:
                        if isinstance(block, dict):
                            block_text = block.get("text")
                            if isinstance(block_text, str) and block_text.strip():
                                parts.append(block_text.strip())
                item_text = item.get("text")
                if isinstance(item_text, str) and item_text.strip():
                    parts.append(item_text.strip())
            if parts:
                return "\n".join(parts).strip()

        choices = data.get("choices")
        if isinstance(choices, list) and choices:
            message = choices[0].get("message", {})
            content = message.get("content")
            if isinstance(content, str):
                return content.strip()

        for key in ("content", "text"):
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()

    return text.strip()


def call_agent(
    prompt: str,
    *,
    timeout: float = DEFAULT_CLI_TIMEOUT,
    purge_sessions: bool = True,
) -> EnrichResponse:
    """Call the dedicated OpenClaw agent with OpenClaw CLI session hygiene."""
    if time.monotonic() < _rate_limit_until:
        remaining = int(_rate_limit_until - time.monotonic())
        return EnrichResponse(
            content="",
            success=False,
            source="openclaw_cli",
            error=f"rate limit backoff in effect ({remaining}s remaining)",
        )

    try:
        agent_id = ensure_agent()
        openclaw = _resolve_openclaw_path()
    except OpenClawAgentError as exc:
        return EnrichResponse(content="", success=False, source="openclaw_cli", error=str(exc))

    if purge_sessions:
        _purge_agent_sessions(agent_id)

    try:
        proc = subprocess.Popen(
            [
                openclaw,
                "agent",
                "--agent",
                agent_id,
                "--message",
                prompt,
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except (FileNotFoundError, OSError) as exc:
        return EnrichResponse(content="", success=False, source="openclaw_cli", error=str(exc))

    timed_out = False
    deadline = time.monotonic() + timeout
    try:
        while proc.poll() is None:
            if time.monotonic() > deadline:
                timed_out = True
                _terminate_process(proc)
                break
            time.sleep(0.25)

        stdout = proc.stdout.read() if proc.stdout else ""
        stderr = proc.stderr.read() if proc.stderr else ""
    finally:
        if purge_sessions:
            _purge_agent_sessions(agent_id)

    if timed_out:
        return EnrichResponse(
            content="",
            success=False,
            source="openclaw_cli",
            error=f"CLI timeout ({timeout}s)",
        )

    if proc.returncode != 0:
        error_msg = stderr.strip() or f"exit code {proc.returncode}"
        _mark_rate_limited(error_msg)
        log.warning("[AGENT] CLI failed: %s", error_msg[:200])
        return EnrichResponse(
            content="",
            success=False,
            source="openclaw_cli",
            error=error_msg,
        )

    if not stdout.strip():
        return EnrichResponse(
            content="",
            success=False,
            source="openclaw_cli",
            error="empty response",
        )

    content = _extract_content(stdout.strip())
    if not content:
        return EnrichResponse(
            content="",
            success=False,
            source="openclaw_cli",
            error="unable to extract response content",
        )

    return EnrichResponse(
        content=content,
        success=True,
        source="openclaw_cli",
        model="openclaw/agent",
    )


def parse_json_response(content: str) -> dict[str, Any] | list[Any]:
    """Parse JSON from an agent response. Delegates to the robust llm_client parser."""
    from crawler.enrich.generative.llm_client import parse_json_response as _parse
    result = _parse(content)
    return result if result is not None else {"raw": content}


async def enrich_with_llm(
    prompt: str,
    *,
    timeout: float = DEFAULT_CLI_TIMEOUT,
) -> EnrichResponse:
    """Async wrapper around the OpenClaw CLI style OpenClaw agent call."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, lambda: call_agent(prompt, timeout=timeout))
