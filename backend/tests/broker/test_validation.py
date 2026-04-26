"""Tests for app.broker.validation.validate_for_submission."""
from __future__ import annotations

from datetime import date

from app.domain.instruction import (
    InstructionType,
    OptionInstruction,
    StockInstruction,
)
from app.broker.validation import validate_for_submission


def _stock(**overrides) -> StockInstruction:
    base = dict(
        instruction_type=InstructionType.BUY,
        price=26.5, price_range=None,
        quantity=100, position_size=None,
        stop_loss_price=None, take_profit_price=None,
        context_source=None, parser_notes=[],
        ticker="TSLL", symbol="TSLL.US", sell_quantity=None,
    )
    base.update(overrides)
    return StockInstruction(**base)


def _option(**overrides) -> OptionInstruction:
    base = dict(
        instruction_type=InstructionType.BUY,
        price=2.15, price_range=None,
        quantity=2, position_size=None,
        stop_loss_price=None, take_profit_price=None,
        context_source=None, parser_notes=[],
        ticker="NVDA", option_type="CALL",
        strike=135.0, expiry=date(2026, 4, 26),
        symbol="NVDA260426C135000.US",
    )
    base.update(overrides)
    return OptionInstruction(**base)


# ---------- happy paths ----------

def test_stock_complete_with_quantity_returns_none():
    assert validate_for_submission(_stock()) is None


def test_stock_complete_with_position_size_returns_none():
    inst = _stock(quantity=None, position_size="常规仓的一半")
    assert validate_for_submission(inst) is None


def test_stock_no_quantity_no_position_size_returns_none():
    """Stock parser legitimately emits signals with neither quantity nor
    position_size (e.g. 'TSLL 26.5 买'). The validation gate must accept
    them — qty resolves later from page_settings.trade_quantity."""
    inst = _stock(quantity=None, position_size=None)
    assert validate_for_submission(inst) is None


def test_option_complete_returns_none():
    assert validate_for_submission(_option()) is None


def test_option_complete_without_quantity_returns_none():
    """Option qty is always derived from page_settings; parser-stage qty=None
    is the normal case and must NOT be flagged."""
    assert validate_for_submission(_option(quantity=None)) is None


def test_stock_with_price_range_only_returns_none():
    assert validate_for_submission(_stock(price=None, price_range=(26.0, 27.0))) is None


# ---------- stock missing fields ----------

def test_stock_close_instruction_type_rejected():
    reason = validate_for_submission(_stock(instruction_type=InstructionType.CLOSE))
    assert reason is not None
    assert "BUY" in reason and "SELL" in reason


def test_stock_modify_instruction_type_rejected():
    reason = validate_for_submission(_stock(instruction_type=InstructionType.MODIFY))
    assert reason is not None
    assert "BUY" in reason and "SELL" in reason


# ---------- option missing fields ----------

def test_option_zero_strike():
    reason = validate_for_submission(_option(strike=0))
    assert reason is not None
    assert "行权价" in reason


def test_option_no_expiry_falsy():
    inst = _option()
    inst.expiry = None  # type: ignore[assignment]
    reason = validate_for_submission(inst)
    assert reason is not None
    assert "到期日" in reason


def test_option_invalid_type_rejected():
    inst = _option()
    inst.option_type = "UNKNOWN"  # type: ignore[assignment]
    reason = validate_for_submission(inst)
    assert reason is not None
    assert "CALL/PUT" in reason


def test_option_close_instruction_type_rejected():
    reason = validate_for_submission(_option(instruction_type=InstructionType.CLOSE))
    assert reason is not None
    assert "BUY" in reason and "SELL" in reason


# ---------- error string format ----------

def test_reason_starts_with_zh_prefix():
    reason = validate_for_submission(_stock(instruction_type=InstructionType.CLOSE))
    assert reason is not None
    assert reason.startswith("参数不齐: ")


def test_reason_lists_multiple_missing_fields():
    """Multiple missing fields produce a reason joined by 、 separator.
    Uses an OptionInstruction with CLOSE side + zero strike + no expiry to
    trigger three distinct failures and verify 、-joining."""
    inst = _option(
        instruction_type=InstructionType.CLOSE,
        strike=0,
    )
    inst.expiry = None  # type: ignore[assignment]
    reason = validate_for_submission(inst)
    assert reason is not None
    assert "BUY" in reason and "SELL" in reason
    assert "行权价" in reason
    assert "到期日" in reason
    assert "、" in reason
