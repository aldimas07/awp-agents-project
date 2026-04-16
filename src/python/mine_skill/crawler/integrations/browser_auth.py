from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from crawler.fetch.error_classifier import FetchError


def get_default_auto_browser_script() -> Path:
    return Path(__file__).resolve().parents[2] / "auto-browser" / "scripts" / "vrd.py"


def get_default_auto_browser_workdir() -> Path:
    return Path(os.environ.get("WORKDIR", Path.home() / ".openclaw" / "vrd-data"))


def get_platform_login_url(platform: str) -> str:
    login_urls = {
        "linkedin": "https://www.linkedin.com/login",
    }
    return login_urls.get(platform, "")


def get_platform_login_guide_text(platform: str) -> str:
    platform_name = platform.capitalize()
    if platform == "linkedin":
        platform_name = "LinkedIn"
    return f"Complete {platform_name} login in the remote browser, then click Done / Continue."


def _is_local_browser_mode(state: dict[str, Any]) -> bool:
    runtime_platform = str(state.get("RUNTIME_PLATFORM", "")).strip().lower()
    mode = str(state.get("MODE", "")).strip().lower()
    return runtime_platform == "windows-local" or mode.endswith("-local")


def _load_storage_state_payload(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict) and isinstance(payload.get("storage_state"), dict):
        return payload["storage_state"]
    return payload if isinstance(payload, dict) else {}


def _session_has_login_cookie(platform: str, session_path: Path) -> bool:
    if not session_path.exists():
        return False
    payload = _load_storage_state_payload(session_path)
    cookies = payload.get("cookies", []) if isinstance(payload, dict) else []
    cookie_names = {
        str(item.get("name"))
        for item in cookies
        if isinstance(item, dict) and item.get("name")
    }
    if platform == "linkedin":
        return "li_at" in cookie_names
    return bool(cookie_names)


@dataclass(frozen=True, slots=True)
class AutoBrowserSession:
    platform: str
    session_path: Path
    public_url: str
    switch_token: str
    login_url: str
    requires_user_action: bool
    started_by_bridge: bool
    cleanup_performed: bool
    local_browser_mode: bool
    guide_active: bool


class AutoBrowserAuthError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        error_code: str,
        agent_hint: str,
        retryable: bool,
        public_url: str = "",
        login_url: str = "",
    ) -> None:
        super().__init__(message)
        self.public_url = public_url
        self.login_url = login_url
        self.fetch_error = FetchError(error_code, agent_hint, message, retryable)  # type: ignore[assignment]


