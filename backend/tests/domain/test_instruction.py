from datetime import date

import pytest

from app.domain.instruction import (
    InstructionType,
    OptionInstruction,
    StockInstruction,
)


def test_stock_instruction_basic():
    inst = StockInstruction(
        instruction_type=InstructionType.BUY,
        price=26.50,
        price_range=None,
        quantity=500,
        position_size=None,
        stop_loss_price=25.80,
        take_profit_price=None,
        context_source="group",
        parser_notes=[],
        ticker="TSLL",
        symbol="TSLL.US",
        sell_quantity=None,
    )
    assert inst.ticker == "TSLL"
    assert inst.symbol == "TSLL.US"
    assert inst.instruction_type == InstructionType.BUY


def test_option_instruction_basic():
    inst = OptionInstruction(
        instruction_type=InstructionType.BUY,
        price=2.15,
        price_range=None,
        quantity=2,
        position_size="小仓位",
        stop_loss_price=None,
        take_profit_price=None,
        context_source="refer",
        parser_notes=[],
        ticker="NVDA",
        option_type="CALL",
        strike=135.0,
        expiry=date(2026, 4, 26),
        symbol="NVDA 250426C135.US",
    )
    assert inst.strike == 135.0
    assert inst.option_type == "CALL"


def test_option_invalid_type_rejected():
    with pytest.raises(ValueError):
        OptionInstruction(
            instruction_type=InstructionType.BUY,
            price=1.0,
            price_range=None,
            quantity=1,
            position_size=None,
            stop_loss_price=None,
            take_profit_price=None,
            context_source=None,
            parser_notes=[],
            ticker="AAPL",
            option_type="STRADDLE",  # type: ignore[arg-type]
            strike=200.0,
            expiry=date(2026, 5, 3),
            symbol="AAPL ...",
        )


def test_price_or_price_range_required():
    """至少需要 price 或 price_range 之一。"""
    with pytest.raises(ValueError):
        StockInstruction(
            instruction_type=InstructionType.BUY,
            price=None,
            price_range=None,
            quantity=100,
            position_size=None,
            stop_loss_price=None,
            take_profit_price=None,
            context_source=None,
            parser_notes=[],
            ticker="TSLL",
            symbol="TSLL.US",
            sell_quantity=None,
        )
