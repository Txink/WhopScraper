"""validate_parser — diff stock parser outputs against parser_golden.json.

Public surface:
  - match(out, expected) -> bool          — single-message comparator
  - run_validation(...) -> ValidationResult — full harness over corpus + golden
  - main()                                — CLI entrypoint

run_validation and CLI are added in later tasks of this plan; this file
starts with the matcher only.

Match semantics — see spec section 6.3:
  strict equality:    instruction_type, ticker, sell_quantity, position_size
  ±0.001 tolerance:   price, referenced_lot_price, price_range (both ends)
  ignored:            parser_notes, context_source, symbol, quantity,
                      raw_message, message_id, stop_loss_price, take_profit_price
"""

from __future__ import annotations

from typing import Any

from app.domain.instruction import StockInstruction

PRICE_TOLERANCE = 0.001


def _float_eq(a: float | None, b: float | None, tol: float = PRICE_TOLERANCE) -> bool:
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    return abs(a - b) <= tol


def _range_eq(
    a: tuple[float, float] | None,
    b: list[float] | tuple[float, float] | None,
    tol: float = PRICE_TOLERANCE,
) -> bool:
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    return _float_eq(a[0], b[0], tol) and _float_eq(a[1], b[1], tol)


def match(out: StockInstruction | None, expected: dict[str, Any] | None) -> bool:
    """Return True iff parser output matches the golden expected dict.

    None on either side: must both be None to match. Non-None on both sides:
    compare 7 load-bearing fields per spec 6.3 rules.
    """
    if out is None and expected is None:
        return True
    if out is None or expected is None:
        return False

    if out.instruction_type.name != expected["instruction_type"]:
        return False
    if out.ticker.upper() != expected["ticker"]:
        return False
    if not _float_eq(out.price, expected["price"]):
        return False
    if not _range_eq(out.price_range, expected["price_range"]):
        return False
    if not _float_eq(out.referenced_lot_price, expected["referenced_lot_price"]):
        return False
    if (out.sell_quantity or None) != (expected["sell_quantity"] or None):
        return False
    if (out.position_size or None) != (expected["position_size"] or None):
        return False
    return True
