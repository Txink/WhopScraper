"""Pre-submission parameter completeness gate.

Runs inside the validation node of trader._handle_instruction_ready (after
whitelist + non-today checks). Returns a Chinese reason string when *inst*
lacks the parser-level fields needed to make a sensible order, or None when
the instruction is OK to proceed.

This gate intentionally does NOT check `quantity`:
  - Stock: parser legitimately emits signals with neither quantity nor
    position_size (e.g. "TSLL 26.5 买"). For whitelisted tickers the trader
    resolves qty from page_settings.tickers[ticker].trade_quantity * 1.0
    (default fraction when position_size is None). For orphan stocks the
    trader's existing inst.quantity guard catches the no-qty case.
  - Option: parser never emits quantity; it is fully derived from
    page_settings (option_buy_quantity / option_total_price_limit).

Stock requires: ticker + side (BUY/SELL) + price (or price_range).
Option requires: ticker + side + price + strike + CALL/PUT + expiry.
"""
from __future__ import annotations

from app.domain.instruction import (
    Instruction,
    InstructionType,
    OptionInstruction,
    StockInstruction,
)


def validate_for_submission(inst: Instruction) -> str | None:
    missing: list[str] = []

    if inst.instruction_type not in (InstructionType.BUY, InstructionType.SELL):
        missing.append(f"方向(BUY/SELL,当前: {inst.instruction_type})")
    if inst.price is None and not inst.price_range:
        missing.append("价格")

    if isinstance(inst, StockInstruction):
        if not inst.ticker:
            missing.append("股票名")
        # Note: stock quantity is intentionally not checked — for whitelisted
        # tickers the trader resolves it from page_settings.trade_quantity, and
        # for orphan stocks the trader's existing inst.quantity guard catches
        # the no-qty case.
    elif isinstance(inst, OptionInstruction):
        if not inst.ticker:
            missing.append("股票")
        if not inst.strike or inst.strike <= 0:
            missing.append("行权价")
        if inst.option_type not in ("CALL", "PUT"):
            missing.append("CALL/PUT")
        if not inst.expiry:
            missing.append("到期日")
        # NOTE: no quantity check — option qty is derived from page_settings.

    if missing:
        return "参数不齐: " + "、".join(missing)
    return None
