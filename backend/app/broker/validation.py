"""Pre-submission parameter completeness gate.

Runs as the FIRST step of trader._handle_instruction_ready, before the
auto_trade decision. Returns a Chinese reason string when *inst* lacks
the parser-level fields needed to make a sensible order, or None when
the instruction is OK to proceed.

This gate intentionally does NOT check `quantity`:
  - Stock: parser typically only emits position_size; concrete qty is
    resolved by trader using page_settings.tickers[ticker].trade_quantity.
  - Option: parser never emits quantity; it is fully derived from
    page_settings (option_buy_quantity / option_total_price_limit).

Stock instead requires either explicit `quantity > 0` OR a non-empty
`position_size` — evidence that the user expressed *some* quantity
intent. Option only requires the per-option-contract specifics; qty
resolution stays the trader's job.
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
        has_qty = inst.quantity is not None and inst.quantity > 0
        has_size = bool(inst.position_size)
        if not has_qty and not has_size:
            missing.append("数量(qty 或 position_size)")
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
