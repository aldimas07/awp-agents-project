from __future__ import annotations

try:
    from playwright.sync_api import sync_playwright
except ModuleNotFoundError:  # pragma: no cover
    sync_playwright = None

from .browser_common import persist_storage_state
from .browser_common import resolve_storage_state_path
from .browser_common import run_sync_compatible


def fetch_with_playwright(url: str, storage_state_path: str | None = None) -> dict:
    if sync_playwright is None:
        raise RuntimeError("playwright is not installed")

    def run() -> dict:
        storage_state = resolve_storage_state_path(storage_state_path)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                context = browser.new_context(storage_state=storage_state)
                try:
                    page = context.new_page()
                    page.goto(url, wait_until="networkidle")
                    html = page.content()
                    screenshot = page.screenshot(type="png")
                    if storage_state_path is not None:
                        persist_storage_state(storage_state_path, context.storage_state())
                finally:
                    context.close()
            finally:
                browser.close()
        return {
            "url": url,
            "html": html,
            "content_type": "text/html; charset=utf-8",
            "content_bytes": html.encode("utf-8"),
            "screenshot_bytes": screenshot,
            "backend": "playwright",
        }

    return run_sync_compatible(run)
