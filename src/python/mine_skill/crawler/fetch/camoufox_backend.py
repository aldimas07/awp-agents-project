from __future__ import annotations

try:
    from camoufox.sync_api import Camoufox
except ModuleNotFoundError:  # pragma: no cover
    Camoufox = None

from .browser_common import persist_storage_state
from .browser_common import resolve_storage_state_path
from .browser_common import run_sync_compatible


def fetch_with_camoufox(url: str, storage_state_path: str | None = None) -> dict:
    if Camoufox is None:
        raise RuntimeError("camoufox is not installed")

    def run() -> dict:
        storage_state = resolve_storage_state_path(storage_state_path)
        with Camoufox(headless=True) as browser:
            context = browser.new_context(storage_state=storage_state)
            try:
                page = context.new_page()
                page.goto(url, wait_until="domcontentloaded")
                html = page.content()
                screenshot = page.screenshot(type="png")
                if storage_state_path is not None:
                    persist_storage_state(storage_state_path, context.storage_state())
            finally:
                context.close()
        return {
            "url": url,
            "html": html,
            "content_type": "text/html; charset=utf-8",
            "content_bytes": html.encode("utf-8"),
            "screenshot_bytes": screenshot,
            "backend": "camoufox",
        }

    return run_sync_compatible(run)
