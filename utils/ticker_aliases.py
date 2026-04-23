"""
中文昵称 → ticker 映射。消息里常见 "博通"/"奈飞双倍"/"微软双倍" 等昵称，需要在正则前做替换。
配置位于 config/ticker_aliases.json。
"""
import json
import os
import time
from typing import Dict, List, Tuple

DEFAULT_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "config", "ticker_aliases.json"
)

_CACHE_TTL = 1.0
_last_mtime: float = 0
_last_items: List[Tuple[str, str]] = []


def _load(path: str = None) -> Dict[str, str]:
    p = path or os.getenv("TICKER_ALIASES_PATH", DEFAULT_PATH)
    try:
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(k): str(v).upper() for k, v in data.items() if k and v}


def _get_items_sorted(path: str = None) -> List[Tuple[str, str]]:
    """按昵称长度降序返回 [(昵称, ticker), ...]，避免短昵称先匹配吃掉长的。"""
    global _last_mtime, _last_items
    p = path or os.getenv("TICKER_ALIASES_PATH", DEFAULT_PATH)
    try:
        mtime = os.path.getmtime(p)
    except OSError:
        mtime = 0
    if (time.time() - _last_mtime) > _CACHE_TTL or mtime > _last_mtime:
        _last_mtime = time.time()
        d = _load(p)
        _last_items = sorted(d.items(), key=lambda x: len(x[0]), reverse=True)
    return _last_items


def normalize_message(message: str, path: str = None) -> str:
    """把消息中的中文昵称替换为 ticker（前后加空格保证词边界）。长昵称优先。"""
    if not message:
        return message
    items = _get_items_sorted(path)
    out = message
    for alias, ticker in items:
        if alias in out:
            out = out.replace(alias, f" {ticker} ")
    return out


def get_aliased_tickers(path: str = None) -> List[str]:
    """所有可能从昵称映射出来的 ticker（大写，去重）。"""
    items = _get_items_sorted(path)
    seen = []
    for _, t in items:
        if t not in seen:
            seen.append(t)
    return seen
