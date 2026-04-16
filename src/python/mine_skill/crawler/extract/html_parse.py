"""Shared HTML parse entry: prefer lxml (closer to browser trees), fall back to html.parser."""
from __future__ import annotations

from bs4 import BeautifulSoup


def parse_html(html: str, *, features: str | None = None) -> BeautifulSoup:
    """Parse HTML with lxml by default; fall back to html.parser if lxml is missing or fails."""
    if features:
        return BeautifulSoup(html, features)
    try:
        return BeautifulSoup(html, "lxml")
    except Exception:
        return BeautifulSoup(html, "html.parser")
