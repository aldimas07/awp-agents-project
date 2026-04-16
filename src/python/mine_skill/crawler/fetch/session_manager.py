from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

from .models import SessionStatus

logger = logging.getLogger(__name__)

# Platform-specific critical cookies that indicate a valid session.
_CRITICAL_COOKIES: dict[str, list[str]] = {
    "linkedin": ["li_at", "JSESSIONID"],
    "amazon": ["session-id", "session-token"],
    "base_chain": [],
    "wikipedia": [],
    "arxiv": [],
}


class SessionManager:
    """Validates and manages session state (cookies/storage_state) per platform."""

    def __init__(self, session_root: Path) -> None:
        self._session_root = session_root
        self._session_root.mkdir(parents=True, exist_ok=True)

    def _storage_path(self, platform: str) -> Path:
        return self._session_root / f"{platform}.json"

    def _load_state(self, platform: str) -> dict | None:
        path = self._storage_path(platform)
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            logger.warning("Corrupt session file for %s", platform)
            return None

    def validate_session(self, platform: str) -> SessionStatus:
        """Check if the session for a platform is valid."""
        state = self._load_state(platform)
        if state is None:
            return SessionStatus.MISSING

        cookies = state.get("cookies", [])
        if not cookies:
            return SessionStatus.MISSING

        required = _CRITICAL_COOKIES.get(platform, [])
        if not required:
            # Platforms without critical cookie requirements are always valid if cookies exist
            return SessionStatus.VALID

        cookie_map: dict[str, dict] = {}
        for c in cookies:
            name = c.get("name", "")
            cookie_map[name] = c

        for name in required:
            if name not in cookie_map:
                return SessionStatus.INVALID
            cookie = cookie_map[name]
            # Check expiry if present
            expires = cookie.get("expires", -1)
            if isinstance(expires, (int, float)) and expires > 0:
                if expires < time.time():
                    return SessionStatus.EXPIRED

        return SessionStatus.VALID

    async def refresh_session(self, platform: str, context: Any) -> bool:
        """Save the current browser context's storage_state back to disk.

        Returns True if cookies were updated.
        """
        try:
            state = await context.storage_state()
            path = self._storage_path(platform)
            old_data = self._load_state(platform)
            path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")

            if old_data is None:
                return True
            old_cookies = {c.get("name"): c.get("value") for c in old_data.get("cookies", [])}
            new_cookies = {c.get("name"): c.get("value") for c in state.get("cookies", [])}
            return old_cookies != new_cookies
        except Exception:
            logger.warning("Failed to refresh session for %s", platform, exc_info=True)
            return False

    def has_valid_session(self, platform: str) -> bool:
        return self.validate_session(platform) == SessionStatus.VALID
