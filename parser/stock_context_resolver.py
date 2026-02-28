"""
股票消息上下文解析器
对单条消息调用 StockParser，解析后填充分辨出的具体股数（quantity）。
"""
from typing import Optional
from models.instruction import InstructionType
from models.record import Record
from models.stock_instruction import StockInstruction
from parser.stock_parser import StockParser
from utils.watched_stocks import resolve_position_size_to_shares
from utils.stock_trade_records import resolve_sell_quantity_from_records


class StockContextResolver:
    """股票页专用：解析消息为 StockInstruction，并解析出具体数量（股数）。"""

    def resolve_instruction(self, record: Record) -> None:
        """
        解析消息并挂载到 record.instruction。
        买入：若 position_size 为「常规一半」等，换算为具体股数写入 quantity。
        卖出：若 sell_reference_price / sell_reference_label 存在，从 stock_trade_records 解析卖出股数写入 quantity。
        """
        content = (record.content or "").strip()
        if not content or len(content) < 2:
            return

        instruction = StockParser.parse(
            content,
            message_id=record.message.group_id,
            message_timestamp=getattr(record.message, "timestamp", None),
        )
        if not instruction:
            return

        instruction.origin = record.message
        if getattr(record.message, "timestamp", None):
            instruction.timestamp = record.message.timestamp
        instruction.ensure_symbol()

        # 买入：根据 position_size 换算为具体股数
        if instruction.instruction_type == InstructionType.BUY.value and instruction.position_size and instruction.ticker:
            shares = resolve_position_size_to_shares(instruction.position_size, ticker=instruction.ticker)
            if shares is not None:
                instruction.quantity = shares
            # buy_quantity_reference（周五卖出的、今天卖出的）由执行层根据 stock_trade_records 解析数量

        # 卖出：根据 sell_reference_* 从 stock_trade_records 解析卖出股数
        if instruction.instruction_type == InstructionType.SELL.value and instruction.ticker:
            if instruction.sell_reference_price is not None or instruction.sell_reference_label:
                qty = resolve_sell_quantity_from_records(
                    ticker=instruction.ticker,
                    reference_price=instruction.sell_reference_price,
                    reference_label=instruction.sell_reference_label,
                    sell_quantity_ratio=instruction.sell_quantity,
                )
                if qty is not None:
                    instruction.quantity = qty

        record.instruction = instruction
