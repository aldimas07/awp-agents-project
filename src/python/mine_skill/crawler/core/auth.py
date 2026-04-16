from __future__ import annotations

from typing import Any

import httpx

from crawler.contracts import CrawlerConfig
from crawler.fetch.error_classifier import FetchError
from crawler.fetch.session_store import SessionStore


def _human_next_action(agent_hint: str) -> str:
    mapping = {
        "refresh_session": "refresh login session and retry",
        "wait_and_retry": "wait and retry",
        "retry_later": "retry later",
        "notify_user": "notify user",
        "retry": "retry",
        "inspect": "inspect error and retry",
        "inspect_agent_browser": "inspect auto-browser setup",
        "inspect_auto_browser_setup": "inspect auto-browser setup",
        "inspect_auto_browser_state": "inspect auto-browser state",
        "retry_export_session": "retry session export",
        "open_public_url_and_complete_login": "open public URL and complete login",
        "provide_state": "provide cookies or storage state",
        "complete_auto_login": "complete login in auto-browser and retry",
        "complete_phone_verification": "complete LinkedIn phone verification",
        "switch_network_region": "switch to a non-restricted network region and retry",
    }
    return mapping.get(agent_hint, agent_hint.replace("_", " "))


def resolve_storage_state_path(
    *,
    config: CrawlerConfig,
    platform: str,
    requires_auth: bool,
    session_store: SessionStore,
) -> str | None:
    if not requires_auth:
        return None
    if config.cookies_path is not None:
        return str(session_store.import_cookies(platform, config.cookies_path))
    if session_store.load(platform) is not None:
        return str(session_store.root / f"{platform}.json")
    if config.auto_login:
        return export_session_via_auto_browser(session_store=session_store, platform=platform)
    return None


def refresh_storage_state_path(
    *,
    config: CrawlerConfig,
    platform: str,
    requires_auth: bool,
    session_store: SessionStore,
) -> str | None:
    if not requires_auth or not config.auto_login:
        return None
    return export_session_via_auto_browser(session_store=session_store, platform=platform)


def export_session_via_auto_browser(*, session_store: SessionStore, platform: str) -> str:
    from crawler.integrations.browser_auth import (
        AutoBrowserAuthBridge,
        get_default_auto_browser_script,
        get_default_auto_browser_workdir,
    )

    bridge = AutoBrowserAuthBridge(
        script_path=get_default_auto_browser_script(),
        workdir=get_default_auto_browser_workdir(),
    )
    session = bridge.ensure_exported_session(
        platform=platform,
        output_dir=session_store.root.parent,
        cleanup_on_success=True,
    )
    return str(session_store.import_cookies(platform, session.session_path))


def build_auth_required_error(
    *,
    platform: str,
    resource_type: str | None,
    auto_login_enabled: bool,
) -> dict[str, Any]:
    fetch_error = FetchError(
        "AUTH_REQUIRED",
        "complete_auto_login" if auto_login_enabled else "provide_state",
        f"{platform} requires authenticated browser state",
        auto_login_enabled,
    )
    return build_error_from_fetch_error(
        platform=platform,
        resource_type=resource_type,
        fetch_error=fetch_error,
        stage="fetch",
        message=fetch_error.message,
    )


def classify_auth_failure(
    *,
    platform: str,
    resource_type: str | None,
    exception: Exception,
    has_session: bool,
    stage: str,
) -> dict[str, Any] | None:
    fetch_error = getattr(exception, "fetch_error", None)
    if isinstance(fetch_error, FetchError):
        return build_error_from_fetch_error(
            platform=platform,
            resource_type=resource_type,
            fetch_error=fetch_error,
            stage=stage,
            message=str(exception),
            exception=exception,
        )

    if has_session and isinstance(exception, httpx.HTTPStatusError) and exception.response is not None:
        if exception.response.status_code in {401, 403}:
            return build_error_from_fetch_error(
                platform=platform,
                resource_type=resource_type,
                fetch_error=FetchError(
                    "AUTH_EXPIRED",
                    "refresh_session",
                    str(exception),
                    True,
                    exception.response.status_code,
                ),
                stage=stage,
                message=str(exception),
                exception=exception,
            )
    return None


def build_error_from_fetch_error(
    *,
    platform: str,
    resource_type: str | None,
    fetch_error: FetchError,
    stage: str,
    message: str,
    exception: Exception | None = None,
) -> dict[str, Any]:
    error = {
        "platform": platform,
        "resource_type": resource_type,
        "stage": stage,
        "status": "failed",
        "error_code": fetch_error.error_code,
        "retryable": fetch_error.retryable,
        "next_action": _human_next_action(fetch_error.agent_hint),
        "message": message,
    }
    if exception is not None:
        public_url = str(getattr(exception, "public_url", "") or "").strip()
        login_url = str(getattr(exception, "login_url", "") or "").strip()
        if public_url:
            error["public_url"] = public_url
        if login_url:
            error["login_url"] = login_url
    return error
