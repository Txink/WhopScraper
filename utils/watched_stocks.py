"""
关注股票列表与股票仓位配置：从文件读取，支持运行期间修改实时生效。
配置格式：{ "ticker小写": { "position": 股数, "bucket": 常规仓比例 }, ... }
position = 该股票总仓位股数；bucket = 常规仓占比（如 0.3）。
常规仓 = position * bucket，常规仓的一半 = position * bucket * 0.5（具体股数）。
"""
import json
import os
import time
from typing import Set, Optional, Dict, Any

DEFAULT_WATCHED_STOCKS_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "data", "watched_stocks.json"
)

_CACHE_TTL = 1.0
_last_mtime: float = 0
_last_path: str = ""
_last_data: Optional[Dict[str, Any]] = None


def _load_watched_data(path: str = None) -> Dict[str, Any]:
    """读取配置文件。格式：{ "ticker小写": { "position": 股数, "bucket": 常规仓比例 }, ... }"""
    p = path or os.getenv("WATCHED_STOCKS_PATH", DEFAULT_WATCHED_STOCKS_PATH)
    try:
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {k: v for k, v in data.items() if k and not k.startswith("_") and isinstance(v, dict) and "position" in v}


def _get_bucket(entry: dict) -> float:
    """常规仓比例，支持 bucket 或 regular_ratio，默认 1/3。"""
    for key in ("bucket", "regular_ratio"):
        r = entry.get(key)
        if r is None:
            continue
        if isinstance(r, (int, float)):
            return float(r)
        if isinstance(r, str):
            s = r.strip()
            if s == "1/3":
                return 1.0 / 3.0
            if "/" in s:
                a, _, b = s.partition("/")
                try:
                    return float(a.strip()) / float(b.strip())
                except ValueError:
                    pass
            try:
                return float(s)
            except ValueError:
                pass
    return 1.0 / 3.0


def _get_cached(path: str = None) -> Dict[str, Any]:
    global _last_mtime, _last_path, _last_data
    p = path or os.getenv("WATCHED_STOCKS_PATH", DEFAULT_WATCHED_STOCKS_PATH)
    try:
        mtime = os.path.getmtime(p)
    except OSError:
        mtime = 0
    if p != _last_path or (time.time() - _last_mtime) > _CACHE_TTL or mtime > _last_mtime:
        _last_path = p
        _last_mtime = time.time()
        _last_data = _load_watched_data(p)
    return _last_data or {}


def get_watched_tickers(path: str = None) -> Set[str]:
    """获取关注股票 ticker 集合（大写）。"""
    data = _get_cached(path)
    return {k.strip().upper() for k in data if k}


def get_stock_position_shares(ticker: str = None, path: str = None) -> Optional[int]:
    """获取某股票总仓位股数，取 config[ticker]["position"]。"""
    if not ticker:
        return None
    data = _get_cached(path)
    entry = data.get(ticker.strip().lower())
    if isinstance(entry, dict) and "position" in entry:
        try:
            return int(entry["position"])
        except (TypeError, ValueError):
            pass
    return None


def get_bucket_ratio(ticker: str = None, path: str = None) -> float:
    """常规仓占比，默认 1/3。"""
    if not ticker:
        return 1.0 / 3.0
    data = _get_cached(path)
    entry = data.get(ticker.strip().lower())
    if isinstance(entry, dict):
        return _get_bucket(entry)
    return 1.0 / 3.0


def resolve_position_size_to_shares(position_size: str, ticker: str = None, path: str = None) -> Optional[int]:
    """
    将「常规仓」「常规仓的一半」「常规一半」「常规的一半」解析为具体股数。
    - 常规仓 -> position * bucket
    - 常规仓的一半 / 常规一半 / 常规的一半 -> position * bucket * 0.5（向下取整）
    """
    if not position_size or not isinstance(position_size, str):
        return None
    pos = get_stock_position_shares(ticker=ticker, path=path)
    if pos is None or pos <= 0:
        return None
    bucket = get_bucket_ratio(ticker=ticker, path=path)
    s = position_size.strip()
    if "常规仓" in s and ("一半" in s or "1/2" in s):
        return int(pos * bucket * 0.5)
    if "常规一半" in s or "常规的一半" in s or s == "常规一半" or s == "常规的一半":
        return int(pos * bucket * 0.5)
    if "常规仓" in s or s == "常规仓":
        return int(pos * bucket)
    return None


def is_watched(ticker: str, path: str = None) -> bool:
    """判断某 ticker 是否在关注列表中。"""
    ticker = (ticker or "").strip().upper()
    if not ticker:
        return False
    watched = get_watched_tickers(path)
    if not watched:
        return True
    return ticker in watched