@dataclass(frozen=True, slots=True)
class AutoBrowserAuthBridge:
    script_path: Path
    workdir: Path
    wait_timeout_seconds: int = 300

    def ensure_exported_session(
        self,
        *,
        platform: str,
        output_dir: Path,
        login_url: str | None = None,
        guide_text: str | None = None,
        cleanup_on_success: bool = False,
    ) -> AutoBrowserSession:
        session = self.prepare_session(
            platform=platform,
            output_dir=output_dir,
            login_url=login_url,
            guide_text=guide_text,
            cleanup_on_success=cleanup_on_success,
        )
        if not session.requires_user_action:
            return session
        return self.complete_prepared_session(
            session,
            cleanup_on_success=cleanup_on_success,
        )

    def prepare_session(
        self,
        *,
        platform: str,
        output_dir: Path,
        login_url: str | None = None,
        guide_text: str | None = None,
        cleanup_on_success: bool = False,
    ) -> AutoBrowserSession:
        self._ensure_script_exists()
        resolved_login_url = (login_url or get_platform_login_url(platform)).strip()
        started_by_bridge = False
        try:
            started_by_bridge = self._ensure_vrd_running(resolved_login_url)
            self._open_login_page(resolved_login_url)
        except AutoBrowserAuthError:
            raise
        except Exception as exc:
            raise AutoBrowserAuthError(
                str(exc),
                error_code="AUTH_AUTO_LOGIN_FAILED",
                agent_hint="inspect_auto_browser_setup",
                retryable=False,
                login_url=resolved_login_url,
            ) from exc
        state = self._wait_for_state()
        local_browser_mode = _is_local_browser_mode(state)
        public_url = str(state.get("PUBLIC_URL", "")).strip()
        switch_token = str(state.get("SWITCH_TOKEN", "")).strip()
        if not switch_token or (not public_url and not local_browser_mode):
            raise AutoBrowserAuthError(
                "auto-browser started but PUBLIC_URL or SWITCH_TOKEN is missing",
                error_code="AUTH_AUTO_LOGIN_FAILED",
                agent_hint="inspect_auto_browser_state",
                retryable=False,
                login_url=resolved_login_url,
            )

        session_path = output_dir / ".sessions" / f"{platform}.auto-browser.json"
        if self._try_export_existing_session(platform, session_path):
            cleanup_performed = cleanup_on_success and started_by_bridge and self._stop_vrd()
            return AutoBrowserSession(
                platform=platform,
                session_path=session_path,
                public_url=public_url,
                switch_token=switch_token,
                login_url=resolved_login_url,
                requires_user_action=False,
                started_by_bridge=started_by_bridge,
                cleanup_performed=cleanup_performed,
                local_browser_mode=local_browser_mode,
                guide_active=False,
            )

        prompt = guide_text or get_platform_login_guide_text(platform)
        self._show_login_guide_message(
            public_url=public_url,
            switch_token=switch_token,
            guide_text=prompt,
        )
        return AutoBrowserSession(
            platform=platform,
            session_path=session_path,
            public_url=public_url,
            switch_token=switch_token,
            login_url=resolved_login_url,
            requires_user_action=True,
            started_by_bridge=started_by_bridge,
            cleanup_performed=False,
            local_browser_mode=local_browser_mode,
            guide_active=True,
        )

    def complete_prepared_session(
        self,
        session: AutoBrowserSession,
        *,
        cleanup_on_success: bool = False,
    ) -> AutoBrowserSession:
        try:
            if session.local_browser_mode:
                self._wait_for_local_login(
                    platform=session.platform,
                    session_path=session.session_path,
                    login_url=session.login_url,
                )
            elif session.public_url:
                self._poll_continue_signal(
                    session.switch_token,
                    platform=session.platform,
                    session_path=session.session_path,
                    public_url=session.public_url,
                    login_url=session.login_url,
                )
            self._export_session(session.platform, session.session_path)
        except AutoBrowserAuthError:
            raise
        except Exception as exc:
            raise AutoBrowserAuthError(
                str(exc),
                error_code="AUTH_SESSION_EXPORT_FAILED",
                agent_hint="retry_export_session",
                retryable=True,
                public_url=session.public_url,
                login_url=session.login_url,
            ) from exc
        finally:
            if session.guide_active:
                self._clear_login_guide(session.switch_token)

        cleanup_performed = session.cleanup_performed or (cleanup_on_success and session.started_by_bridge and self._stop_vrd())
        return AutoBrowserSession(
            platform=session.platform,
            session_path=session.session_path,
            public_url=session.public_url,
            switch_token=session.switch_token,
            login_url=session.login_url,
            requires_user_action=not self._session_has_login_cookie_or_none(session.platform, session.session_path),
            started_by_bridge=session.started_by_bridge,
            cleanup_performed=cleanup_performed,
            local_browser_mode=session.local_browser_mode,
            guide_active=False,
        )

    def _ensure_script_exists(self) -> None:
        if not self.script_path.exists():
            raise RuntimeError(f"auto-browser script not found: {self.script_path}")

    _ENV_ALLOWLIST = {
        "PATH", "HOME", "USER", "LANG", "LC_ALL", "TERM", "SHELL",
        "DISPLAY", "XDG_RUNTIME_DIR", "DBUS_SESSION_BUS_ADDRESS",
        "TMPDIR", "TMP", "TEMP",
        # Python/Node
        "PYTHONPATH", "VIRTUAL_ENV", "NODE_PATH", "NVM_DIR",
        # Project-specific
        "WORKDIR", "GEOM", "DEPTH", "DISPLAY_NUM",
    }

    def _base_env(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        env = {k: v for k, v in os.environ.items() if k in self._ENV_ALLOWLIST or k.startswith("VRD_")}
        env["WORKDIR"] = str(self.workdir)
        if extra:
            env.update(extra)
        return env

    def _run_vrd(
        self,
        *args: str,
        extra_env: dict[str, str] | None = None,
        timeout: int = 60,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(self.script_path), *args],
            capture_output=True,
            text=True,
            env=self._base_env(extra_env),
            timeout=timeout,
        )

    def _run_agent_browser(self, *args: str) -> subprocess.CompletedProcess[str]:
        agent_browser_bin = shutil.which("agent-browser") or shutil.which("agent-browser.cmd") or "agent-browser"
        return subprocess.run(
            [agent_browser_bin, "--cdp", "9222", "--session", "vrd", *args],
            capture_output=True,
            text=True,
            env=self._base_env(),
            timeout=120,
        )

    def _ensure_vrd_running(self, login_url: str) -> bool:
        status = self._run_vrd("status")
        if status.returncode == 0:
            return False

        extra_env = {"AUTO_LAUNCH_CHROME": "1"}
        if login_url:
            extra_env["AUTO_LAUNCH_URL"] = login_url
        start = self._run_vrd("start", extra_env=extra_env)
        if start.returncode != 0:
            raise RuntimeError(
                "auto-browser failed to start: "
                + (start.stderr.strip() or start.stdout.strip() or "unknown error")
            )
        return True

    def _stop_vrd(self) -> bool:
        try:
            stopped = self._run_vrd("stop")
        except Exception:
            return False
        return stopped.returncode == 0

    def _wait_for_state(self) -> dict[str, Any]:
        state_path = self.workdir / "state.json"
        deadline = time.time() + 45
        last_error = "state file missing"
        while time.time() < deadline:
            try:
                if state_path.exists():
                    state = json.loads(state_path.read_text(encoding="utf-8"))
                    if isinstance(state, dict) and state.get("CDP_PORT"):
                        return state
            except Exception as exc:  # pragma: no cover - defensive runtime path
                last_error = str(exc)
            time.sleep(1)
        raise RuntimeError(f"Timed out waiting for auto-browser state: {last_error}")

    def _request_json(
        self,
        path: str,
        *,
        token: str,
        method: str = "GET",
        body: dict[str, Any] | None = None,
        timeout: float = 10.0,
    ) -> dict[str, Any]:
        url = f"http://127.0.0.1:6090{path}"
        sep = "&" if "?" in url else "?"
        url = f"{url}{sep}{urlencode({'token': token})}"
        data: bytes | None = None
        headers: dict[str, str] = {}
        if body is not None:
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = Request(url, data=data, headers=headers, method=method)
        try:
            with urlopen(request, timeout=timeout) as response:
                payload = response.read().decode("utf-8")
        except URLError as exc:  # pragma: no cover - runtime network path
            raise RuntimeError(f"auto-browser control plane request failed: {exc}") from exc
        parsed = json.loads(payload)
        if not isinstance(parsed, dict):
            raise RuntimeError("auto-browser control plane returned invalid JSON")
        return parsed

    def _open_login_page(self, login_url: str) -> None:
        if not login_url:
            return
        opened = self._run_agent_browser("open", login_url)
        if opened.returncode != 0:
            raise AutoBrowserAuthError(
                "auto-browser failed to open login page: "
                + (opened.stderr.strip() or opened.stdout.strip() or "unknown error"),
                error_code="AUTH_AUTO_LOGIN_FAILED",
                agent_hint="inspect_agent_browser",
                retryable=False,
                login_url=login_url,
            )
        # LinkedIn login may never reach networkidle; best-effort wait only.
        try:
            subprocess.run(
                [
                    shutil.which("agent-browser") or shutil.which("agent-browser.cmd") or "agent-browser",
                    "--cdp",
                    "9222",
                    "--session",
                    "vrd",
                    "wait",
                    "--load",
                    "networkidle",
                ],
                capture_output=True,
                text=True,
                env=self._base_env(),
                timeout=10,
            )
        except subprocess.TimeoutExpired:
            pass

    def _show_login_guide_message(
        self,
        public_url: str,
        switch_token: str,
        guide_text: str,
    ) -> None:
        self._request_json(
            "/guide",
            token=switch_token,
            method="POST",
            body={"text": guide_text, "kind": "action"},
        )
        print(f"[AUTH] {guide_text}")
        if public_url:
            print("[AUTH] Open this URL to continue:")
            print(public_url)
        else:
            print("[AUTH] Local browser opened; complete login there.")

    def _clear_login_guide(self, switch_token: str) -> None:
        if not switch_token:
            return
        try:
            self._request_json("/guide", token=switch_token, method="DELETE")
        except Exception:
            pass

    def _try_export_existing_session(self, platform: str, session_path: Path) -> bool:
        probe_path = session_path.with_suffix(".probe.json")
        try:
            self._export_session(platform, probe_path)
            if _session_has_login_cookie(platform, probe_path):
                session_path.parent.mkdir(parents=True, exist_ok=True)
                probe_path.replace(session_path)
                return True
        except Exception:
            return False
        finally:
            # Clean up probe file if session was not successfully moved
            if probe_path.exists():
                try:
                    probe_path.unlink()
                except OSError:
                    pass
        return False

    def _session_has_login_cookie_or_none(self, platform: str, session_path: Path) -> bool:
        try:
            return _session_has_login_cookie(platform, session_path)
        except Exception:
            return False

    def _wait_for_local_login(self, *, platform: str, session_path: Path, login_url: str) -> None:
        deadline = time.time() + self.wait_timeout_seconds
        probe_path = session_path.with_suffix(".probe.json")
        while time.time() < deadline:
            try:
                self._export_session(platform, probe_path)
                if _session_has_login_cookie(platform, probe_path):
                    return
            except Exception:
                pass
            time.sleep(2)
        raise AutoBrowserAuthError(
            "Timed out waiting for local browser login",
            error_code="AUTH_INTERACTIVE_TIMEOUT",
            agent_hint="open_local_browser_and_complete_login",
            retryable=True,
            login_url=login_url,
        )

    def _poll_continue_signal(
        self,
        switch_token: str,
        *,
        platform: str,
        session_path: Path,
        public_url: str,
        login_url: str,
    ) -> None:
        after = 0.0
        deadline = time.time() + self.wait_timeout_seconds
        while time.time() < deadline:
            if self._try_export_existing_session(platform, session_path):
                return
            payload = self._request_json(
                f"/continue/poll?after={after}&timeout=5",
                token=switch_token,
                method="GET",
                timeout=8.0,
            )
            after = float(payload.get("ts", after) or after)
            if payload.get("signaled") is True:
                exported = self._try_export_existing_session(platform, session_path)
                if not exported:
                    import logging
                    logging.getLogger("browser_auth").warning(
                        "User signaled done but session export failed for %s", platform
                    )
                return
        raise AutoBrowserAuthError(
            "Timed out waiting for user to finish login",
            error_code="AUTH_INTERACTIVE_TIMEOUT",
            agent_hint="open_public_url_and_complete_login",
            retryable=True,
            public_url=public_url,
            login_url=login_url,
        )

    def _export_session(self, platform: str, session_path: Path) -> None:
        export = self._run_vrd("export-session", platform, str(session_path))
        if export.returncode != 0:
            raise RuntimeError(
                f"Failed to export {platform} session: "
                + (export.stderr.strip() or export.stdout.strip() or "unknown error")
            )
