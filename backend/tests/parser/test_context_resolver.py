"""Tests for app.parser.context_resolver — Task 19.

Five test cases covering the three resolution tiers:
1. test_already_has_ticker_returns_unchanged
2. test_refer_to_parsed_message_fills_ticker
3. test_watchlist_fills_missing_ticker_on_parsed_stock
4. test_watchlist_ambiguous_returns_none
5. test_recent_fills_ticker_when_parser_returned_none
"""
from __future__ import annotations

import dataclasses
from datetime import UTC, date, datetime

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.instruction import InstructionType, OptionInstruction, StockInstruction
from app.domain.message import Message
from app.domain.status import Status
from app.domain.task import Task
from app.parser.context_resolver import resolve_context
from app.storage.repo import save_task

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 4, 24, 14, 0, 0, tzinfo=UTC)


def _msg(
    id_: str,
    content: str,
    source: str = "stock",
    quoted: Message | None = None,
    posted_at: datetime = _NOW,
) -> Message:
    return Message(
        id=id_,
        content=content,
        raw_content=content,
        author="trader",
        posted_at=posted_at,
        received_at=posted_at,
        source=source,  # type: ignore[arg-type]
        quoted=quoted,
    )


def _stock_inst_with_empty_ticker(
    price: float = 26.5,
    instruction_type: InstructionType = InstructionType.BUY,
) -> StockInstruction:
    """Create a StockInstruction with empty ticker, bypassing __post_init__ guard."""
    obj = object.__new__(StockInstruction)
    # Initialise all fields directly without calling __post_init__
    obj.__dict__.update(
        instruction_type=instruction_type,
        price=price,
        price_range=None,
        quantity=None,
        position_size="一半",
        stop_loss_price=None,
        take_profit_price=None,
        context_source=None,
        parser_notes=[],
        ticker="",
        symbol="",
        sell_quantity=None,
    )
    return obj


def _opt_inst_with_empty_ticker(price: float = 2.15) -> OptionInstruction:
    """Create an OptionInstruction with empty ticker, bypassing __post_init__ guard."""
    obj = object.__new__(OptionInstruction)
    obj.__dict__.update(
        instruction_type=InstructionType.SELL,
        price=price,
        price_range=None,
        quantity=None,
        position_size=None,
        stop_loss_price=None,
        take_profit_price=None,
        context_source=None,
        parser_notes=[],
        ticker="",
        option_type="CALL",
        strike=135.0,
        expiry=date(2026, 4, 25),
        symbol="",
    )
    return obj


def _task_with_stock_inst(
    id_: str,
    ticker: str,
    source: str = "stock",
    created_at: datetime = _NOW,
) -> Task:
    msg = _msg(id_=id_, content=f"{ticker} 26.5 买入", source=source, posted_at=created_at)
    inst = StockInstruction(
        instruction_type=InstructionType.BUY,
        price=26.5,
        price_range=None,
        quantity=None,
        position_size=None,
        stop_loss_price=None,
        take_profit_price=None,
        context_source=None,
        parser_notes=[],
        ticker=ticker,
        symbol=f"{ticker}.US",
        sell_quantity=None,
    )
    task = Task(
        id=id_,
        type="stock",
        status=Status.INSTRUCTION_READY,
        message=msg,
        instruction=inst,
        created_at=created_at,
        updated_at=created_at,
    )
    return task


# ---------------------------------------------------------------------------
# Test 1: already has ticker → unchanged
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_already_has_ticker_returns_unchanged(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """If parsed instruction already has a non-empty ticker, return it unchanged."""
    msg = _msg("m1", "TSLL 26.5 买入")
    parsed = StockInstruction(
        instruction_type=InstructionType.BUY,
        price=26.5,
        price_range=None,
        quantity=None,
        position_size=None,
        stop_loss_price=None,
        take_profit_price=None,
        context_source=None,
        parser_notes=[],
        ticker="TSLL",
        symbol="TSLL.US",
        sell_quantity=None,
    )

    result = await resolve_context(
        session_factory=session_factory,
        msg=msg,
        parsed=parsed,
        watched_tickers={"TSLL"},
    )

    assert result is parsed  # identity check: same object returned unchanged
    assert result.ticker == "TSLL"  # type: ignore[union-attr]
    assert result.context_source is None  # not modified


# ---------------------------------------------------------------------------
# Test 2: refer fills ticker from quoted message
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_refer_to_parsed_message_fills_ticker(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """msg.quoted has a parseable option instruction; ticker should be filled from it."""
    # Quoted message: NVDA 135C 本周 2.15 买 (clearly option BUY for NVDA)
    quoted_msg = _msg(
        id_="q1",
        content="NVDA 135C 本周 2.15 买",
        source="option",
    )
    # Current message: partial info without ticker
    current_msg = _msg(
        id_="m2",
        content="1.75 出一半",
        source="option",
        quoted=quoted_msg,
    )
    # Parser failed to extract ticker from "1.75 出一半"
    parsed = _opt_inst_with_empty_ticker(price=1.75)

    result = await resolve_context(
        session_factory=session_factory,
        msg=current_msg,
        parsed=parsed,
        watched_tickers=None,
    )

    assert result is not None
    assert result.ticker == "NVDA"
    assert result.context_source == "refer"


# ---------------------------------------------------------------------------
# Test 3: watchlist fills missing ticker on already-parsed stock instruction
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_watchlist_fills_missing_ticker_on_parsed_stock(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Content contains exactly one watched ticker (TSLL); resolver fills it."""
    msg = _msg("m3", "TSLL 26.5 加一半", source="stock")
    parsed = _stock_inst_with_empty_ticker(price=26.5)

    result = await resolve_context(
        session_factory=session_factory,
        msg=msg,
        parsed=parsed,
        watched_tickers={"TSLL", "NVDA", "PLTR"},
    )

    assert result is not None
    assert result.ticker == "TSLL"
    assert result.context_source == "watchlist"


# ---------------------------------------------------------------------------
# Test 4: ambiguous watchlist → returns None
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_watchlist_ambiguous_returns_none(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Content contains TSLL and NVDA (both watched) → ambiguous → skip."""
    msg = _msg("m4", "TSLL NVDA 26.5 加一半", source="stock")
    parsed = _stock_inst_with_empty_ticker(price=26.5)

    result = await resolve_context(
        session_factory=session_factory,
        msg=msg,
        parsed=parsed,
        watched_tickers={"TSLL", "NVDA", "PLTR"},
    )

    # watchlist is ambiguous, and no refer or recent context → None
    assert result is None


# ---------------------------------------------------------------------------
# Test 5: recent task fills ticker
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_recent_fills_ticker_when_db_has_recent_task(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """No refer, no watchlist match; DB has a recent TSLL stock task; resolver fills ticker."""
    # Seed the DB with a recent TSLL stock task
    async with session_factory() as session:
        task = _task_with_stock_inst(
            id_="recent-task-1",
            ticker="TSLL",
            source="stock",
            created_at=_NOW,
        )
        await save_task(session, task)

    # Current message: no ticker visible in content, no quoted
    msg = _msg("m5", "26.5 加一半", source="stock", posted_at=_NOW)
    parsed = _stock_inst_with_empty_ticker(price=26.5)

    result = await resolve_context(
        session_factory=session_factory,
        msg=msg,
        parsed=parsed,
        watched_tickers=None,  # no watchlist help
        recent_window_minutes=120,
        recent_limit=20,
    )

    assert result is not None
    assert result.ticker == "TSLL"
    assert result.context_source == "recent"
