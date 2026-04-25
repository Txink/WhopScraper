"""
正股指令解析器 — 单条消息文本 → StockInstruction。

不做 ticker 上下文补全（Task 19）；不做关注列表校验（调用方职责）。
纯函数，无副作用。
"""
from __future__ import annotations

import hashlib
import re
from decimal import ROUND_HALF_UP, Decimal

from app.domain.instruction import InstructionType, StockInstruction
from app.parser.ticker_aliases import normalize_message as _normalize_aliases

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _normalize_price(s: str) -> float:
    """将含中文句号的价格字符串转为 float，如 '15。03' → 15.03。"""
    return float(str(s).replace("。", "."))


def _round2(x: float) -> float:
    """标准四舍五入保留2位小数（避免 Python round() 银行家舍入问题）。"""
    return float(Decimal(str(x)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _sort_range(p1: float, p2: float) -> tuple[float, float]:
    """确保价格区间低价在前。"""
    return (min(p1, p2), max(p1, p2))


def _resolve_position_size(message: str) -> str | None:
    """
    统一解析买入仓位描述：
    1. 优先匹配 POSITION_SIZE_PATTERN（小仓位/常规仓的一半等）
    2. 其次检测独立的"一半"（如"吸回一半"）
    """
    pos = _POSITION_SIZE_PATTERN.search(message)
    if pos:
        return pos.group(1)
    if "一半" in message:
        return "一半"
    return None


# ---------------------------------------------------------------------------
# Compiled patterns — verbatim from old parser/stock_parser.py
# ---------------------------------------------------------------------------

BUY_PATTERN_1 = re.compile(
    r'([A-Z]{2,5})\s+(?:买入|买了?|建仓了?)\s*\$?(\d+(?:\.\d+)?)',
    re.IGNORECASE,
)
BUY_PATTERN_2 = re.compile(
    r'(?:买入|买|建仓)\s+([A-Z]{2,5})\s+(?:在|价格)?\s*\$?(\d+(?:\.\d+)?)',
    re.IGNORECASE,
)
BUY_PATTERN_3 = re.compile(
    r'([A-Z]{2,5})\s+\$?(\d+(?:\.\d+)?)\s*(?:买入|买了?|建仓了?)',
    re.IGNORECASE,
)

SELL_PATTERN_1 = re.compile(
    r'([A-Z]{2,5})\s+(?:卖出|卖|出)\s+\$?(\d+(?:\.\d+)?)',
    re.IGNORECASE,
)
SELL_PATTERN_2 = re.compile(
    r'(?:卖出|卖|出|平仓)\s+([A-Z]{2,5})\s+(?:在|价格)?\s*\$?(\d+(?:\.\d+)?)',
    re.IGNORECASE,
)
SELL_PATTERN_3 = re.compile(
    r'([A-Z]{2,5})\s+\$?(\d+(?:\.\d+)?)\s+(?:卖出|卖|出)',
    re.IGNORECASE,
)

STOCK_STOP_LOSS_PATTERN = re.compile(
    r'(?:([A-Z]{2,5})\s+)?(?:止损|SL|stop\s*loss)\s+(?:([A-Z]{2,5})\s+)?(?:在)?\s*\$?(\d+(?:\.\d+)?)',
    re.IGNORECASE,
)
STOCK_TAKE_PROFIT_PATTERN = re.compile(
    r'(?:([A-Z]{2,5})\s+)?(?:止盈|TP|take\s*profit)\s+(?:([A-Z]{2,5})\s+)?(?:在)?\s*\$?(\d+(?:\.\d+)?)'
    r'(?:\s+出\s*(一半|三分之一|三分之二|全部|1/2|1/3|2/3))?',
    re.IGNORECASE,
)

_POSITION_SIZE_PATTERN = re.compile(
    r'(小仓位|中仓位|大仓位|轻仓|重仓|半仓|满仓|常规仓的一半|常规一半|常规的一半)',
    re.IGNORECASE,
)

# 口语化买入
BUY_PATTERN_4 = re.compile(
    r'([A-Za-z]{2,5})[\s\S]{0,20}?(?:在[到了]?\s*|可以\s*)?(\d+(?:\.\d+)?)\s*附近\s*[\s\S]{0,10}?(?:开个?底仓|开底仓|建个?(?:小仓位)?底仓|建仓一?笔?|先?建仓|建点|加仓|加(?!密)|介入|(?:做点)?配置|在?接(?!下))',
    re.IGNORECASE,
)
BUY_PATTERN_5 = re.compile(
    r'(\d+(?:\.\d+)?)[^A-Za-z]{0,10}?(?:加了|加(?!仓))\s*(?:了)?[^A-Za-z]*([A-Za-z]{2,5})\b',
    re.IGNORECASE,
)
BUY_PATTERN_6 = re.compile(
    r'(\d+(?:\.\d+)?)\s*附近?(?:加回|加)\s*(?:了)?[^A-Za-z]*([A-Za-z]{2,5})\b',
    re.IGNORECASE,
)
BUY_PATTERN_7 = re.compile(
    r'(\d+(?:\.\d+)?)\s*附近?\s*加(?:了)?(?:\s*个)?\s*([A-Za-z]{2,5})\b',
    re.IGNORECASE,
)
BUY_PATTERN_8 = re.compile(
    r'([A-Za-z]{2,5})\s*(\d+(?:\.\d+)?)\s*(?:在)?吸回',
    re.IGNORECASE,
)

SELL_PATTERN_4 = re.compile(
    r'([A-Za-z]{2,5})\s+.*?(\d+(?:\.\d+)?)\s*附近可以出',
    re.IGNORECASE,
)
SELL_PATTERN_5 = re.compile(
    r'([A-Za-z]{2,5})?.*?(\d+(?:\.\d+)?)\s*可以出\s*(\d+(?:\.\d+)?)\s*(?:的)?(一半)?',
    re.IGNORECASE,
)
SELL_PATTERN_6 = re.compile(
    r'(\d+(?:\.\d+)?)\s*出\s*之前\s*(\d+(?:\.\d+)?)\s*剩下(一半)?[^A-Za-z]*([A-Za-z]{2,5})\b',
    re.IGNORECASE,
)
SELL_PATTERN_7 = re.compile(
    r'([A-Za-z]{2,5})\s+.*?可以\s*(\d+(?:\.\d+)?)\s*出\s*(\d+(?:\.\d+)?)\s*的',
    re.IGNORECASE,
)
SELL_PATTERN_8 = re.compile(
    r'([A-Za-z]{2,5})\s+.*?(\d+(?:\.\d+)?)\s*可以\s*在?出\s*(\d+(?:\.\d+)?)\s*那部分',
    re.IGNORECASE,
)
SELL_TICKER_OUT_PRICE_PART = re.compile(
    r'([A-Za-z]{2,5})[\s\S]{0,60}?出[\s\S]{0,20}?(\d+(?:\.\d+)?)\s*(?:那部分|那笔|部分)',
    re.IGNORECASE,
)
SELL_TICKER_CAN_PRICE_OUT = re.compile(
    r'([A-Za-z]{2,5})[\s\S]{0,30}?可以\s*(\d+(?:\.\d+)?)\s*(?:附近)?\s*出(?!现|来)',
    re.IGNORECASE,
)
SELL_REF_YESTERDAY = re.compile(r'昨天\s*(\d+(?:\.\d+)?)\s*的')

# 新增卖出模式
SELL_RANGE_HALF = re.compile(
    r'([A-Za-z]{2,5})[\s\S]{0,60}?(\d+(?:\.\d+)?)\s*[-~]\s*(\d+(?:\.\d+)?)\s*(?:附近)?\s*[\s\S]{0,15}?(?:出掉?|减掉?)\s*(?:剩下的?|另外的?)?一半',
    re.IGNORECASE,
)
SELL_SINGLE_HALF = re.compile(
    r'([A-Za-z]{2,5})[\s\S]{0,60}?(\d+(?:\.\d+)?)\s*(?:附近)?\s*[\s\S]{0,15}?(?:出掉?|减掉?)\s*(?:剩下的?|另外的?)?一半',
    re.IGNORECASE,
)
SELL_HALF_AT_PRICE = re.compile(
    r'([A-Za-z]{2,5})[\s\S]{0,40}?一半[\s\S]{0,20}?在?\s*(\d+(?:\.\d+)?)\s*(?:附近)?出(?!现|来)',
    re.IGNORECASE,
)
SELL_ALSO_OUT_SOME = re.compile(
    r'([A-Za-z]{2,5})[\s\S]{0,60}?(\d+(?:\.\d+)?)\s*(?:附近)?\s*[\s\S]{0,15}?(?:也|可以)?出(?:掉|了)?(?:些?点)',
    re.IGNORECASE,
)
SELL_HALF_WITH_REF = re.compile(
    r'([A-Za-z]{2,5})[\s\S]{0,15}?(\d+(?:\.\d+)?)\s*出\s*(?:剩下的?)?一半\s*(\d+(?:\.\d+)?)\s*(?:吸的|买的|加的)?',
    re.IGNORECASE,
)
SELL_TIME_REDUCE = re.compile(
    r'([A-Za-z]{2,5})[\s\S]{0,20}?(\d+(?:\.\d+)?)\s*时候\s*减掉?\s*(\d+(?:\.\d+)?)\s*(?:加仓的|买的|加的)?',
    re.IGNORECASE,
)
SELL_RANGE_PARTIAL = re.compile(
    r'([A-Za-z]{2,5})[\s\S]{0,60}?(\d+(?:\.\d+)?)\s*[-~]\s*(\d+(?:\.\d+)?)\s*(?:附近)?\s*(?:分批出|减点|减掉点)',
    re.IGNORECASE,
)
SELL_RANGE_FULL = re.compile(
    r'([A-Za-z]{2,5})[\s\S]{0,60}?(\d+(?:\.\d+)?)\s*[-~]\s*(\d+(?:\.\d+)?)\s*(?:附近)?\s*[\s\S]{0,20}?(?:出掉?|减掉?)',
    re.IGNORECASE,
)
SELL_RANGE_BETWEEN = re.compile(
    r'([A-Za-z]{2,5})[\s\S]{0,60}?(\d+(?:\.\d+)?)\s*[-~]\s*(\d+(?:\.\d+)?)\s*(?:之间|到)\s*(?:出|都出)?',
    re.IGNORECASE,
)
SELL_PARTIAL = re.compile(
    r'([A-Za-z]{2,5})[\s\S]{0,60}?(\d+(?:\.\d+)?)\s*(?:附近)?\s*[\s\S]{0,20}?(?:减掉?点|分批出)',
    re.IGNORECASE,
)
SELL_REDUCE = re.compile(
    r'([A-Za-z]{2,5})[\s\S]{0,60}?(\d+(?:\.\d+)?)\s*(?:附近)?\s*[\s\S]{0,10}?减(?!点|掉点)',
    re.IGNORECASE,
)
SELL_PRICE_SELL_OUT = re.compile(
    r'([A-Za-z]{2,5})[\s\S]{0,60}?(\d+(?:\.\d+)?)\s*(?:附近)?\s*卖出',
    re.IGNORECASE,
)
SELL_SHORT_TERM = re.compile(
    r'([A-Za-z]{2,5})[\s\S]{0,30}?(\d+(?:\.\d+)?)\s*(?:附近)?\s*出短线',
    re.IGNORECASE,
)
SELL_APPROX_OUT_REF_HALF = re.compile(
    r'([A-Za-z]{2,5})[\s\S]{0,30}?(\d+(?:\.\d+)?)\s*(?:附近)?\s*出\s*(\d+(?:\.\d+)?)\s*(?:买的|吸的|加的)?的?\s*一半',
    re.IGNORECASE,
)
SELL_APPROX_OUT_REF = re.compile(
    r'([A-Za-z]{2,5})[\s\S]{0,30}?(\d+(?:\.\d+)?)\s*(?:附近)?[^出]{0,15}?出\s*(?:了)?\s*(\d+(?:\.\d+)?)\s*(?:买的|吸的|加的)?',
    re.IGNORECASE,
)
SELL_PUT_OUT_REF = re.compile(
    r'([A-Za-z]{2,5})[\s\S]{0,30}?(\d+(?:\.\d+)?)\s*(?:附近)?\s*[\s\S]{0,15}?把\s*(?:节前)?(?:\S+)?\s*(\d+(?:\.\d+)?)\s*(?:买的|吸的)\s*出(?:了)?',
    re.IGNORECASE,
)
SELL_APPROX_SIMPLE = re.compile(
    r'([A-Za-z]{2,5})[\s\S]{0,60}?(\d+(?:\.\d+)?)\s*(?:成本)?附近\s*(?:都|也|先)?(?:卖)?出(?:\s|$|了|掉)',
    re.IGNORECASE,
)
SELL_OUT_BEFORE_REF = re.compile(
    r'([A-Za-z]{2,5})[\s\S]{0,15}?(\d+(?:\.\d+)?)\s*出\s*(?:之前)?\s*(\d+(?:\.\d+)?)\s*(?:吸的|买的|加的)',
    re.IGNORECASE,
)
SELL_THAT_PART = re.compile(
    r'([A-Za-z]{2,5})[\s\S]{0,10}?(\d+(?:\.\d+)?)\s*那部分[\s\S]{0,30}?出',
    re.IGNORECASE,
)
SELL_YESTERDAY_BUY_PART = re.compile(
    r'([A-Za-z]{2,5})[\s\S]{0,50}?出\s*(?:昨天|之前|上次)?\s*(\d+(?:\.\d+)?)\s*(?:买的|吸的|加的)\s*那部分',
    re.IGNORECASE,
)

# 新增买入模式
BUY_RANGE_ABSORB = re.compile(
    r'([A-Za-z]{2,5})[\s\S]{0,60}?(\d+(?:\.\d+)?)\s*[-~]\s*(\d+(?:\.\d+)?)\s*(?:附近)?\s*[\s\S]{0,15}?(?:支撑)?(?:分批)?(?:回吸|吸回|低吸|吸(?!筹))',
    re.IGNORECASE,
)
BUY_TICKER_ACTION_RANGE = re.compile(
    r'([A-Za-z]{2,5})[\s\S]{0,50}?(?:吸|回吸|吸回|低吸|加|接)\s*(\d+(?:\.\d+)?)\s*[-~]\s*(\d+(?:\.\d+)?)',
    re.IGNORECASE,
)
BUY_RANGE_RETRACE = re.compile(
    r'([A-Za-z]{2,5})[\s\S]{0,40}?(\d+(?:\.\d+)?)\s*[-~]\s*(\d+(?:\.\d+)?)\s*(?:在)?(?:回吸|吸回)',
    re.IGNORECASE,
)
BUY_RANGE_BUILD = re.compile(
    r'([A-Za-z]{2,5})[\s\S]{0,60}?(?:在\s*)?(\d+(?:\.\d+)?)\s*[-~]\s*(\d+(?:\.\d+)?)\s*(?:附近)?\s*[\s\S]{0,15}?(?:建个?小仓位|建底仓|建仓|开个?(?:小仓位|常规仓)?仓?|加仓|加点仓?|加一笔|加一半|分批(?:进|加)|进|买一半|买)',
    re.IGNORECASE,
)
BUY_RETRACE = re.compile(
    r'([A-Za-z]{2,5})[\s\S]{0,30}?回踩\s*(\d+(?:\.\d+)?)\s*(?:回吸|建点|时候建点|低吸)',
    re.IGNORECASE,
)
BUY_ABSORB_SINGLE = re.compile(
    r'([A-Za-z]{2,5})[\s\S]{0,50}?(\d+(?:\.\d+)?)\s*(?:附近)?\s*(?:可以\s*|在\s*)?(?:回吸|吸回|低吸|吸(?!筹))(?:一笔|一半|点)?',
    re.IGNORECASE,
)
BUY_PRICE_ABSORB = re.compile(
    r'([A-Za-z]{2,5})[\s\S]{0,30}?(\d+(?:\.\d+)?)\s*(?:也是|在)?\s*(?:回吸|吸回|吸(?!筹|回))(?!\s*之前)',
    re.IGNORECASE,
)
BUY_ENTERED = re.compile(
    r'([A-Za-z]{2,5})[\s\S]{0,20}?(\d+(?:\.\d+)?)\s*(?:附近)?\s*[\s\S]{0,20}?(?:入了?仓位?|入仓|入了|先?入一笔|先入)',
    re.IGNORECASE,
)
BUY_HANG_ORDER = re.compile(
    r'([A-Za-z]{2,5})[\s\S]{0,40}?挂[^在]{0,15}在\s*(\d+(?:\.\d+)?)\s*(?:这里|附近)?',
    re.IGNORECASE,
)
BUY_HANG_ABSORB = re.compile(
    r'([A-Za-z]{2,5})[\s\S]{0,50}?挂单[^\d]{0,20}?(\d+(?:\.\d+)?)\s*(?:的)?\s*(?:低吸|回吸|吸)',
    re.IGNORECASE,
)
BUY_CATCH_PRICE = re.compile(
    r'([A-Za-z]{2,5})[\s\S]{0,50}?(\d+[.。]\d+)\s*(?:附近)?\s*接(?!\s*下)',
    re.IGNORECASE,
)
BUY_PRICE_THEN_TICKER = re.compile(
    r'(\d+(?:\.\d+)?)\s*(?:附近)?\s*吸回\s*([A-Za-z]{2,5})',
    re.IGNORECASE,
)
BUY_RANGE_SUPPORT = re.compile(
    r'([A-Za-z]{2,5})[\s\S]{0,10}?(\d+(?:\.\d+)?)\s*[-~]\s*(\d+(?:\.\d+)?)\s*[\s\S]{0,40}?支撑',
    re.IGNORECASE,
)
BUY_SMALL_ADD = re.compile(
    r'([A-Za-z]{2,5})[\s\S]{0,60}?(\d+(?:\.\d+)?)\s*附近\s*小加',
    re.IGNORECASE,
)
BUY_PRICE_REF_ABSORB = re.compile(
    r'([A-Za-z]{2,5})[\s\S]{0,60}?价格\s*(\d+(?:\.\d+)?)\s*[\s\S]{0,50}?(?:这个价格|这里|该价格|这个价位)?\s*附近\s*(?:吸|回吸|低吸)',
    re.IGNORECASE,
)
BUY_OPENED_ONE = re.compile(
    r'([A-Za-z]{2,5})[\s\S]{0,10}?(\d+(?:\.\d+)?)\s*(?:开了一笔|建了一笔|开了一个|建了一个|入了一笔)',
    re.IGNORECASE,
)
BUY_ABSORB_THEN_RANGE = re.compile(
    r'([A-Za-z]{2,5})[\s\S]{0,80}?(?:回吸|低吸|吸回)\s*[\s\S]{0,50}?(\d+(?:\.\d+)?)\s*[-~]\s*(\d+(?:\.\d+)?)\s*(?:附近)?',
    re.IGNORECASE,
)
BUY_LIST_PRICE = re.compile(
    r'([A-Za-z]{2,5})\s+(\d+(?:\.\d+)?)\s+(?=[A-Za-z]{2,5}\s)',
    re.IGNORECASE,
)

# ticker 在句尾/句中的买入模式
BUY_OPEN_SUFFIX = re.compile(
    r'(\d+(?:[.。]\d+)?)\s*附近\s*(?:在\s*)?(?:小仓位|常规仓)?\s*(?:开仓|建仓)\s*([A-Za-z]{2,5})(?![a-zA-Z0-9])',
    re.IGNORECASE,
)
BUY_RANGE_BUILD_SUFFIX = re.compile(
    r'(\d+(?:[.。]\d+)?)\s*[-~到]\s*(\d+(?:[.。]\d+)?)\s*[\s\S]{0,20}?(?:建了?|买了?|加了?|开了?)\s*(?:点|些|个)?[\s\S]{0,15}?([A-Za-z]{2,5})(?![a-zA-Z0-9])',
    re.IGNORECASE,
)
BUY_TICKER_ABSORB_HANG = re.compile(
    r'([A-Za-z]{2,5})\s*回吸[\s\S]{0,30}?可以\s*(\d+(?:[.。]\d+)?)\s*挂',
    re.IGNORECASE,
)
BUY_ABSORB_BACK_SUFFIX = re.compile(
    r'(\d+(?:[.。]\d+)?)\s*(?:附近)?\s*在?\s*吸回\s*(?:卖出的|之前卖出的|之前的|卖的)?\s*([A-Za-z]{2,5})(?![a-zA-Z0-9])',
    re.IGNORECASE,
)
BUY_PRICE_ACTION_SUFFIX = re.compile(
    r'(\d+(?:[.。]\d+)?)\s*(?:附近)?\s*[\s\S]{0,15}?(?:吸了|接回|回吸了?|加了)\s*[\s\S]{0,10}?([A-Za-z]{2,5})(?![a-zA-Z0-9])',
    re.IGNORECASE,
)
BUY_PRICE_ADD_POSITION_SUFFIX = re.compile(
    r'(\d+(?:[.。]\d+)?)\s*加仓了?\s*([A-Za-z]{2,5})(?![a-zA-Z0-9])',
    re.IGNORECASE,
)
BUY_POSITION_TICKER_ACTION = re.compile(
    r'(\d+(?:[.。]\d+)?)\s*(?:常规仓的?一半|常规一半|常规的一半|小仓位|常规仓)\s*的?\s*([A-Za-z]{2,5})\s*(?:接回|接|吸回)',
    re.IGNORECASE,
)
BUY_ACTION_TICKER_AT_PRICE = re.compile(
    r'(?:回吸了?|吸回了?|加了)\s*[\s\S]{0,20}?([A-Za-z]{2,5})\s*(?:在|@)\s*(\d+(?:[.。]\d+)?)',
    re.IGNORECASE,
)
BUY_APPROX_ACTION_TICKER_SUFFIX = re.compile(
    r'(\d+(?:[.。]\d+)?)\s*(?:附近)?\s*[\s\S]{0,15}?(?:回吸|吸回|吸(?!筹)|接|进(?!场|行)|加(?!仓|密))\s*[\s\S]{0,10}?([A-Za-z]{2,5})(?![a-zA-Z0-9])',
    re.IGNORECASE,
)
BUY_OPEN_POSITION_TICKER_SUFFIX = re.compile(
    r'(\d+(?:[.。]\d+)?)\s*附近\s*开仓了?\s*[\s\S]{0,20}?([A-Za-z]{2,5})(?![a-zA-Z0-9])',
    re.IGNORECASE,
)
BUY_VERBOSE_ACTION_SUFFIX = re.compile(
    r'(\d+(?:[.。]\d+)?)(?![分秒])\s*(?:附近)?\s*[\s\S]{0,15}?'
    r'(?:加仓|建仓了?|配置点?|买回|接回|回买)'
    r'\s*[\s\S]{0,25}?(?<![a-zA-Z0-9])([A-Za-z]{3,5})(?![a-zA-Z0-9])',
    re.IGNORECASE,
)

# ticker 在句尾/句中的卖出模式
SELL_RANGE_REDUCE_SUFFIX = re.compile(
    r'(\d+(?:[.。]\d+)?)\s*[-~到]\s*(\d+(?:[.。]\d+)?)\s*(?:附近|之间|这段)?\s*[\s\S]{0,15}?(?:减仓|减持|减点|减掉|减|出)\s*[\s\S]{0,15}?([A-Za-z]{2,5})(?![a-zA-Z0-9])',
    re.IGNORECASE,
)
SELL_BATCH_REF_SUFFIX = re.compile(
    r'(\d+(?:[.。]\d+)?)\s*[-~到]\s*(\d+(?:[.。]\d+)?)\s*(?:这段|附近)?\s*分批出\s*(?:昨天|之前)?\s*(\d+(?:[.。]\d+)?)\s*的?\s*([A-Za-z]{2,5})(?![a-zA-Z0-9])',
    re.IGNORECASE,
)
SELL_PRICE_OUT_SUFFIX = re.compile(
    r'(\d+(?:[.。]\d+)?)\s*(?:[-~到]\s*(\d+(?:[.。]\d+)?))?\s*(?:附近)?\s*(?:可以\s*)?出\s*([A-Za-z]{2,5})(?![a-zA-Z0-9])',
    re.IGNORECASE,
)
SELL_RANGE_OUT_REF_SUFFIX = re.compile(
    r'(\d+(?:[.。]\d+)?)\s*[-~]\s*(\d+(?:[.。]\d+)?)\s*附近?\s*出\s*(\d+(?:[.。]\d+)?)\s*(?:的|吸的|买的|加的)\s*([A-Za-z]{2,5})(?![a-zA-Z0-9])',
    re.IGNORECASE,
)
SELL_HALF_REF_SUFFIX = re.compile(
    r'(\d+(?:[.。]\d+)?)\s*(?:附近)?\s*出\s*(?:剩下的?)?一半\s*(\d+(?:[.。]\d+)?)\s*(?:吸的|买的|加的|的)\s*([A-Za-z]{2,5})(?![a-zA-Z0-9])',
    re.IGNORECASE,
)
SELL_PRICE_OUT_REF_SUFFIX = re.compile(
    r'(\d+(?:[.。]\d+)?)\s*(?:附近)?\s*(?:可以)?(?:再次?)?出(?:了|掉)?\s*[\s\S]{0,25}?(\d+(?:[.。]\d+)?)\s*(?:附近)?(?:的那部分|那部分|的|低吸的|低买的|吸的|买的|加的)\s*([A-Za-z]{2,5})(?![a-zA-Z0-9])',
    re.IGNORECASE,
)
SELL_OUT_HALF_NO_REF_SUFFIX = re.compile(
    r'(\d+(?:[.。]\d+)?)\s*(?:附近)?\s*(?:再)?出\s*(?:掉)?(?:剩下的?)?一半\s*[\s\S]{0,10}?([A-Za-z]{2,5})(?![a-zA-Z0-9])',
    re.IGNORECASE,
)
SELL_APPROX_OUT_TICKER_SUFFIX = re.compile(
    r'(\d+(?:[.。]\d+)?)\s*(?:附近|近)\s*(?:可以)?(?:再)?出(?:了|掉)?[\s\S]{0,20}?([A-Za-z]{2,5})(?![a-zA-Z0-9])',
    re.IGNORECASE,
)
SELL_PRICE_OUT_GAP_TICKER_SUFFIX = re.compile(
    r'(\d+(?:[.。]\d+)?)\s*(?:附近)?\s*出[\s\S]{0,20}?([A-Za-z]{2,5})(?![a-zA-Z0-9])',
    re.IGNORECASE,
)
SELL_SINGLE_REDUCE_SUFFIX = re.compile(
    r'(\d+(?:[.。]\d+)?)\s*(?:附近)?\s*[\s\S]{0,20}?(?:减仓|减持|减点|减)\s*[\s\S]{0,20}?([A-Za-z]{2,5})(?![a-zA-Z0-9])',
    re.IGNORECASE,
)
SELL_REDUCE_HALF_REF_SUFFIX = re.compile(
    r'(\d+(?:[.。]\d+)?)\s*(?:附近)?\s*减一半\s*(\d+(?:[.。]\d+)?)\s*(?:附近的|挂单进的|的|吸的|买的|加的)?\s*([A-Za-z]{2,5})(?![a-zA-Z0-9])',
    re.IGNORECASE,
)

# 关注列表 fallback 正则（ticker 已知后用）
SELL_HINT_RANGE_CAN_OUT = re.compile(
    r'(\d+(?:[.。]\d+)?)\s*[-~]\s*(\d+(?:[.。]\d+)?)\s*附近可以出',
    re.IGNORECASE,
)
SELL_HINT_RANGE_OUT = re.compile(
    r'(\d+(?:[.。]\d+)?)\s*[-~]\s*(\d+(?:[.。]\d+)?)\s*附近?\s*[\s\S]{0,30}?(?:出|减)',
    re.IGNORECASE,
)
SELL_HINT_SINGLE_OUT = re.compile(
    r'(\d+(?:[.。]\d+)?)\s*(?:成本)?(?:附近)?[\s\S]{0,15}?(?:可以\s*)?(?:都|也|先)?(?:卖出|出)(?!现|来|了?短线)',
    re.IGNORECASE,
)
SELL_HINT_SINGLE_HALF = re.compile(
    r'(\d+(?:[.。]\d+)?)\s*出\s*(?:剩下的?)?一半',
    re.IGNORECASE,
)
SELL_HINT_REDUCE = re.compile(
    r'(\d+(?:[.。]\d+)?)\s*(?:附近)?\s*[\s\S]{0,20}?(?:减仓|减持|减点|减)',
    re.IGNORECASE,
)
BUY_HINT_RANGE = re.compile(
    r'(\d+(?:[.。]\d+)?)\s*[-~]\s*(\d+(?:[.。]\d+)?)\s*附近?\s*[\s\S]{0,30}?(?:回吸|吸回|吸|加|建仓|开仓|介入|配置|分批进|分批加|进|接)',
    re.IGNORECASE,
)
BUY_HINT_SINGLE = re.compile(
    r'(\d+(?:[.。]\d+)?)(?![分秒])\s*(?:附近)?\s*[\s\S]{0,20}?(?:加(?!仓|密)|吸回|回吸|吸(?!筹)|开仓|建仓|(?<!人工)介入|(?:做点)?配置|开(?!盘|始|涨|跌|低|高)|进(?!场|行)|接(?!下)|回买)',
    re.IGNORECASE,
)
TP_HINT = re.compile(
    r'(\d+(?:[.。]\d+)?)(?![分秒])\s*(?:[-~到]\s*(\d+(?:[.。]\d+)?))?\s*(?:附近)?\s*'
    r'[\s\S]{0,20}?(?:全部|都|先)?\s*止盈(?:一半|一点|一部分|了)?',
    re.IGNORECASE,
)
TP_HINT_POST = re.compile(
    r'止盈(?:一半|一点|一部分|了)?\s*(?:在)?\s*\$?'
    r'(\d+(?:[.。]\d+)?)(?![分秒])(?:\s*[-~到]\s*(\d+(?:[.。]\d+)?))?',
    re.IGNORECASE,
)
SL_HINT = re.compile(
    r'(\d+(?:[.。]\d+)?)(?![分秒])\s*(?:[-~到]\s*(\d+(?:[.。]\d+)?))?\s*(?:附近)?\s*'
    r'[\s\S]{0,20}?(?:全部|都|先)?\s*止损(?:一半|一点|了)?',
    re.IGNORECASE,
)
SL_HINT_POST = re.compile(
    r'止损(?:一半|一点|了)?\s*(?:在)?\s*\$?(\d+(?:[.。]\d+)?)(?![分秒])',
    re.IGNORECASE,
)

# 持仓回顾/观察性语句排除
_NON_ACTION_WATCH = re.compile(
    r'(?:回吸|入了?一笔)[\s\S]{0,30}剩下的?(?:放|到)[\s\S]{0,20}再看',
    re.IGNORECASE,
)

# 买入数量参考
_BUY_REF_FRIDAY = re.compile(r'周五卖出的', re.IGNORECASE)
_BUY_REF_TODAY = re.compile(r'今天卖出的', re.IGNORECASE)
_BUY_REF_PART = re.compile(r'卖出的一部分', re.IGNORECASE)

_PORTION_MAP = {
    "三分之一": "1/3",
    "三分之二": "2/3",
    "一半": "1/2",
    "剩下一半": "1/2",
    "另外一半": "1/2",
    "剩下的一半": "1/2",
    "全部": "全部",
    "1/3": "1/3",
    "2/3": "2/3",
    "1/2": "1/2",
}

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def parse(content: str, *, message_id: str) -> StockInstruction | None:
    """Parse a single stock-channel message into StockInstruction.

    Returns None if the message doesn't look like a trading instruction at all
    (empty, chatter, no recognizable pattern). Callers should invoke context
    resolution for None results before giving up.

    Does NOT validate tickers against a watchlist — that's the caller's concern.
    Does NOT resolve quoted/history context — see context_resolver (Task 19).
    """
    msg = content.strip().replace("。", ".")
    msg = (
        msg.replace("–", "-")
        .replace("—", "-")
        .replace("‒", "-")
        .replace("―", "-")
    )
    if not msg:
        return None

    if not message_id:
        message_id = hashlib.md5(msg.encode()).hexdigest()[:12]

    instruction = _parse_buy(msg, message_id)
    if instruction:
        return instruction
    instruction = _parse_sell(msg, message_id)
    if instruction:
        return instruction
    instruction = _parse_stop_loss(msg, message_id)
    if instruction:
        return instruction
    instruction = _parse_take_profit(msg, message_id)
    if instruction:
        return instruction

    # 中文昵称 fallback：把"博通/奈飞双倍"等替换为 ticker 再重试
    normalized = _normalize_aliases(msg)
    if normalized != msg:
        for fn in (_parse_buy, _parse_sell, _parse_stop_loss, _parse_take_profit):
            instruction = fn(normalized, message_id)
            if instruction:
                return instruction

    return None


# ---------------------------------------------------------------------------
# Private parse methods
# ---------------------------------------------------------------------------

def _make_stock(
    *,
    ticker: str,
    instruction_type: InstructionType,
    message_id: str,
    raw_message: str,
    price: float | None = None,
    price_range: tuple[float, float] | None = None,
    quantity: int | None = None,
    position_size: str | None = None,
    stop_loss_price: float | None = None,
    take_profit_price: float | None = None,
    sell_quantity: str | None = None,
    parser_notes: list[str] | None = None,
) -> StockInstruction | None:
    """
    Construct a StockInstruction, absorbing validation errors gracefully.

    The new domain model requires:
      - ticker must be non-empty
      - price OR price_range must be set

    For MODIFY instructions (stop-loss / take-profit) that have no price,
    we fall back to using the stop_loss_price / take_profit_price as the price
    so the invariant is satisfied.
    """
    ticker = ticker.strip().upper()
    if not ticker:
        return None

    # Satisfy the price invariant for MODIFY instructions
    if price is None and price_range is None:
        if stop_loss_price is not None:
            price = stop_loss_price
        elif take_profit_price is not None:
            price = take_profit_price
        else:
            return None

    notes: list[str] = parser_notes or []

    try:
        return StockInstruction(
            instruction_type=instruction_type,
            price=price,
            price_range=price_range,
            quantity=quantity,
            position_size=position_size,
            stop_loss_price=stop_loss_price,
            take_profit_price=take_profit_price,
            context_source=None,
            parser_notes=notes,
            ticker=ticker,
            sell_quantity=sell_quantity,
        )
    except ValueError:
        return None


def _parse_buy(message: str, message_id: str) -> StockInstruction | None:  # noqa: C901 (long but direct port)
    # 排除持仓回顾性语句（非新操作）
    if _NON_ACTION_WATCH.search(message):
        return None

    # 标准格式
    for pattern in (BUY_PATTERN_1, BUY_PATTERN_2, BUY_PATTERN_3):
        match = pattern.search(message)
        if not match:
            continue
        ticker = match.group(1).upper()
        price = float(match.group(2))
        position_match = _POSITION_SIZE_PATTERN.search(message)
        position_size = position_match.group(1) if position_match else None
        return _make_stock(
            ticker=ticker,
            instruction_type=InstructionType.BUY,
            message_id=message_id,
            raw_message=message,
            price=price,
            position_size=position_size,
        )

    # 口语化：tsll 在16.02附近开个底仓 常规仓的一半
    match = BUY_PATTERN_4.search(message)
    if match:
        ticker = match.group(1).upper()
        price = float(match.group(2))
        pos = _POSITION_SIZE_PATTERN.search(message)
        position_size = pos.group(1) if pos else None
        return _make_stock(
            ticker=ticker,
            instruction_type=InstructionType.BUY,
            message_id=message_id,
            raw_message=message,
            price=price,
            position_size=position_size,
        )

    # 15.43加了常规一半的tsll / 15.35加个tsll 常规的一半
    for pattern in (BUY_PATTERN_5, BUY_PATTERN_7):
        match = pattern.search(message)
        if not match:
            continue
        price = float(match.group(1))
        ticker = match.group(2).upper()
        pos = _POSITION_SIZE_PATTERN.search(message)
        position_size = pos.group(1) if pos else None
        return _make_stock(
            ticker=ticker,
            instruction_type=InstructionType.BUY,
            message_id=message_id,
            raw_message=message,
            price=price,
            position_size=position_size,
        )

    # 15.17附近加回了周五卖出的那部分tsll
    match = BUY_PATTERN_6.search(message)
    if match:
        price = float(match.group(1))
        ticker = match.group(2).upper()
        return _make_stock(
            ticker=ticker,
            instruction_type=InstructionType.BUY,
            message_id=message_id,
            raw_message=message,
            price=price,
        )

    # tsll15.48在吸回卖出的一部分
    match = BUY_PATTERN_8.search(message)
    if match:
        ticker = match.group(1).upper()
        price = float(match.group(2))
        return _make_stock(
            ticker=ticker,
            instruction_type=InstructionType.BUY,
            message_id=message_id,
            raw_message=message,
            price=price,
        )

    # 价格区间 + 回吸/低吸
    match = BUY_RANGE_ABSORB.search(message)
    if match:
        ticker = match.group(1).upper()
        lo, hi = _sort_range(float(match.group(2)), float(match.group(3)))
        position_size = _resolve_position_size(message)
        return _make_stock(
            ticker=ticker,
            instruction_type=InstructionType.BUY,
            message_id=message_id,
            raw_message=message,
            price=_round2((lo + hi) / 2),
            price_range=(lo, hi),
            position_size=position_size,
        )

    # "nvdl今天还是转弯时候吸 83-83.5" (action before range)
    match = BUY_TICKER_ACTION_RANGE.search(message)
    if match:
        ticker = match.group(1).upper()
        lo, hi = _sort_range(float(match.group(2)), float(match.group(3)))
        position_size = _resolve_position_size(message)
        return _make_stock(
            ticker=ticker,
            instruction_type=InstructionType.BUY,
            message_id=message_id,
            raw_message=message,
            price=_round2((lo + hi) / 2),
            price_range=(lo, hi),
            position_size=position_size,
        )

    # 价格区间 + 在回吸
    match = BUY_RANGE_RETRACE.search(message)
    if match:
        ticker = match.group(1).upper()
        lo, hi = _sort_range(float(match.group(2)), float(match.group(3)))
        return _make_stock(
            ticker=ticker,
            instruction_type=InstructionType.BUY,
            message_id=message_id,
            raw_message=message,
            price=_round2((lo + hi) / 2),
            price_range=(lo, hi),
        )

    # 价格区间 + 建仓/买一半
    match = BUY_RANGE_BUILD.search(message)
    if match:
        ticker = match.group(1).upper()
        lo, hi = _sort_range(float(match.group(2)), float(match.group(3)))
        pos = _POSITION_SIZE_PATTERN.search(message)
        position_size = "一半" if "一半" in message and not pos else pos.group(1) if pos else None
        return _make_stock(
            ticker=ticker,
            instruction_type=InstructionType.BUY,
            message_id=message_id,
            raw_message=message,
            price=_round2((lo + hi) / 2),
            price_range=(lo, hi),
            position_size=position_size,
        )

    # 回踩+单价+回吸
    match = BUY_RETRACE.search(message)
    if match:
        ticker = match.group(1).upper()
        price = float(match.group(2))
        return _make_stock(
            ticker=ticker,
            instruction_type=InstructionType.BUY,
            message_id=message_id,
            raw_message=message,
            price=price,
        )

    # 入了仓位
    match = BUY_ENTERED.search(message)
    if match:
        ticker = match.group(1).upper()
        price = float(match.group(2))
        position_size = _resolve_position_size(message)
        return _make_stock(
            ticker=ticker,
            instruction_type=InstructionType.BUY,
            message_id=message_id,
            raw_message=message,
            price=price,
            position_size=position_size,
        )

    # 单价 + 回吸/吸回/低吸
    match = BUY_ABSORB_SINGLE.search(message)
    if match:
        ticker = match.group(1).upper()
        price = float(match.group(2))
        position_size = _resolve_position_size(message)
        return _make_stock(
            ticker=ticker,
            instruction_type=InstructionType.BUY,
            message_id=message_id,
            raw_message=message,
            price=price,
            position_size=position_size,
        )

    # 价格直接紧跟回吸
    match = BUY_PRICE_ABSORB.search(message)
    if match:
        ticker = match.group(1).upper()
        price = float(match.group(2))
        position_size = _resolve_position_size(message)
        return _make_stock(
            ticker=ticker,
            instruction_type=InstructionType.BUY,
            message_id=message_id,
            raw_message=message,
            price=price,
            position_size=position_size,
        )

    # 挂单在
    match = BUY_HANG_ORDER.search(message)
    if match:
        ticker = match.group(1).upper()
        price = float(match.group(2))
        pos = _POSITION_SIZE_PATTERN.search(message)
        position_size = pos.group(1) if pos else "小仓位"
        return _make_stock(
            ticker=ticker,
            instruction_type=InstructionType.BUY,
            message_id=message_id,
            raw_message=message,
            price=price,
            position_size=position_size,
        )

    # 挂单的XX的低吸
    match = BUY_HANG_ABSORB.search(message)
    if match:
        ticker = match.group(1).upper()
        price = float(match.group(2))
        return _make_stock(
            ticker=ticker,
            instruction_type=InstructionType.BUY,
            message_id=message_id,
            raw_message=message,
            price=price,
            position_size="小仓位",
        )

    # 价格附近接
    match = BUY_CATCH_PRICE.search(message)
    if match:
        ticker = match.group(1).upper()
        price = _normalize_price(match.group(2))
        pos = _POSITION_SIZE_PATTERN.search(message)
        position_size = pos.group(1) if pos else None
        return _make_stock(
            ticker=ticker,
            instruction_type=InstructionType.BUY,
            message_id=message_id,
            raw_message=message,
            price=price,
            position_size=position_size,
        )

    # price吸回 ticker
    match = BUY_PRICE_THEN_TICKER.search(message)
    if match:
        price = float(match.group(1))
        ticker = match.group(2).upper()
        return _make_stock(
            ticker=ticker,
            instruction_type=InstructionType.BUY,
            message_id=message_id,
            raw_message=message,
            price=price,
        )

    # 附近小加
    match = BUY_SMALL_ADD.search(message)
    if match:
        ticker = match.group(1).upper()
        price = float(match.group(2))
        return _make_stock(
            ticker=ticker,
            instruction_type=InstructionType.BUY,
            message_id=message_id,
            raw_message=message,
            price=price,
            position_size="小仓位",
        )

    # 价格 + 附近吸 (价格引用)
    match = BUY_PRICE_REF_ABSORB.search(message)
    if match:
        ticker = match.group(1).upper()
        price = float(match.group(2))
        pos = _POSITION_SIZE_PATTERN.search(message)
        position_size = pos.group(1) if pos else None
        return _make_stock(
            ticker=ticker,
            instruction_type=InstructionType.BUY,
            message_id=message_id,
            raw_message=message,
            price=price,
            position_size=position_size,
        )

    # 开了一笔/建了一笔
    match = BUY_OPENED_ONE.search(message)
    if match:
        ticker = match.group(1).upper()
        price = float(match.group(2))
        pos = _POSITION_SIZE_PATTERN.search(message)
        position_size = pos.group(1) if pos else None
        return _make_stock(
            ticker=ticker,
            instruction_type=InstructionType.BUY,
            message_id=message_id,
            raw_message=message,
            price=price,
            position_size=position_size,
        )

    # 价格区间 + 支撑
    match = BUY_RANGE_SUPPORT.search(message)
    if match:
        ticker = match.group(1).upper()
        lo, hi = _sort_range(float(match.group(2)), float(match.group(3)))
        pos = _POSITION_SIZE_PATTERN.search(message)
        position_size = pos.group(1) if pos else None
        return _make_stock(
            ticker=ticker,
            instruction_type=InstructionType.BUY,
            message_id=message_id,
            raw_message=message,
            price=_round2((lo + hi) / 2),
            price_range=(lo, hi),
            position_size=position_size,
        )

    # 回吸在前，价格区间在后
    match = BUY_ABSORB_THEN_RANGE.search(message)
    if match:
        ticker = match.group(1).upper()
        lo, hi = _sort_range(float(match.group(2)), float(match.group(3)))
        pos = _POSITION_SIZE_PATTERN.search(message)
        position_size = pos.group(1) if pos else None
        return _make_stock(
            ticker=ticker,
            instruction_type=InstructionType.BUY,
            message_id=message_id,
            raw_message=message,
            price=_round2((lo + hi) / 2),
            price_range=(lo, hi),
            position_size=position_size,
        )

    # ticker + price 直接列举
    match = BUY_LIST_PRICE.search(message)
    if match:
        ticker = match.group(1).upper()
        price = float(match.group(2))
        return _make_stock(
            ticker=ticker,
            instruction_type=InstructionType.BUY,
            message_id=message_id,
            raw_message=message,
            price=price,
        )

    # ===== ticker 在句尾/中间的买入模式 =====

    match = BUY_OPEN_SUFFIX.search(message)
    if match:
        price = _normalize_price(match.group(1))
        ticker = match.group(2).upper()
        pos = _POSITION_SIZE_PATTERN.search(message)
        position_size = pos.group(1) if pos else "小仓位"
        return _make_stock(
            ticker=ticker,
            instruction_type=InstructionType.BUY,
            message_id=message_id,
            raw_message=message,
            price=price,
            position_size=position_size,
        )

    match = BUY_RANGE_BUILD_SUFFIX.search(message)
    if match:
        lo, hi = _sort_range(
            _normalize_price(match.group(1)),
            _normalize_price(match.group(2)),
        )
        ticker = match.group(3).upper()
        pos = _POSITION_SIZE_PATTERN.search(message)
        position_size = pos.group(1) if pos else None
        return _make_stock(
            ticker=ticker,
            instruction_type=InstructionType.BUY,
            message_id=message_id,
            raw_message=message,
            price=_round2((lo + hi) / 2),
            price_range=(lo, hi),
            position_size=position_size,
        )

    match = BUY_ABSORB_BACK_SUFFIX.search(message)
    if match:
        price = _normalize_price(match.group(1))
        ticker = match.group(2).upper()
        return _make_stock(
            ticker=ticker,
            instruction_type=InstructionType.BUY,
            message_id=message_id,
            raw_message=message,
            price=price,
        )

    match = BUY_TICKER_ABSORB_HANG.search(message)
    if match:
        ticker = match.group(1).upper()
        price = _normalize_price(match.group(2))
        return _make_stock(
            ticker=ticker,
            instruction_type=InstructionType.BUY,
            message_id=message_id,
            raw_message=message,
            price=price,
            position_size="小仓位",
        )

    match = BUY_ACTION_TICKER_AT_PRICE.search(message)
    if match:
        ticker = match.group(1).upper()
        price = _normalize_price(match.group(2))
        position_size = _resolve_position_size(message)
        return _make_stock(
            ticker=ticker,
            instruction_type=InstructionType.BUY,
            message_id=message_id,
            raw_message=message,
            price=price,
            position_size=position_size,
        )

    match = BUY_POSITION_TICKER_ACTION.search(message)
    if match:
        price = _normalize_price(match.group(1))
        ticker = match.group(2).upper()
        position_size = _resolve_position_size(message)
        return _make_stock(
            ticker=ticker,
            instruction_type=InstructionType.BUY,
            message_id=message_id,
            raw_message=message,
            price=price,
            position_size=position_size,
        )

    match = BUY_PRICE_ACTION_SUFFIX.search(message)
    if match:
        price = _normalize_price(match.group(1))
        ticker = match.group(2).upper()
        position_size = _resolve_position_size(message)
        return _make_stock(
            ticker=ticker,
            instruction_type=InstructionType.BUY,
            message_id=message_id,
            raw_message=message,
            price=price,
            position_size=position_size,
        )

    match = BUY_PRICE_ADD_POSITION_SUFFIX.search(message)
    if match:
        price = _normalize_price(match.group(1))
        ticker = match.group(2).upper()
        position_size = _resolve_position_size(message)
        return _make_stock(
            ticker=ticker,
            instruction_type=InstructionType.BUY,
            message_id=message_id,
            raw_message=message,
            price=price,
            position_size=position_size,
        )

    match = BUY_APPROX_ACTION_TICKER_SUFFIX.search(message)
    if match:
        price = _normalize_price(match.group(1))
        ticker = match.group(2).upper()
        position_size = _resolve_position_size(message)
        return _make_stock(
            ticker=ticker,
            instruction_type=InstructionType.BUY,
            message_id=message_id,
            raw_message=message,
            price=price,
            position_size=position_size,
        )

    match = BUY_OPEN_POSITION_TICKER_SUFFIX.search(message)
    if match:
        price = _normalize_price(match.group(1))
        ticker = match.group(2).upper()
        position_size = _resolve_position_size(message)
        return _make_stock(
            ticker=ticker,
            instruction_type=InstructionType.BUY,
            message_id=message_id,
            raw_message=message,
            price=price,
            position_size=position_size,
        )

    match = BUY_VERBOSE_ACTION_SUFFIX.search(message)
    if match:
        price = _normalize_price(match.group(1))
        ticker = match.group(2).upper()
        position_size = _resolve_position_size(message)
        return _make_stock(
            ticker=ticker,
            instruction_type=InstructionType.BUY,
            message_id=message_id,
            raw_message=message,
            price=price,
            position_size=position_size,
        )

    return None


def _parse_sell(message: str, message_id: str) -> StockInstruction | None:  # noqa: C901
    # 标准格式
    for pattern in (SELL_PATTERN_1, SELL_PATTERN_2, SELL_PATTERN_3):
        match = pattern.search(message)
        if not match:
            continue
        ticker = match.group(1).upper()
        price = float(match.group(2))
        return _make_stock(
            ticker=ticker,
            instruction_type=InstructionType.SELL,
            message_id=message_id,
            raw_message=message,
            price=price,
            sell_quantity="全部",
        )

    # tsll ... 16.04附近可以出昨天16.02的
    match = SELL_PATTERN_4.search(message)
    if match:
        ticker = match.group(1).upper()
        price = float(match.group(2))
        return _make_stock(
            ticker=ticker,
            instruction_type=InstructionType.SELL,
            message_id=message_id,
            raw_message=message,
            price=price,
            sell_quantity="全部",
        )

    # 16.4可以出15.43的一半（ticker 可能在句首）
    match = SELL_PATTERN_5.search(message)
    if match:
        ticker = (match.group(1) or "").strip().upper()
        if not ticker:
            ticker = next(
                (
                    m.group(1).upper()
                    for m in re.finditer(r'\b([A-Za-z]{2,5})\b', message)
                    if m.group(1).upper() != "可以"
                ),
                "",
            )
        if not ticker:
            return None
        price = float(match.group(2))
        half = match.group(4)
        sell_quantity = "1/2" if half and "半" in str(half) else "全部"
        return _make_stock(
            ticker=ticker,
            instruction_type=InstructionType.SELL,
            message_id=message_id,
            raw_message=message,
            price=price,
            sell_quantity=sell_quantity,
        )

    # 15.75出之前15.45剩下一半tsll
    match = SELL_PATTERN_6.search(message)
    if match:
        price = float(match.group(1))
        half = match.group(3)
        ticker = (match.group(4) or "").upper()
        sell_quantity = "1/2" if (half and "半" in str(half)) else "全部"
        return _make_stock(
            ticker=ticker,
            instruction_type=InstructionType.SELL,
            message_id=message_id,
            raw_message=message,
            price=price,
            sell_quantity=sell_quantity,
        )

    # tsll 可以15.3出15.17的
    match = SELL_PATTERN_7.search(message)
    if match:
        ticker = match.group(1).upper()
        price = float(match.group(2))
        return _make_stock(
            ticker=ticker,
            instruction_type=InstructionType.SELL,
            message_id=message_id,
            raw_message=message,
            price=price,
            sell_quantity="全部",
        )

    # tsll 在到15.76可以在出15.48那部分
    match = SELL_PATTERN_8.search(message)
    if match:
        ticker = match.group(1).upper()
        price = float(match.group(2))
        return _make_stock(
            ticker=ticker,
            instruction_type=InstructionType.SELL,
            message_id=message_id,
            raw_message=message,
            price=price,
            sell_quantity="全部",
        )

    # "nvdl今天注意分时转弯时候出84.5那部分"
    match = SELL_TICKER_OUT_PRICE_PART.search(message)
    if match:
        ticker = match.group(1).upper()
        price = float(match.group(2))
        return _make_stock(
            ticker=ticker,
            instruction_type=InstructionType.SELL,
            message_id=message_id,
            raw_message=message,
            price=price,
            sell_quantity="全部",
        )

    # "nvdl可以86.75 出"
    match = SELL_TICKER_CAN_PRICE_OUT.search(message)
    if match:
        ticker = match.group(1).upper()
        price = float(match.group(2))
        sq = "1/2" if "一半" in message else "全部"
        return _make_stock(
            ticker=ticker,
            instruction_type=InstructionType.SELL,
            message_id=message_id,
            raw_message=message,
            price=price,
            sell_quantity=sq,
        )

    # 11. 价格出一半+参考价
    match = SELL_HALF_WITH_REF.search(message)
    if match:
        ticker = match.group(1).upper()
        price = float(match.group(2))
        return _make_stock(
            ticker=ticker,
            instruction_type=InstructionType.SELL,
            message_id=message_id,
            raw_message=message,
            price=price,
            sell_quantity="1/2",
        )

    # 12. "XX时候减掉 YY加仓的"
    match = SELL_TIME_REDUCE.search(message)
    if match:
        ticker = match.group(1).upper()
        price = float(match.group(2))
        return _make_stock(
            ticker=ticker,
            instruction_type=InstructionType.SELL,
            message_id=message_id,
            raw_message=message,
            price=price,
            sell_quantity="全部",
        )

    # 9. 价格区间 + 一半
    match = SELL_RANGE_HALF.search(message)
    if match:
        ticker = match.group(1).upper()
        lo, hi = _sort_range(float(match.group(2)), float(match.group(3)))
        return _make_stock(
            ticker=ticker,
            instruction_type=InstructionType.SELL,
            message_id=message_id,
            raw_message=message,
            price=_round2((lo + hi) / 2),
            price_range=(lo, hi),
            sell_quantity="1/2",
        )

    # 10. 单价 + 一半
    match = SELL_SINGLE_HALF.search(message)
    if match:
        ticker = match.group(1).upper()
        price = float(match.group(2))
        return _make_stock(
            ticker=ticker,
            instruction_type=InstructionType.SELL,
            message_id=message_id,
            raw_message=message,
            price=price,
            sell_quantity="1/2",
        )

    # 10b. "nvdl之前剩下的一半在107.5出"
    match = SELL_HALF_AT_PRICE.search(message)
    if match:
        ticker = match.group(1).upper()
        price = float(match.group(2))
        return _make_stock(
            ticker=ticker,
            instruction_type=InstructionType.SELL,
            message_id=message_id,
            raw_message=message,
            price=price,
            sell_quantity="1/2",
        )

    # 10c. "nvdl上周五剩下点仓位 在盘前90.9附近也出点"
    match = SELL_ALSO_OUT_SOME.search(message)
    if match:
        ticker = match.group(1).upper()
        price = float(match.group(2))
        return _make_stock(
            ticker=ticker,
            instruction_type=InstructionType.SELL,
            message_id=message_id,
            raw_message=message,
            price=price,
            sell_quantity="全部",
        )

    # 13. 价格区间 + 分批出/减点
    match = SELL_RANGE_PARTIAL.search(message)
    if match:
        ticker = match.group(1).upper()
        lo, hi = _sort_range(float(match.group(2)), float(match.group(3)))
        sq = "1/2" if "分批出" in message else "小仓位"
        return _make_stock(
            ticker=ticker,
            instruction_type=InstructionType.SELL,
            message_id=message_id,
            raw_message=message,
            price=_round2((lo + hi) / 2),
            price_range=(lo, hi),
            sell_quantity=sq,
        )

    # 14. 价格区间 + 出/减 (通用)
    match = SELL_RANGE_FULL.search(message)
    if match:
        ticker = match.group(1).upper()
        lo, hi = _sort_range(float(match.group(2)), float(match.group(3)))
        return _make_stock(
            ticker=ticker,
            instruction_type=InstructionType.SELL,
            message_id=message_id,
            raw_message=message,
            price=_round2((lo + hi) / 2),
            price_range=(lo, hi),
            sell_quantity="全部",
        )

    # 18. "XX-YY之间出"
    match = SELL_RANGE_BETWEEN.search(message)
    if match:
        ticker = match.group(1).upper()
        lo, hi = _sort_range(float(match.group(2)), float(match.group(3)))
        return _make_stock(
            ticker=ticker,
            instruction_type=InstructionType.SELL,
            message_id=message_id,
            raw_message=message,
            price=_round2((lo + hi) / 2),
            price_range=(lo, hi),
            sell_quantity="全部",
        )

    # 16b. ticker + price + 附近卖出
    match = SELL_PRICE_SELL_OUT.search(message)
    if match:
        ticker = match.group(1).upper()
        price = float(match.group(2))
        sq = "1/2" if "一半" in message else "全部"
        return _make_stock(
            ticker=ticker,
            instruction_type=InstructionType.SELL,
            message_id=message_id,
            raw_message=message,
            price=price,
            sell_quantity=sq,
        )

    # 15. 单价 + 减点/分批出
    match = SELL_PARTIAL.search(message)
    if match:
        ticker = match.group(1).upper()
        price = float(match.group(2))
        sq = "1/2" if "分批出" in message else "小仓位"
        return _make_stock(
            ticker=ticker,
            instruction_type=InstructionType.SELL,
            message_id=message_id,
            raw_message=message,
            price=price,
            sell_quantity=sq,
        )

    # 16. 单价 + 减 (视为小仓位减出)
    match = SELL_REDUCE.search(message)
    if match:
        ticker = match.group(1).upper()
        price = float(match.group(2))
        return _make_stock(
            ticker=ticker,
            instruction_type=InstructionType.SELL,
            message_id=message_id,
            raw_message=message,
            price=price,
            sell_quantity="小仓位",
        )

    # 17. 短线出
    match = SELL_SHORT_TERM.search(message)
    if match:
        ticker = match.group(1).upper()
        price = float(match.group(2))
        return _make_stock(
            ticker=ticker,
            instruction_type=InstructionType.SELL,
            message_id=message_id,
            raw_message=message,
            price=price,
            sell_quantity="全部",
        )

    # 19a. 附近出+参考价+的一半
    match = SELL_APPROX_OUT_REF_HALF.search(message)
    if match:
        ticker = match.group(1).upper()
        price = _normalize_price(match.group(2))
        return _make_stock(
            ticker=ticker,
            instruction_type=InstructionType.SELL,
            message_id=message_id,
            raw_message=message,
            price=price,
            sell_quantity="1/2",
        )

    # 19. 附近出+参考价
    match = SELL_APPROX_OUT_REF.search(message)
    if match:
        ticker = match.group(1).upper()
        price = float(match.group(2))
        return _make_stock(
            ticker=ticker,
            instruction_type=InstructionType.SELL,
            message_id=message_id,
            raw_message=message,
            price=price,
            sell_quantity="全部",
        )

    # 22. 出之前/出+参考价
    match = SELL_OUT_BEFORE_REF.search(message)
    if match:
        ticker = match.group(1).upper()
        price = float(match.group(2))
        return _make_stock(
            ticker=ticker,
            instruction_type=InstructionType.SELL,
            message_id=message_id,
            raw_message=message,
            price=price,
            sell_quantity="全部",
        )

    # 20. 把XX买的出了
    match = SELL_PUT_OUT_REF.search(message)
    if match:
        ticker = match.group(1).upper()
        price = float(match.group(2))
        return _make_stock(
            ticker=ticker,
            instruction_type=InstructionType.SELL,
            message_id=message_id,
            raw_message=message,
            price=price,
            sell_quantity="全部",
        )

    # 21. 简单附近出
    match = SELL_APPROX_SIMPLE.search(message)
    if match:
        ticker = match.group(1).upper()
        price = float(match.group(2))
        return _make_stock(
            ticker=ticker,
            instruction_type=InstructionType.SELL,
            message_id=message_id,
            raw_message=message,
            price=price,
            sell_quantity="全部",
        )

    # 23. XX那部分...出
    match = SELL_THAT_PART.search(message)
    if match:
        ticker = match.group(1).upper()
        ref_price = float(match.group(2))
        return _make_stock(
            ticker=ticker,
            instruction_type=InstructionType.SELL,
            message_id=message_id,
            raw_message=message,
            price=ref_price,
            sell_quantity="全部",
        )

    # 24. 出昨天/之前XX买的那部分
    match = SELL_YESTERDAY_BUY_PART.search(message)
    if match:
        ticker = match.group(1).upper()
        ref_price = float(match.group(2))
        return _make_stock(
            ticker=ticker,
            instruction_type=InstructionType.SELL,
            message_id=message_id,
            raw_message=message,
            price=ref_price,
            sell_quantity="全部",
        )

    # ===== ticker 在句尾/中间的卖出模式 =====

    match = SELL_RANGE_OUT_REF_SUFFIX.search(message)
    if match:
        lo, hi = _sort_range(
            _normalize_price(match.group(1)),
            _normalize_price(match.group(2)),
        )
        ticker = match.group(4).upper()
        sq = "1/2" if "一半" in message else "全部"
        return _make_stock(
            ticker=ticker,
            instruction_type=InstructionType.SELL,
            message_id=message_id,
            raw_message=message,
            price=_round2((lo + hi) / 2),
            price_range=(lo, hi),
            sell_quantity=sq,
        )

    match = SELL_HALF_REF_SUFFIX.search(message)
    if match:
        price = _normalize_price(match.group(1))
        ticker = match.group(3).upper()
        return _make_stock(
            ticker=ticker,
            instruction_type=InstructionType.SELL,
            message_id=message_id,
            raw_message=message,
            price=price,
            sell_quantity="1/2",
        )

    match = SELL_PRICE_OUT_REF_SUFFIX.search(message)
    if match:
        price = _normalize_price(match.group(1))
        ticker = match.group(3).upper()
        return _make_stock(
            ticker=ticker,
            instruction_type=InstructionType.SELL,
            message_id=message_id,
            raw_message=message,
            price=price,
            sell_quantity="全部",
        )

    match = SELL_BATCH_REF_SUFFIX.search(message)
    if match:
        lo, hi = _sort_range(
            _normalize_price(match.group(1)),
            _normalize_price(match.group(2)),
        )
        ticker = match.group(4).upper()
        return _make_stock(
            ticker=ticker,
            instruction_type=InstructionType.SELL,
            message_id=message_id,
            raw_message=message,
            price=_round2((lo + hi) / 2),
            price_range=(lo, hi),
            sell_quantity="1/2",
        )

    match = SELL_RANGE_REDUCE_SUFFIX.search(message)
    if match:
        lo, hi = _sort_range(
            _normalize_price(match.group(1)),
            _normalize_price(match.group(2)),
        )
        ticker = match.group(3).upper()
        sq = "1/2" if "一半" in message else "小仓位"
        return _make_stock(
            ticker=ticker,
            instruction_type=InstructionType.SELL,
            message_id=message_id,
            raw_message=message,
            price=_round2((lo + hi) / 2),
            price_range=(lo, hi),
            sell_quantity=sq,
        )

    match = SELL_PRICE_OUT_SUFFIX.search(message)
    if match:
        p1 = _normalize_price(match.group(1))
        p2_str = match.group(2)
        ticker = match.group(3).upper()
        if p2_str:
            lo, hi = _sort_range(p1, _normalize_price(p2_str))
            return _make_stock(
                ticker=ticker,
                instruction_type=InstructionType.SELL,
                message_id=message_id,
                raw_message=message,
                price=_round2((lo + hi) / 2),
                price_range=(lo, hi),
                sell_quantity="全部",
            )
        return _make_stock(
            ticker=ticker,
            instruction_type=InstructionType.SELL,
            message_id=message_id,
            raw_message=message,
            price=p1,
            sell_quantity="全部",
        )

    # SELL_PRICE_OUT_REF_SUFFIX second pass (already checked above, skip duplicate)

    match = SELL_REDUCE_HALF_REF_SUFFIX.search(message)
    if match:
        price = _normalize_price(match.group(1))
        ticker = match.group(3).upper()
        return _make_stock(
            ticker=ticker,
            instruction_type=InstructionType.SELL,
            message_id=message_id,
            raw_message=message,
            price=price,
            sell_quantity="1/2",
        )

    match = SELL_SINGLE_REDUCE_SUFFIX.search(message)
    if match:
        price = _normalize_price(match.group(1))
        ticker = match.group(2).upper()
        sq = "1/2" if "一半" in message else "全部"
        return _make_stock(
            ticker=ticker,
            instruction_type=InstructionType.SELL,
            message_id=message_id,
            raw_message=message,
            price=price,
            sell_quantity=sq,
        )

    match = SELL_OUT_HALF_NO_REF_SUFFIX.search(message)
    if match:
        price = _normalize_price(match.group(1))
        ticker = match.group(2).upper()
        return _make_stock(
            ticker=ticker,
            instruction_type=InstructionType.SELL,
            message_id=message_id,
            raw_message=message,
            price=price,
            sell_quantity="1/2",
        )

    match = SELL_PRICE_OUT_GAP_TICKER_SUFFIX.search(message)
    if match:
        price = _normalize_price(match.group(1))
        ticker = match.group(2).upper()
        sq = "1/2" if "一半" in message else ("1/3" if "三分之一" in message else "全部")
        return _make_stock(
            ticker=ticker,
            instruction_type=InstructionType.SELL,
            message_id=message_id,
            raw_message=message,
            price=price,
            sell_quantity=sq,
        )

    match = SELL_APPROX_OUT_TICKER_SUFFIX.search(message)
    if match:
        price = _normalize_price(match.group(1))
        ticker = match.group(2).upper()
        sq = "1/2" if "一半" in message else "全部"
        return _make_stock(
            ticker=ticker,
            instruction_type=InstructionType.SELL,
            message_id=message_id,
            raw_message=message,
            price=price,
            sell_quantity=sq,
        )

    return None


def _parse_stop_loss(message: str, message_id: str) -> StockInstruction | None:
    match = STOCK_STOP_LOSS_PATTERN.search(message)
    if not match:
        return None
    ticker = match.group(1) or match.group(2)
    if not ticker:
        return None  # 无 ticker 时让给关注列表 fallback（此模块无 fallback，直接 None）
    price = float(match.group(3))
    return _make_stock(
        ticker=ticker.upper(),
        instruction_type=InstructionType.MODIFY,
        message_id=message_id,
        raw_message=message,
        stop_loss_price=price,
    )


def _parse_take_profit(message: str, message_id: str) -> StockInstruction | None:
    match = STOCK_TAKE_PROFIT_PATTERN.search(message)
    if not match:
        return None
    ticker = match.group(1) or match.group(2)
    if not ticker:
        return None
    price = float(match.group(3))
    portion_raw = match.group(4) if len(match.groups()) >= 4 and match.group(4) else "全部"
    portion = _PORTION_MAP.get(portion_raw, portion_raw)
    return _make_stock(
        ticker=ticker.upper(),
        instruction_type=InstructionType.SELL,
        message_id=message_id,
        raw_message=message,
        price=price,
        sell_quantity=portion,
        take_profit_price=price,
    )
