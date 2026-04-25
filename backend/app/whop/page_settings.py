"""PageSettings —— per-page 监听设置（去重开关、价格偏差容忍、stock ticker 白名单+数量）。

option page 的 settings.tickers = None；stock page 的 = {} 起步。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Literal

logger = logging.getLogger(__name__)


@dataclass
class TickerConfig:
    trade_quantity: int   # "常规仓" 对应的整股数；半仓 → 一半，1/3 → trade_quantity/3 …


@dataclass
class PageSettings:
    dedupe_processed_messages: bool = True
    price_deviation_tolerance: float = 1.0  # 单位：百分比（1.0 = 1%）
    tickers: dict[str, TickerConfig] | None = field(default_factory=dict)


DEFAULT_STOCK_SETTINGS = PageSettings(
    dedupe_processed_messages=True,
    price_deviation_tolerance=1.0,
    tickers={},
)

DEFAULT_OPTION_SETTINGS = PageSettings(
    dedupe_processed_messages=True,
    price_deviation_tolerance=5.0,
    tickers=None,
)


def default_settings_for(source: Literal["stock", "option"]) -> PageSettings:
    if source == "stock":
        return PageSettings(
            dedupe_processed_messages=DEFAULT_STOCK_SETTINGS.dedupe_processed_messages,
            price_deviation_tolerance=DEFAULT_STOCK_SETTINGS.price_deviation_tolerance,
            tickers={},
        )
    if source == "option":
        return PageSettings(
            dedupe_processed_messages=DEFAULT_OPTION_SETTINGS.dedupe_processed_messages,
            price_deviation_tolerance=DEFAULT_OPTION_SETTINGS.price_deviation_tolerance,
            tickers=None,
        )
    raise ValueError(f"unknown source: {source!r}")


def page_settings_to_dict(s: PageSettings) -> dict[str, Any]:
    out: dict[str, Any] = {
        "dedupe_processed_messages": s.dedupe_processed_messages,
        "price_deviation_tolerance": s.price_deviation_tolerance,
    }
    if s.tickers is not None:
        out["tickers"] = {k: {"trade_quantity": v.trade_quantity} for k, v in s.tickers.items()}
    return out


def page_settings_from_dict(
    d: dict[str, Any],
    *,
    source: Literal["stock", "option"],
) -> PageSettings:
    """Tolerant parser: missing keys → use defaults; ticker keys → uppercased."""
    base = default_settings_for(source)
    dedupe = bool(d.get("dedupe_processed_messages", base.dedupe_processed_messages))
    tol = float(d.get("price_deviation_tolerance", base.price_deviation_tolerance))
    tickers: dict[str, TickerConfig] | None
    if source == "option":
        tickers = None
    else:
        raw_tickers = d.get("tickers", {}) or {}
        tickers = {
            str(k).upper(): TickerConfig(trade_quantity=int(v["trade_quantity"]))
            for k, v in raw_tickers.items()
        }
    return PageSettings(
        dedupe_processed_messages=dedupe,
        price_deviation_tolerance=tol,
        tickers=tickers,
    )


# --------------------------------------------------------------------------- #
# Position size string → fraction multiplier                                    #
# --------------------------------------------------------------------------- #

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


def position_size_to_fraction(s: str | None) -> float:
    """把 stock_parser 解出来的 position_size 字符串 → 仓位比例倍数。

    未识别 / None → 1.0（按 trade_quantity 全量下单）。
    未识别时记 warning，便于后续补条目。
    """
    if not s:
        return 1.0
    s2 = s.strip()
    if s2 in _FRACTION_MAP:
        return _FRACTION_MAP[s2]
    logger.warning("unrecognized position_size %r — falling back to 1.0", s2)
    return 1.0
