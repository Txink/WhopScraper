"""Tests for scripts/validate_parser.py — matcher + run_validation."""

import pytest

from app.domain.instruction import InstructionType, StockInstruction
from scripts.validate_parser import match


def _stock(
    *,
    instruction_type: InstructionType = InstructionType.SELL,
    ticker: str = "TSLL",
    price: float | None = 27.2,
    price_range: tuple[float, float] | None = None,
    referenced_lot_price: float | None = None,
    sell_quantity: str | None = None,
    position_size: str | None = None,
) -> StockInstruction:
    return StockInstruction(
        instruction_type=instruction_type,
        price=price,
        price_range=price_range,
        quantity=None,
        position_size=position_size,
        stop_loss_price=None,
        take_profit_price=None,
        context_source=None,
        parser_notes=[],
        ticker=ticker,
        symbol=f"{ticker}.US",
        sell_quantity=sell_quantity,
        referenced_lot_price=referenced_lot_price,
    )


def _expected(**overrides) -> dict:
    base = {
        "instruction_type": "SELL",
        "ticker": "TSLL",
        "price": 27.2,
        "price_range": None,
        "referenced_lot_price": None,
        "sell_quantity": None,
        "position_size": None,
    }
    base.update(overrides)
    return base


def test_match_both_none_passes() -> None:
    assert match(None, None) is True


def test_match_one_none_fails() -> None:
    assert match(_stock(), None) is False
    assert match(None, _expected()) is False


def test_match_identical_passes() -> None:
    assert match(_stock(), _expected()) is True


def test_match_different_instruction_type_fails() -> None:
    assert match(_stock(instruction_type=InstructionType.BUY), _expected()) is False


def test_match_different_ticker_fails() -> None:
    assert match(_stock(ticker="HOOD"), _expected()) is False


def test_match_price_within_tolerance_passes() -> None:
    # 0.0009 difference < 0.001 tolerance
    assert match(_stock(price=27.2009), _expected(price=27.2)) is True


def test_match_price_outside_tolerance_fails() -> None:
    assert match(_stock(price=27.21), _expected(price=27.2)) is False


def test_match_price_one_null_fails() -> None:
    # StockInstruction requires price or price_range; supply a range so the
    # domain invariant holds, but expected still has a scalar price — mismatch.
    assert match(_stock(price=None, price_range=(27.0, 27.5)), _expected(price=27.2)) is False


def test_match_price_both_null_passes() -> None:
    assert match(_stock(price=None, price_range=(27.0, 27.5)),
                 _expected(price=None, price_range=[27.0, 27.5])) is True


def test_match_price_range_within_tolerance_passes() -> None:
    assert match(_stock(price=None, price_range=(27.0009, 27.5)),
                 _expected(price=None, price_range=[27.0, 27.5])) is True


def test_match_price_range_outside_tolerance_fails() -> None:
    assert match(_stock(price=None, price_range=(27.1, 27.5)),
                 _expected(price=None, price_range=[27.0, 27.5])) is False


def test_match_referenced_lot_price_compared() -> None:
    assert match(_stock(referenced_lot_price=12.42),
                 _expected(referenced_lot_price=12.42)) is True
    assert match(_stock(referenced_lot_price=12.42),
                 _expected(referenced_lot_price=12.5)) is False


def test_match_sell_quantity_strict() -> None:
    assert match(_stock(sell_quantity="1/2"), _expected(sell_quantity="1/2")) is True
    assert match(_stock(sell_quantity="一半"), _expected(sell_quantity="1/2")) is False


def test_match_position_size_strict() -> None:
    assert match(_stock(position_size="常规仓的一半"),
                 _expected(position_size="常规仓的一半")) is True


def test_match_ticker_case_sensitive_uppercase() -> None:
    """Ticker comes uppercase from _make_stock; expected also uppercase. Match is direct."""
    assert match(_stock(ticker="TSLL"), _expected(ticker="TSLL")) is True
