"""context_resolver — 三段式 ticker 补全。

当单条消息解析结果 ticker 为空时，按以下顺序尝试补全：
  1. refer   — msg.quoted 引用消息重新解析，取其 ticker
  2. watchlist — 从 msg.content 中提取大写 token，与关注股票列表取交集
                 （仅 stock，唯一匹配才生效）
  3. recent  — 从 DB 查询同 source 的最近 N 条任务，取最新有 ticker 的一条

规则：
  - parsed is None → 返回 None（解析器连动作/价格都无法确定，不从上下文凭空构造）
  - parsed.ticker 非空 → 原样返回（快速路径）
  - 任意一段补全成功 → 返回带 ticker 的新 Instruction（dataclasses.replace），同时写入
    context_source
  - 三段均失败 → 返回 None
"""
from __future__ import annotations

import dataclasses
import json
import logging
import re
from datetime import timedelta
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.instruction import Instruction, OptionInstruction, StockInstruction
from app.domain.message import Message

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

# backend/app/parser/context_resolver.py  →  project_root = ../../..
_HERE = Path(__file__).parent  # backend/app/parser
_PROJECT_ROOT = _HERE.parent.parent.parent  # signal-station/


def load_watched_tickers(
    path: Path = _PROJECT_ROOT / "config" / "watched_stocks.json",
) -> set[str]:
    """Load the watched-stocks whitelist from JSON; return uppercase ticker set.

    The JSON format is: { "ticker_lowercase": { "position": ..., "bucket": ... }, ... }
    Keys starting with "_" are skipped (comment convention).
    Returns an empty set if the file is missing or malformed.
    """
    try:
        with open(path, encoding="utf-8") as f:
            data: Any = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        logger.warning("watched_stocks file not found or invalid: %s", path)
        return set()
    if not isinstance(data, dict):
        return set()
    return {
        k.strip().upper()
        for k in data
        if k and not k.startswith("_") and isinstance(data[k], dict)
    }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_TICKER_TOKEN_RE = re.compile(r"\b([A-Z]{2,5})\b")

# Words that are commonly found in trading messages but are NOT tickers
_NON_TICKER_WORDS: frozenset[str] = frozenset(
    {
        "CALL", "PUT", "CALLS", "PUTS",
        "THE", "AND", "FOR", "ALL", "OUT", "NEW", "ONE", "SEE",
        "BUY", "SELL", "ETF", "ITM", "OTM", "ATM",
        "SL", "TP", "STOP", "LOSS", "TAKE", "PROFIT",
    }
)


def _extract_ticker_tokens(text: str) -> set[str]:
    """Extract plausible uppercase ticker tokens (2-5 letters) from *text*."""
    return {
        m.group(1)
        for m in _TICKER_TOKEN_RE.finditer(text.upper())
        if m.group(1) not in _NON_TICKER_WORDS
    }


def _with_ticker(
    parsed: StockInstruction | OptionInstruction,
    ticker: str,
    context_source: str,
) -> StockInstruction | OptionInstruction:
    """Return a copy of *parsed* with *ticker* and *context_source* filled in.

    Uses ``dataclasses.replace`` which constructs a new dataclass instance
    without going through ``__init__`` / ``__post_init__`` validation.
    ``context_source`` is typed as ``ContextSource`` in the domain but we
    accept ``str`` here because mypy can't narrow Literal types dynamically.
    """
    # dataclasses.replace accepts keyword args that correspond to fields,
    # including those on subclasses.
    return dataclasses.replace(
        parsed,
        ticker=ticker,
        context_source=context_source,  # type: ignore[arg-type]
    )


def _get_ticker(inst: Instruction) -> str:
    """Return ``inst.ticker`` if the instruction is a stock/option type, else ''."""
    if isinstance(inst, (StockInstruction, OptionInstruction)):
        return inst.ticker or ""
    return ""


# ---------------------------------------------------------------------------
# Tier 1: refer
# ---------------------------------------------------------------------------


