"""Instruction —— 从 Message 解析出的交易指令。Stock 和 Option 两个具体子类。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum
from typing import Literal


class InstructionType(StrEnum):
    BUY = "BUY"
    SELL = "SELL"
    CLOSE = "CLOSE"
    MODIFY = "MODIFY"


ContextSource = Literal["group", "refer", "recent", "positions", "watchlist"]
OptionSide = Literal["CALL", "PUT"]


@dataclass
class Instruction:
    instruction_type: InstructionType
    price: float | None
    price_range: tuple[float, float] | None
    quantity: int | None
    position_size: str | None
    stop_loss_price: float | None
    take_profit_price: float | None
    context_source: ContextSource | None
    parser_notes: list[str] = field(default_factory=list)
    referenced_lot_price: float | None = None

    def __post_init__(self) -> None:
        if self.price is None and self.price_range is None:
            raise ValueError("Instruction 必须有 price 或 price_range")


@dataclass
class StockInstruction(Instruction):
    ticker: str = ""
    symbol: str = ""
    sell_quantity: str | None = None

    def __post_init__(self) -> None:
        super().__post_init__()
        if not self.ticker:
            raise ValueError("StockInstruction.ticker 必填")


@dataclass
class OptionInstruction(Instruction):
    ticker: str = ""
    option_type: OptionSide = "CALL"
    strike: float = 0.0
    expiry: date = field(default_factory=lambda: date.today())
    symbol: str = ""

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.option_type not in ("CALL", "PUT"):
            raise ValueError(f"invalid option_type: {self.option_type}")
        if not self.ticker:
            raise ValueError("OptionInstruction.ticker 必填")
