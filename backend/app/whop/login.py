"""Whop cookie management — load/save .auth/whop_cookie.json."""
from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def cookie_path(root: Path | None = None) -> Path:
    """Return the path of the saved Whop cookie JSON."""
    if root is None:
        # Default: project root (one level up from backend/)
        root = Path(__file__).resolve().parents[3]
    return root / ".auth" / "whop_cookie.json"


def load_cookie_state(path: Path | None = None) -> dict[str, Any] | None:
    """Load Playwright storage_state JSON. Returns None if missing/invalid."""
    p = path or cookie_path()
    if not p.is_file():
        return None
    try:
        data: dict[str, Any] = json.loads(p.read_text(encoding="utf-8"))
        return data
    except (OSError, json.JSONDecodeError) as e:
        logger.warning("failed to load cookie state from %s: %s", p, e)
        return None


def save_cookie_state(state: dict[str, Any], path: Path | None = None) -> None:
    """Persist Playwright storage_state to disk. Creates parent dir if missing."""
    p = path or cookie_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info("saved cookie state to %s", p)


async def login_if_needed(
    is_logged_in: Callable[[], Awaitable[bool]],
    interactive_login: Callable[[], Awaitable[dict[str, Any]]],
    save: Callable[[dict[str, Any]], None] = save_cookie_state,
) -> bool:
    """If not logged in, run interactive_login (which returns a fresh storage_state)
    and save it. Returns True if a login occurred."""
    if await is_logged_in():
        return False
    state = await interactive_login()
    save(state)
    return True
