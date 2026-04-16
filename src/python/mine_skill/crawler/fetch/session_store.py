from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from crawler.output import read_json_file


def _cookie_header_to_storage_state(platform: str, cookie_header: str) -> dict[str, Any]:
    cookies: list[dict[str, Any]] = []
    for chunk in cookie_header.split(";"):
        item = chunk.strip()
        if not item or "=" not in item:
            continue
        name, value = item.split("=", 1)
        cookies.append(
            {
                "name": name.strip(),
                "value": value.strip(),
                "domain": ".linkedin.com" if platform == "linkedin" else "",
                "path": "/",
            }
        )
    return {"cookies": cookies, "origins": []}


def _cookie_mapping_to_storage_state(platform: str, payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "cookies": [
            {
                "name": str(name),
                "value": str(value),
                "domain": ".linkedin.com" if platform == "linkedin" else "",
                "path": "/",
            }
            for name, value in payload.items()
            if isinstance(value, str)
        ],
        "origins": [],
    }


def _normalize_storage_state(platform: str, payload: Any) -> dict[str, Any]:
    if isinstance(payload, list):
        return {"cookies": payload, "origins": []}

    if isinstance(payload, dict) and "storage_state" in payload:
        return _normalize_storage_state(platform, payload["storage_state"])

    if isinstance(payload, dict):
        cookie_header = payload.get("cookie_header") or payload.get("Cookie") or payload.get("cookie")
        if isinstance(cookie_header, str):
            return _cookie_header_to_storage_state(platform, cookie_header)
        if "cookies" in payload:
            return {
                "cookies": list(payload.get("cookies", [])),
                "origins": list(payload.get("origins", [])),
            }
        return _cookie_mapping_to_storage_state(platform, payload)

    raise ValueError("cookies file must contain a cookie list or Playwright storage state")


class SessionStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def save(self, platform: str, payload: dict) -> Path:
        path = self.root / f"{platform}.json"
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def load(self, platform: str) -> dict | None:
        path = self.root / f"{platform}.json"
        if not path.exists():
            return None
        payload = read_json_file(path)
        return payload if isinstance(payload, dict) else None

    def import_cookies(self, platform: str, cookies_path: Path) -> Path:
        payload = read_json_file(cookies_path)
        storage_state = _normalize_storage_state(platform, payload)
        return self.save(platform, storage_state)
