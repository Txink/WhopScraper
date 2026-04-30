"""PageSettings —— per-page 监听设置（去重开关、价格偏差容忍、stock ticker 白名单+数量）。

option page 的 settings.tickers = None；stock page 的 = {} 起步。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Literal

from app.parser.vocab_shared import _FRACTION_MAP, _SELL_FRACTION_MAP

logger = logging.getLogger(__name__)


@dataclass
class TickerConfig:
    trade_quantity: int  # "常规仓" 对应的整股数；半仓 → 一半，1/3 → trade_quantity/3 …


@dataclass
class PageSettings:
    dedupe_processed_messages: bool = True
    price_deviation_tolerance: float = 1.0  # 单位：百分比（1.0 = 1%）
    block_historical_messages: bool = False  # 拦截下单历史消息（posted_at < listener.started_at），仅解析不下单
    launch_headless: bool = False  # 该页面监听是否以无头模式启动浏览器
    tickers: dict[str, TickerConfig] | None = field(default_factory=dict)
    # Option-page local risk controls (both optional and independently switchable).
    option_buy_quantity_enabled: bool = False
    option_buy_quantity: int | None = None
    option_total_price_limit_enabled: bool = False
    option_total_price_limit: float | None = None
    parser_version: Literal["v1", "v2"] = "v1"


DEFAULT_STOCK_SETTINGS = PageSettings(
    dedupe_processed_messages=True,
    price_deviation_tolerance=1.0,
    block_historical_messages=False,
    launch_headless=False,
    tickers={},
    parser_version="v1",
)

DEFAULT_OPTION_SETTINGS = PageSettings(
    dedupe_processed_messages=True,
    price_deviation_tolerance=5.0,
    block_historical_messages=False,
    launch_headless=False,
    tickers=None,
    option_buy_quantity_enabled=False,
    option_buy_quantity=None,
    option_total_price_limit_enabled=False,
    option_total_price_limit=None,
    parser_version="v1",
)


def default_settings_for(source: Literal["stock", "option"]) -> PageSettings:
    if source == "stock":
        return PageSettings(
            dedupe_processed_messages=DEFAULT_STOCK_SETTINGS.dedupe_processed_messages,
            price_deviation_tolerance=DEFAULT_STOCK_SETTINGS.price_deviation_tolerance,
            block_historical_messages=DEFAULT_STOCK_SETTINGS.block_historical_messages,
            launch_headless=DEFAULT_STOCK_SETTINGS.launch_headless,
            tickers={},
            parser_version=DEFAULT_STOCK_SETTINGS.parser_version,
        )
    if source == "option":
        return PageSettings(
            dedupe_processed_messages=DEFAULT_OPTION_SETTINGS.dedupe_processed_messages,
            price_deviation_tolerance=DEFAULT_OPTION_SETTINGS.price_deviation_tolerance,
            block_historical_messages=DEFAULT_OPTION_SETTINGS.block_historical_messages,
            launch_headless=DEFAULT_OPTION_SETTINGS.launch_headless,
            tickers=None,
            option_buy_quantity_enabled=DEFAULT_OPTION_SETTINGS.option_buy_quantity_enabled,
            option_buy_quantity=DEFAULT_OPTION_SETTINGS.option_buy_quantity,
            option_total_price_limit_enabled=DEFAULT_OPTION_SETTINGS.option_total_price_limit_enabled,
            option_total_price_limit=DEFAULT_OPTION_SETTINGS.option_total_price_limit,
            parser_version=DEFAULT_OPTION_SETTINGS.parser_version,
        )
    raise ValueError(f"unknown source: {source!r}")


def page_settings_to_dict(s: PageSettings) -> dict[str, Any]:
    out: dict[str, Any] = {
        "dedupe_processed_messages": s.dedupe_processed_messages,
        "price_deviation_tolerance": s.price_deviation_tolerance,
        "block_historical_messages": s.block_historical_messages,
        "launch_headless": s.launch_headless,
        "option_buy_quantity_enabled": s.option_buy_quantity_enabled,
        "option_buy_quantity": s.option_buy_quantity,
        "option_total_price_limit_enabled": s.option_total_price_limit_enabled,
        "option_total_price_limit": s.option_total_price_limit,
        "parser_version": s.parser_version,
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
    block_historical = bool(d.get("block_historical_messages", base.block_historical_messages))
    launch_headless = bool(d.get("launch_headless", base.launch_headless))
    option_qty_enabled = bool(
        d.get("option_buy_quantity_enabled", base.option_buy_quantity_enabled)
    )
    option_qty_raw = d.get("option_buy_quantity", base.option_buy_quantity)
    option_qty = int(option_qty_raw) if option_qty_raw is not None else None
    option_total_enabled = bool(
        d.get("option_total_price_limit_enabled", base.option_total_price_limit_enabled)
    )
    option_total_raw = d.get("option_total_price_limit", base.option_total_price_limit)
    option_total = float(option_total_raw) if option_total_raw is not None else None
    tickers: dict[str, TickerConfig] | None
    if source == "option":
        tickers = None
    else:
        raw_tickers = d.get("tickers", {}) or {}
        tickers = {
            str(k).upper(): TickerConfig(trade_quantity=int(v["trade_quantity"]))
            for k, v in raw_tickers.items()
        }
    pv_raw = d.get("parser_version", base.parser_version)
    parser_version: Literal["v1", "v2"] = "v2" if pv_raw == "v2" else "v1"
    return PageSettings(
        dedupe_processed_messages=dedupe,
        price_deviation_tolerance=tol,
        block_historical_messages=block_historical,
        launch_headless=launch_headless,
        tickers=tickers,
        option_buy_quantity_enabled=option_qty_enabled,
        option_buy_quantity=option_qty,
        option_total_price_limit_enabled=option_total_enabled,
        option_total_price_limit=option_total,
        parser_version=parser_version,
    )


# --------------------------------------------------------------------------- #
# Position size string → fraction multiplier                                    #
# (_FRACTION_MAP imported from app.parser.vocab_shared above)                   #
# --------------------------------------------------------------------------- #


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


# --------------------------------------------------------------------------- #
# Sell quantity string → fraction multiplier                                    #
# (_SELL_FRACTION_MAP imported from app.parser.vocab_shared above)              #
# --------------------------------------------------------------------------- #


def sell_quantity_to_fraction(s: str | None) -> float:
    """把 stock_parser 解出来的 sell_quantity 字符串 → 数量倍数。

    未识别 / None / 空 → 1.0（按引用 lot 全量计算）。
    未识别时记 warning。决策见 design 第 5 节：'剩下一半' 等同 1/2，不做
    lot 累计消耗追踪。
    """
    if not s:
        return 1.0
    s2 = s.strip()
    if s2 in _SELL_FRACTION_MAP:
        return _SELL_FRACTION_MAP[s2]
    logger.warning("unrecognized sell_quantity %r — falling back to 1.0", s2)
    return 1.0
