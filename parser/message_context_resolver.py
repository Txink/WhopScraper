"""
消息上下文解析器
利用消息的 history、refer 字段和全局消息列表来补全期权指令中缺失的信息
解析时统一将到期日转为 YYMMDD，并在信息完整时生成期权代码 symbol。
兜底：仅有 ticker（如「tsla 卖出 1/3」）且无历史/引用可用时，从持仓文件补全 symbol。
"""
import os
import json
import logging
from typing import Optional, List, Dict, Tuple, TYPE_CHECKING
from parser.option_parser import OptionParser
from models.instruction import OptionInstruction, InstructionType
from models.record import Record

if TYPE_CHECKING:
    from models.record_manager import RecordManager

logger = logging.getLogger(__name__)

class MessageContextResolver:
    """
    消息上下文解析器
    负责利用历史消息、引用消息补全期权指令的缺失信息。
    传入 RecordManager 与当前要解析的 Record 数组，根据 record.index 从 items 往前找历史。
    """

    def __init__(self, record_manager: "RecordManager"):
        """
        初始化解析器。

        Args:
            record_manager: RecordManager 实例，从中按 index 往前查历史 record
        """
        self.record_manager = record_manager
        self.context_search_limit = int(os.getenv("CONTEXT_SEARCH_LIMIT", "10"))

    def resolve_instruction(self, record: Record) -> None:
        """
        解析消息并补全上下文，结果写入 record.instruction。
        历史消息从 self.record_manager.items 按 record.index 往前查找。
        直接使用 record / record.message 访问消息属性，不转为 dict。
        """
        content = record.content.strip()
        timestamp = record.message.timestamp
        if not content or len(content) < 2:
            return

        instruction = OptionParser.parse(
            content,
            message_id=record.message.group_id,
            message_timestamp=timestamp,
        )

        if not instruction:
            return
        
        instruction.origin = record.message
        # 使用 origin 消息的 timestamp，与 data/check.json 校验一致
        if getattr(record.message, "timestamp", None):
            instruction.timestamp = record.message.timestamp
        record.instruction = instruction
        # 单消息解析symbol成功则直接返回
        if instruction.generate_symbol():
            return

        found_inst = self._find_context(record)
        if not found_inst:
            # 兜底：仅有 ticker、无历史/引用时，从持仓中取 symbol（如「tsla 卖出 1/3」）
            self._resolve_symbol_from_positions(record)
            return
        record.instruction.sync_with_instruction(found_inst)
        record.instruction.generate_symbol()

    def _find_context(self, record: Record) -> Optional[OptionInstruction]:
        """
        按顺序查找可辅助补全的 instruction：
        1. 同组（group）中的 record 的 instruction
        2. refer 解析出的 instruction
        3. 当前 record 之前 N 条的 instruction
        4. 若仍无结果，由 resolve_instruction 内调用 _resolve_symbol_from_positions 做兜底
        返回的 instruction 上已设置 source、depend_message。
        """
        inst = self._search_in_history(record, limit=self.context_search_limit, scope="group")
        if inst:
            record.instruction.source = "history"
            record.instruction.depend_message = inst.origin.primary_message or ""
            return inst
        refer = record.message.quoted_context
        if refer:
            inst = self._search_in_refer(record)
            if inst:
                record.instruction.source = "refer"
                record.instruction.depend_message = refer
                return inst
        inst = self._search_in_history(record, limit=self.context_search_limit, scope="recent")
        if inst:
            record.instruction.source = "recent"
            record.instruction.depend_message = inst.origin.primary_message or ""
            return inst
        return None

    def _resolve_symbol_from_positions(self, record: Record) -> None:
        """
        兜底：当仅有 ticker（如「tsla 卖出 1/3」）、无历史/引用可补全时，从持仓文件中
        按 ticker 匹配该标的的持仓；若仅有一条则用其 symbol 补全，多条则取第一条。
        仅对 SELL/CLOSE/MODIFY 且当前无 symbol、有 ticker 时生效。
        """
        inst = record.instruction
        if not inst or inst.instruction_type not in (
            InstructionType.SELL.value,
            InstructionType.CLOSE.value,
            InstructionType.MODIFY.value,
        ):
            return
        if inst.has_symbol() or not (inst.ticker or "").strip():
            return
        ticker = (inst.ticker or "").strip().upper()
        path = os.getenv("POSITIONS_JSON_PATH", "data/positions.json")
        if not os.path.isfile(path):
            logger.debug("持仓文件不存在，跳过持仓兜底: %s", path)
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            logger.warning("读取持仓文件失败: %s", e)
            return
        if not isinstance(data, dict):
            return
        # 匹配该 ticker 的持仓：symbol 以 ticker 开头，或条目内 ticker 字段一致
        matches = []
        for sym, pos in data.items():
            if not isinstance(pos, dict):
                continue
            pos_ticker = (pos.get("ticker") or "").strip().upper()
            if pos_ticker == ticker or (sym.startswith(ticker) and sym.endswith(".US")):
                matches.append(sym)
        if not matches:
            logger.debug("持仓中无 ticker=%s 的标的，跳过兜底", ticker)
            return
        # 仅一条则用；多条取第一条（兜底语义）
        chosen = matches[0]
        if len(matches) > 1:
            logger.info("持仓中 ticker=%s 有多条，兜底使用: %s", ticker, chosen)
        inst.symbol = chosen
        inst.source = "positions"
        inst.depend_message = "持仓"

    def _can_reuse_symbol_from(
        self, current_inst: OptionInstruction, prev_inst: OptionInstruction
    ) -> bool:
        """
        当前指令（SELL/CLOSE/MODIFY）是否可复用前一条的 symbol。
        - 当前有 ticker：前一条需 ticker 相同且具备完整 symbol。
        - 当前无 ticker：前一条需为 BUY/MODIFY/SELL 且具备完整 symbol。
        """
        if not prev_inst.has_symbol():
            return False
        if current_inst.ticker:
            return (
                prev_inst.ticker is not None
                and prev_inst.ticker.upper() == current_inst.ticker.upper()
            )
        return prev_inst.instruction_type in (
            InstructionType.BUY.value,
            InstructionType.MODIFY.value,
            InstructionType.SELL.value,
        )

    def _search_in_history(
        self,
        record: Record,
        limit: int,
        scope: str = "group",
    ) -> Optional[OptionInstruction]:
        """
        当自身消息无法提供完整 symbol 时（SELL/CLOSE/MODIFY），向前查找可复用 symbol 的 instruction。
        两种范围用 scope 区分，校验规则相同（_can_reuse_symbol_from）：
        - scope="group"：仅当 position=middle|last 时有效，从 record.index-1 向前遍历，到 position=first 结束。
        - scope="recent"：从 record.index-1 向前最多遍历 limit 条 record。
        会更新 record.checkedIndex；返回的 instruction 会设置 source、depend_message。
        """
        current_inst = record.instruction
        if not current_inst or current_inst.instruction_type not in (
            InstructionType.SELL.value,
            InstructionType.CLOSE.value,
            InstructionType.MODIFY.value,
        ):
            return None
        if current_inst.has_symbol():
            return None
        if scope == "group":
            position = record.message.get_position()
            if position in ("single", "first"):
                return None

        if not self.record_manager or not self.record_manager.items:
            return None
        items = self.record_manager.items
        start_i = (
            (record.checkedIndex - 1)
            if record.checkedIndex is not None
            else (record.index - 1)
        )
        if start_i < 0:
            return None
        checked_min = start_i + 1
        # scope=recent 时只查相对 record.index 的前 limit 条（下标 >= record.index - limit）
        min_i = max(0, record.index - limit) if scope == "recent" else 0
        if scope == "recent" and start_i < min_i:
            # start_i 已在 min_i 之前，说明前 limit 条都已校验过，无需再遍历
            return None
        for i in range(start_i, min_i - 1, -1):
            if i >= len(items):
                continue
            r = items[i]
            prev_inst = r.instruction
            if prev_inst and self._can_reuse_symbol_from(current_inst, prev_inst):
                record.checkedIndex = min(checked_min, i)
                return prev_inst
            checked_min = min(checked_min, i)
            pos = r.message.get_position()
            if scope == "group":
                if pos == "first":
                    record.checkedIndex = min(checked_min, i)
                    return None
                if pos == "single":
                    record.checkedIndex = min(checked_min, i)
                    return None
        record.checkedIndex = min(checked_min, start_i) if start_i >= 0 else checked_min
        return None
    
    def _search_in_refer(self, record: Record) -> Optional[OptionInstruction]:
        """
        从当前 record 的引用内容（refer）解析出可辅助补全的 instruction。
        使用 record.message.quoted_context 作为 refer，ticker / timestamp 从 record 取。
        仅当解析结果为 BUY 且具备 ticker、strike 等完整信息时返回，否则返回 None。
        """
        refer = record.message.quoted_context
        if not refer:
            return None
        ticker = record.instruction.ticker if record.instruction else None
        message_timestamp = record.message.timestamp
        instruction = OptionParser.parse(refer, message_timestamp=message_timestamp)
        if not instruction:
            return None
        if instruction.instruction_type != InstructionType.BUY.value:
            return None
        if ticker and instruction.ticker and instruction.ticker.upper() != ticker.upper():
            return None
        if instruction.ticker and instruction.strike:
            return instruction
        return None

    @classmethod
    def from_messages(cls, all_messages: List[dict]) -> "MessageContextResolver":
        """
        从消息列表构造解析器（无 RecordManager 时使用，如测试、离线脚本）。
        内部用临时对象模拟 record_manager + 按 index 查找。
        """
        return _ResolverFromMessages(all_messages)


class _ResolverFromMessages(MessageContextResolver):
    """仅从消息列表构造的解析器（无 RecordManager），用于测试、离线脚本。"""

    def __init__(self, all_messages: List[dict]):
        self.record_manager = None
        self.records = []
        self._all_messages = all_messages
        self._message_index = {
            msg["domID"]: idx for idx, msg in enumerate(all_messages)
        }
        self.context_search_limit = int(os.getenv("CONTEXT_SEARCH_LIMIT", "10"))