async def _tier_refer(
    msg: Message,
    parsed: StockInstruction | OptionInstruction,
) -> StockInstruction | OptionInstruction | None:
    """Parse msg.quoted; if it yields a ticker, clone *parsed* with that ticker."""
    if msg.quoted is None:
        return None

    # Lazy imports to avoid circular dependencies at module load time
    from app.parser import option_parser, stock_parser  # noqa: PLC0415

    quoted_content = msg.quoted.content.strip()
    if not quoted_content:
        return None

    referred_ticker: str | None = None

    if msg.source == "option":
        quoted_opt = option_parser.parse(
            quoted_content,
            message_id=msg.quoted.id,
            message_posted_at=msg.quoted.posted_at,
        )
        if quoted_opt is not None and quoted_opt.ticker:
            referred_ticker = quoted_opt.ticker
    else:
        quoted_stock = stock_parser.parse(quoted_content, message_id=msg.quoted.id)
        if quoted_stock is not None and quoted_stock.ticker:
            referred_ticker = quoted_stock.ticker

    if not referred_ticker:
        return None

    return _with_ticker(parsed, referred_ticker, "refer")


# ---------------------------------------------------------------------------
# Tier 2: watchlist
# ---------------------------------------------------------------------------


def _tier_watchlist(
    msg: Message,
    parsed: StockInstruction | OptionInstruction,
    watched_tickers: set[str],
) -> StockInstruction | OptionInstruction | None:
    """Find exactly one watched ticker in msg.content; fill it (stock-only)."""
    if msg.source != "stock":
        return None
    if not watched_tickers:
        return None

    tokens = _extract_ticker_tokens(msg.content)
    matches = tokens & watched_tickers
    if len(matches) != 1:
        # 0 → nothing found; ≥2 → ambiguous; both cases → skip
        return None

    ticker = next(iter(matches))
    return _with_ticker(parsed, ticker, "watchlist")


# ---------------------------------------------------------------------------
# Tier 3: recent
# ---------------------------------------------------------------------------


async def _tier_recent(
    session_factory: async_sessionmaker[AsyncSession],
    msg: Message,
    parsed: StockInstruction | OptionInstruction,
    *,
    recent_window_minutes: int,
    recent_limit: int,
) -> StockInstruction | OptionInstruction | None:
    """Query DB for same-source tasks with tickers within the time window."""
    from app.storage.repo import list_tasks  # noqa: PLC0415

    cutoff = msg.received_at - timedelta(minutes=recent_window_minutes)

    async with session_factory() as session:
        tasks = await list_tasks(
            session,
            limit=recent_limit,
            type_=msg.source,
            status=None,
        )

    # Filter client-side: within the time window + has a ticker
    candidates = [
        t
        for t in tasks
        if t.created_at >= cutoff
        and t.instruction is not None
        and isinstance(t.instruction, (StockInstruction, OptionInstruction))
        and t.instruction.ticker
    ]

    if not candidates:
        return None

    # list_tasks returns tasks ordered by created_at DESC; first = most recent
    recent_inst = candidates[0].instruction
    assert isinstance(recent_inst, (StockInstruction, OptionInstruction))
    return _with_ticker(parsed, recent_inst.ticker, "recent")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def resolve_context(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    msg: Message,
    parsed: Instruction | None,
    watched_tickers: set[str] | None = None,
    recent_window_minutes: int = 120,
    recent_limit: int = 20,
) -> Instruction | None:
    """Try to fill a missing ticker on a parsed instruction using message context.

    Resolution order:
      1. refer     — msg.quoted → re-parse → use its ticker
      2. watchlist — exactly one watched ticker found in msg.content (stock-only)
      3. recent    — most recent same-source DB task with a ticker in the time window

    Rules:
      - ``parsed`` is None → return None (parser couldn't determine action/price;
        context cannot rescue pure chatter).
      - ``parsed`` has a non-empty ticker → return it unchanged (fast path).
      - On success, sets ``context_source`` on the returned (new) instruction.
      - If all three tiers fail → return None.
    """
    # Rule: parsed is None → don't fabricate from context
    if parsed is None:
        return None

    # Only StockInstruction / OptionInstruction carry a ticker; plain Instruction
    # is a base class that has none, so we can't do anything for it.
    if not isinstance(parsed, (StockInstruction, OptionInstruction)):
        return None

    # Fast path: already has a non-empty ticker
    if parsed.ticker:
        return parsed

    # --- Tier 1: refer ---
    result = await _tier_refer(msg, parsed)
    if result is not None:
        return result

    # --- Tier 2: watchlist (stock-only) ---
    if watched_tickers is not None:
        result = _tier_watchlist(msg, parsed, watched_tickers)
        if result is not None:
            return result

    # --- Tier 3: recent ---
    result = await _tier_recent(
        session_factory,
        msg,
        parsed,
        recent_window_minutes=recent_window_minutes,
        recent_limit=recent_limit,
    )
    if result is not None:
        return result

    return None
