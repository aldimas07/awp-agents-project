"""Fetch backend selection and wrappers.

The unified entry point is `unified_fetch()` which routes all fetch operations
through FetchEngine. This replaces the old orchestrator.py.
"""

from . import browser_common
from .backend_router import get_escalation_backend, resolve_backend
from .browser_pool import BrowserPool
from .engine import FetchEngine
from .models import FetchTiming, RawFetchResult, SessionStatus
from .session_manager import SessionManager
from .unified import unified_fetch, fetch_with_backend  # fetch_with_backend is deprecated alias
from .wait_strategy import apply_wait_strategy, get_wait_config

__all__ = [
    "BrowserPool",
    "FetchEngine",
    "FetchTiming",
    "RawFetchResult",
    "SessionManager",
    "SessionStatus",
    "apply_wait_strategy",
    "browser_common",
    "fetch_with_backend",  # deprecated, use unified_fetch
    "get_escalation_backend",
    "get_wait_config",
    "resolve_backend",
    "unified_fetch",
]
