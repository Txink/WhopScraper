"""
Tests for app.parser.option_parser — Task 18.

8 test cases as specified in the task, covering:
1. Basic CALL
2. Basic PUT
3. Shorthand c/p
4. Explicit date
5. Stop-loss
6. No ticker (should return None)
7. Unrecognizable message
8. Longport symbol format helper

Posted-at timestamps are passed explicitly to keep tests deterministic.

Date reference (verified):
  2026-04-22 is Wednesday (weekday=2). This-week Friday = 2026-04-24.
  2026-04-24 is Friday (weekday=4).  This-week Friday = 2026-04-24 (same day).
  Next-week Friday from 2026-04-22 = 2026-05-01.
"""

from __future__ import annotations

from datetime import date, datetime

import pytest

from app.domain.instruction import InstructionType
from app.parser.option_parser import _make_longport_symbol, _resolve_expiry, parse

# ---------------------------------------------------------------------------
# Helper: a fixed Wednesday message timestamp (2026-04-22 10:00)
# ---------------------------------------------------------------------------
_WED = datetime(2026, 4, 22, 10, 0, 0)  # Wednesday → this Friday = 2026-04-24
_FRI = datetime(2026, 4, 24, 10, 0, 0)  # Friday itself → this Friday = 2026-04-24


# ---------------------------------------------------------------------------
# 1. test_parse_basic_call
# ---------------------------------------------------------------------------
def test_parse_basic_call() -> None:
    """'NVDA 135 CALL 本周 2.15 进' → CALL, NVDA, strike=135, price=2.15, expiry=next Friday."""
    result = parse("NVDA 135 CALL 本周 2.15 进", message_id="opt1", message_posted_at=_WED)
    assert result is not None
    assert result.instruction_type == InstructionType.BUY
    assert result.ticker == "NVDA"
    assert result.option_type == "CALL"
    assert result.strike == pytest.approx(135.0)
    assert result.price == pytest.approx(2.15)
    # 本周 from Wednesday 2026-04-22 → Friday 2026-04-24
    assert result.expiry == date(2026, 4, 24)
    # symbol should be set
    assert result.symbol == "NVDA260424C135000.US"


# ---------------------------------------------------------------------------
# 2. test_parse_basic_put
# ---------------------------------------------------------------------------
def test_parse_basic_put() -> None:
    """'AAPL 210 PUT 下周 1.50 进' → PUT, AAPL, strike=210, price=1.50."""
    result = parse("AAPL 210 PUT 下周 1.50 进", message_id="opt2", message_posted_at=_WED)
    assert result is not None
    assert result.instruction_type == InstructionType.BUY
    assert result.ticker == "AAPL"
    assert result.option_type == "PUT"
    assert result.strike == pytest.approx(210.0)
    assert result.price == pytest.approx(1.50)
    # 下周 from Wednesday 2026-04-22 → Friday 2026-05-01
    assert result.expiry == date(2026, 5, 1)


# ---------------------------------------------------------------------------
# 3. test_parse_call_shorthand
# ---------------------------------------------------------------------------
def test_parse_call_shorthand() -> None:
    """'INTC 48C 本周 1.15 小仓位' → CALL, INTC, strike=48."""
    result = parse("INTC 48C 本周 1.15 小仓位", message_id="opt3", message_posted_at=_WED)
    assert result is not None
    assert result.ticker == "INTC"
    assert result.option_type == "CALL"
    assert result.strike == pytest.approx(48.0)
    assert result.price == pytest.approx(1.15)
    assert result.expiry == date(2026, 4, 24)


# ---------------------------------------------------------------------------
# 4. test_parse_with_explicit_date
# ---------------------------------------------------------------------------
def test_parse_with_explicit_date() -> None:
    """'TSLA 280 PUT 5/3 4.50' → expiry=2026-05-03."""
    result = parse("TSLA 280 PUT 5/3 4.50", message_id="opt4", message_posted_at=_WED)
    assert result is not None
    assert result.ticker == "TSLA"
    assert result.option_type == "PUT"
    assert result.strike == pytest.approx(280.0)
    assert result.price == pytest.approx(4.50)
    assert result.expiry == date(2026, 5, 3)


# ---------------------------------------------------------------------------
# 5. test_parse_stop_loss
# ---------------------------------------------------------------------------
def test_parse_stop_loss() -> None:
    """'INTC 48C 止损 0.9' → stop_loss_price=0.9."""
    result = parse("INTC 48C 止损 0.9", message_id="opt5", message_posted_at=_WED)
    assert result is not None
    assert result.stop_loss_price == pytest.approx(0.9)


# ---------------------------------------------------------------------------
# 6. test_parse_take_profit_no_ticker → None
# ---------------------------------------------------------------------------
def test_parse_take_profit_no_ticker() -> None:
    """'1.75 出三分之一' has no ticker → parse returns None (context resolver's job)."""
    result = parse("1.75 出三分之一", message_id="opt6", message_posted_at=_WED)
    assert result is None


# ---------------------------------------------------------------------------
# 7. test_parse_unrecognizable → None
# ---------------------------------------------------------------------------
def test_parse_unrecognizable() -> None:
    """'盘后信息参考' → None."""
    result = parse("盘后信息参考", message_id="opt7", message_posted_at=_WED)
    assert result is None


# ---------------------------------------------------------------------------
# 8. test_longport_symbol_format
# ---------------------------------------------------------------------------
def test_longport_symbol_format() -> None:
    """Unit-test _make_longport_symbol directly."""
    # Integer strike
    sym = _make_longport_symbol("NVDA", date(2026, 4, 24), "CALL", 135.0)
    assert sym == "NVDA260424C135000.US"

    # PUT
    sym = _make_longport_symbol("AAPL", date(2026, 5, 1), "PUT", 210.0)
    assert sym == "AAPL260501P210000.US"

    # Fractional strike (e.g. 135.5)
    sym = _make_longport_symbol("TSLA", date(2026, 5, 3), "CALL", 135.5)
    assert sym == "TSLA260503C135500.US"

    # Small strike (e.g. 19.5)
    sym = _make_longport_symbol("RIVN", date(2026, 1, 16), "PUT", 19.5)
    assert sym == "RIVN260116P19500.US"


# ---------------------------------------------------------------------------
# Bonus: test _resolve_expiry helper
# ---------------------------------------------------------------------------
def test_resolve_expiry_this_week_wednesday() -> None:
    """本周 from Wednesday 2026-04-22 → that Friday 2026-04-24."""
    result = _resolve_expiry("本周", _WED)
    assert result == date(2026, 4, 24)


def test_resolve_expiry_this_week_friday() -> None:
    """本周 from Friday 2026-04-24 → that same Friday (not next)."""
    result = _resolve_expiry("本周", _FRI)
    assert result == date(2026, 4, 24)


def test_resolve_expiry_next_week() -> None:
    """下周 from Wednesday 2026-04-22 → Friday 2026-05-01."""
    result = _resolve_expiry("下周", _WED)
    assert result == date(2026, 5, 1)


def test_resolve_expiry_explicit_date() -> None:
    """5/3 → 2026-05-03 (year from posted_at)."""
    result = _resolve_expiry("5/3", _WED)
    assert result == date(2026, 5, 3)


def test_resolve_expiry_unrecognized() -> None:
    """Garbage string → None."""
    result = _resolve_expiry("foobar", _WED)
    assert result is None
