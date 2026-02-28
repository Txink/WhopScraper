"""
股票交易记录：读写 data/stock_trade_records.json，并根据参考价/参考标签解析卖出数量。
格式与期权 trade_records 一致：{ "SYMBOL.US": [ { order_id, symbol, side, quantity, executed_quantity, price, status, submitted_at }, ... ] }
"""
import json
import os
from datetime import datetime, timedelta, date
from typing import Optional, List, Dict, Any

DEFAULT_STOCK_TRADE_RECORDS_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "data", "stock_trade_records.json"
)

# 价格匹配容差
PRICE_TOLERANCE = 0.02


def _path(path: str = None) -> str:
    return path or os.getenv("STOCK_TRADE_RECORDS_PATH", DEFAULT_STOCK_TRADE_RECORDS_PATH)


def _load_all(path: str = None) -> Dict[str, List[Dict]]:
    p = _path(path)
    try:
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    return data


def _save_all(data: Dict[str, List[Dict]], path: str = None) -> None:
    p = _path(path)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def append_stock_trade(symbol: str, order_info: Dict[str, Any], path: str = None) -> None:
    """
    交易成功后追加一条股票成交记录。
    order_info 应包含: order_id, symbol, side, quantity, executed_quantity, price, status, submitted_at 等。
    """
    if not symbol or not order_info:
        return
    key = (symbol or "").strip().upper()
    if not key.endswith(".US"):
        key = f"{key}.US"
    data = _load_all(path)
    if key not in data:
        data[key] = []
    data[key].insert(0, order_info)
    _save_all(data, path)


def _parse_date_from_label(label: str) -> Optional[datetime]:
    """从 sell_reference_label 解析日期：昨天、周五、今天。返回该日期的 date（用于过滤 submitted_at）。"""
    if not label or not isinstance(label, str):
        return None
    s = label.strip()
    today = datetime.now().date()
    if "昨天" in s:
        return today - timedelta(days=1)
    if "今天" in s:
        return today
    if "周五" in s or "礼拜五" in s:
        # 最近一个周五
        d = today
        while d.weekday() != 4:
            d -= timedelta(days=1)
        return d
    if "周四" in s:
        d = today
        while d.weekday() != 3:
            d -= timedelta(days=1)
        return d
    if "周三" in s:
        d = today
        while d.weekday() != 2:
            d -= timedelta(days=1)
        return d
    return None


def _ratio_from_sell_quantity(sell_quantity: Optional[str]) -> float:
    """将 sell_quantity 如 '1/2'、'全部' 转为比例。"""
    if not sell_quantity:
        return 1.0
    s = (sell_quantity or "").strip()
    if s == "全部" or not s:
        return 1.0
    if "/" in s:
        parts = s.split("/")
        if len(parts) == 2:
            try:
                return float(parts[0].strip()) / float(parts[1].strip())
            except (ValueError, ZeroDivisionError):
                pass
    if "%" in s:
        try:
            return float(s.replace("%", "").strip()) / 100.0
        except ValueError:
            pass
    return 1.0


def resolve_sell_quantity_from_records(
    ticker: str,
    reference_price: Optional[float] = None,
    reference_label: Optional[str] = None,
    sell_quantity_ratio: Optional[str] = None,
    path: str = None,
) -> Optional[int]:
    """
    根据 sell_reference_price、sell_reference_label 从 stock_trade_records 中汇总
    对应买入的成交股数，再按 sell_quantity（如 1/2）取比例，返回具体卖出股数。
    - reference_label 含「昨天」「周五」「今天」时按日期过滤；
    - reference_price 用于按成交价过滤（容差 PRICE_TOLERANCE）。
    """
    if not ticker:
        return None
    symbol = ticker.strip().upper()
    if not symbol.endswith(".US"):
        symbol = f"{symbol}.US"
    data = _load_all(path)
    orders = data.get(symbol, [])
    if not orders:
        return None

    target_date = _parse_date_from_label(reference_label or "")
    total = 0
    for o in orders:
        if not isinstance(o, dict):
            continue
        if (o.get("side") or "").upper() != "BUY":
            continue
        status = str(o.get("status") or "")
        if "filled" not in status.lower() and "Filled" not in status:
            continue
        try:
            q = float(o.get("executed_quantity") or o.get("quantity") or 0)
        except (TypeError, ValueError):
            continue
        price = o.get("price")
        if price is not None:
            try:
                p = float(price)
            except (TypeError, ValueError):
                p = None
        else:
            p = None
        if reference_price is not None and p is not None:
            if abs(p - reference_price) > PRICE_TOLERANCE:
                continue
        submitted = o.get("submitted_at")
        if target_date is not None and submitted:
            try:
                if isinstance(submitted, str):
                    order_date = date.fromisoformat(submitted[:10])
                elif hasattr(submitted, "date") and callable(getattr(submitted, "date")):
                    order_date = submitted.date()
                else:
                    order_date = submitted if isinstance(submitted, date) else None
                if order_date is not None and order_date != target_date:
                    continue
            except (ValueError, TypeError):
                pass
        total += int(q)

    if total <= 0:
        return None
    ratio = _ratio_from_sell_quantity(sell_quantity_ratio)
    return int(total * ratio)
