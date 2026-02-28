"""
股票（正股）交易指令数据模型
"""
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from rich.console import Console

from models.instruction import OperationInstruction, InstructionType


@dataclass
class StockInstruction(OperationInstruction):
    """股票交易指令数据模型"""

    ticker: Optional[str] = None
    symbol: Optional[str] = None  # 正股代码，如 AAPL.US

    # 解析出的具体数量（股数）。买入时可由 position_size 换算；卖出时可由 stock_trade_records 根据参考价/日期换算。
    quantity: Optional[int] = None

    # 卖出时：按“某次买入”的那部分出。
    sell_reference_price: Optional[float] = None   # 出 X 买入的那部分 -> 参考买入价 X
    sell_reference_label: Optional[str] = None    # 如 "昨天16.02的" "15.48那部分"
    # 买入时：数量按历史参考（如“加回周五卖出的那部分”“吸回今天卖出的”）。
    buy_quantity_reference: Optional[str] = None  # 如 "周五卖出的" "今天卖出的" "卖出的一部分"

    def has_symbol(self) -> bool:
        """有 ticker 或 symbol 即视为具备标的信息。"""
        return bool((self.ticker or "").strip()) or bool((self.symbol or "").strip())

    def ensure_symbol(self) -> None:
        """若无 symbol 则根据 ticker 生成（如 AAPL -> AAPL.US）。"""
        if self.symbol:
            return
        if (self.ticker or "").strip():
            self.symbol = f"{self.ticker.strip().upper()}.US"

    @staticmethod
    def display_parse_failed(message_timestamp: Optional[str] = None) -> None:
        """解析失败时展示（股票页：ticker = X）。"""
        OperationInstruction.display_parse_failed(message_timestamp, symbol_label="ticker")

    def display(self) -> None:
        from utils.rich_logger import get_logger
        logger = get_logger()
        sym = self.symbol or (f"{self.ticker}.US" if self.ticker else "")

        summary_parts = [f"[green]\\[{self.instruction_type}][/green]", f"[bold blue]{sym or self.ticker or '-'}[/bold blue]"]
        if self.price is not None:
            summary_parts.append(f"${self.price}")
        elif self.price_range:
            summary_parts.append(f"${self.price_range[0]}-${self.price_range[1]}")
        if self.quantity is not None:
            summary_parts.append(f"x{self.quantity}股")

        rows = [("", " ".join(summary_parts))]

        if self.price_range and self.price is not None:
            rows.append(("price_range", f"${self.price_range[0]} - ${self.price_range[1]}"))
        if self.instruction_type == InstructionType.BUY.value and self.position_size:
            rows.append(("position_size", str(self.position_size)))
        elif self.instruction_type == InstructionType.SELL.value and self.sell_quantity:
            rows.append(("sell_quantity", str(self.sell_quantity)))
        elif self.instruction_type == InstructionType.CLOSE.value:
            rows.append(("quantity", "全部"))
        elif self.instruction_type == InstructionType.MODIFY.value:
            if self.stop_loss_price is not None:
                rows.append(("stop_loss", f"${self.stop_loss_price}"))
            if self.take_profit_price is not None:
                rows.append(("take_profit", f"${self.take_profit_price}"))

        if self.source:
            rows.append(("source", str(self.source)))

        logger.trade_stage("解析消息", rows=rows, tag_style="bold blue")

    def __str__(self) -> str:
        ticker = self.ticker or "未识别"
        if self.instruction_type == InstructionType.BUY.value:
            if self.price_range:
                price_str = f"${self.price_range[0]}-${self.price_range[1]}"
            else:
                price_str = f"${self.price}" if self.price else "市价"
            return f"[买入] {ticker} @ {price_str} {self.position_size or ''}".strip()
        elif self.instruction_type == InstructionType.SELL.value:
            if self.price_range:
                price_str = f"${self.price_range[0]}-${self.price_range[1]}"
            else:
                price_str = f"${self.price}" if self.price else "市价"
            q = f" 数量: {self.sell_quantity}" if self.sell_quantity else ""
            ref = f" 参考买入价:{self.sell_reference_price}" if self.sell_reference_price is not None else ""
            return f"[卖出] {ticker} @ {price_str}{q}{ref}".strip()
        elif self.instruction_type == InstructionType.CLOSE.value:
            if self.price_range:
                price_str = f"${self.price_range[0]}-${self.price_range[1]}"
            else:
                price_str = f"${self.price}" if self.price else "市价"
            return f"[清仓] {ticker} @ {price_str}"
        elif self.instruction_type == InstructionType.MODIFY.value:
            parts = [f"[修改] {ticker}"]
            if self.stop_loss_range:
                parts.append(f"止损: ${self.stop_loss_range[0]}-${self.stop_loss_range[1]}")
            elif self.stop_loss_price:
                parts.append(f"止损: ${self.stop_loss_price}")
            if self.take_profit_range:
                parts.append(f"止盈: ${self.take_profit_range[0]}-${self.take_profit_range[1]}")
            elif self.take_profit_price:
                parts.append(f"止盈: ${self.take_profit_price}")
            return " ".join(parts)
        return f"[未识别] {self.raw_message[:50]}..."
