"""Factory that constructs StockInstruction from slot dict.

Adapted to the real StockInstruction signature (no message_id / raw_text
fields exist on the dataclass — those are routed at higher layers in v1's
flow). Mirrors v1's `stock_parser._make_stock` shape.
"""

from __future__ import annotations

from app.domain.instruction import InstructionType, StockInstruction


def make_stock_instruction(
    *,
    instruction_type: str,
    ticker: str | None,
    symbol: str,
    price: float | None,
    price_range: tuple[float, float] | None,
    referenced_lot_price: float | None,
    sell_quantity: str | None,
    position_size: str | None,
) -> StockInstruction | None:
    """Build a StockInstruction from slot fields. Returns None if required
    fields are missing (no ticker, or no price/range)."""
    if not ticker:
        return None
    if price is None and price_range is None:
        return None
    try:
        return StockInstruction(
            instruction_type=InstructionType(instruction_type),
            price=price,
            price_range=price_range,
            quantity=None,
            position_size=position_size,
            stop_loss_price=None,
            take_profit_price=None,
            context_source=None,
            parser_notes=[],
            referenced_lot_price=referenced_lot_price,
            ticker=ticker,
            symbol=symbol or f"{ticker}.US",
            sell_quantity=sell_quantity,
        )
    except ValueError:
        return None
