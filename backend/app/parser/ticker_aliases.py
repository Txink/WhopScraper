"""
中文昵称 → ticker 映射。
配置位于 config/ticker_aliases.json（项目根目录）。
"""
from __future__ import annotations

import json
import os
from pathlib import Path

# Resolve path relative to project root (three levels up from this file:
# backend/app/parser/ticker_aliases.py → ../../.. = project root)
_PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
_DEFAULT_PATH = _PROJECT_ROOT / "config" / "ticker_aliases.json"

# Support override via env var for testing
_ENV_PATH = os.getenv("TICKER_ALIASES_PATH")

_items_cache: list[tuple[str, str]] | None = None


def _load(path: Path) -> dict[str, str]:
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(k): str(v).upper() for k, v in data.items() if k and v}


def _get_items_sorted() -> list[tuple[str, str]]:
    """按昵称长度降序返回 [(昵称, ticker), ...]，避免短昵称先匹配吃掉长的。"""
    global _items_cache
    if _items_cache is None:
        p = Path(_ENV_PATH) if _ENV_PATH else _DEFAULT_PATH
        d = _load(p)
        _items_cache = sorted(d.items(), key=lambda x: len(x[0]), reverse=True)
    return _items_cache


def resolve_alias(text_token: str) -> str | None:
    """若 text_token 是已知别名，返回对应 ticker（大写）；否则返回 None。"""
    if not text_token:
        return None
    items = _get_items_sorted()
    for alias, ticker in items:
        if alias == text_token:
            return ticker
    return None


def normalize_message(message: str) -> str:
    """把消息中的中文昵称替换为 ticker（前后加空格保证词边界）。长昵称优先。"""
    if not message:
        return message
    items = _get_items_sorted()
    out = message
    for alias, ticker in items:
        if alias in out:
            out = out.replace(alias, f" {ticker} ")
    return out
