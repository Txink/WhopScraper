"""Shared parser vocabularies — fraction maps for position size & sell quantity.

Originally lived in app/whop/page_settings.py. Moved here so parser_v2 can
import them without depending on the page_settings module (which would create
a circular import via the trader path).
"""

from __future__ import annotations

# position_size 短语 → 仓位倍数
_FRACTION_MAP: dict[str, float] = {
    "常规仓": 1.0,
    "中仓位": 1.0,
    "常规仓的一半": 0.5,
    "常规一半": 0.5,
    "常规的一半": 0.5,
    "半仓": 0.5,
    "一半": 0.5,
    "小仓位": 0.5,
    "轻仓": 0.5,
    "大仓位": 1.5,
    "重仓": 1.5,
    "满仓": 2.0,
    "1/2": 0.5,
    "1/3": 1 / 3,
    "2/3": 2 / 3,
    "1/4": 0.25,
    "1/5": 0.2,
    "三分之一": 1 / 3,
    "三分之二": 2 / 3,
    "四分之一": 0.25,
    "五分之一": 0.2,
}

# sell_quantity 短语 → 数量倍数
_SELL_FRACTION_MAP: dict[str, float] = {
    "1/2": 0.5,
    "1/3": 1 / 3,
    "1/4": 0.25,
    "2/3": 2 / 3,
    "3/4": 0.75,
    "全部": 1.0,
    "剩下": 1.0,
    "剩下一半": 0.5,
    "部分": 1.0,
    "那部分": 1.0,
}
