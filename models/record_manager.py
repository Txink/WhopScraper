"""
Record 管理器：创建 Record、管理 items/discardItems、处理完成后持久化到 origin_message.json
"""
from __future__ import annotations

import json
import os
from typing import List, Optional
from models.message import MessageGroup
from models.record import Record
from models.instruction import OptionInstruction
from parser.message_context_resolver import MessageContextResolver
from parser.stock_context_resolver import StockContextResolver
from utils.watched_stocks import is_watched
from models.stock_instruction import StockInstruction

def _parse_timestamp_for_sort(ts: str) -> str:
    """用于排序的时间戳字符串，保证 YYYY-MM-DD HH:MM:SS.XXX 格式可字符串排序。"""
    if not ts:
        return ""
    # 已是标准格式则直接返回
    if len(ts) >= 23 and ts[4] == "-" and ts[10] == " " and "." in ts:
        return ts
    return ts


def _message_row_from_simple(simple: dict) -> dict:
    """从 monitor 的 simple 字典构建 origin_message 单条格式。"""
    content = simple.get("content", "").strip()
    return {
        "domID": simple.get("domID", simple.get("id", "")),
        "content": content,
        "original_content": simple.get("original_content", content),
        "timestamp": simple.get("timestamp", ""),
        "refer": simple.get("refer"),
        "position": simple.get("position", "middle"),
        "history": list(simple.get("history", [])),
    }


def _message_row_from_message_group(message: MessageGroup) -> dict:
    """从 MessageGroup 构建 origin_message 单条格式。"""

    content = (message.primary_message or "").strip()
    ts = message.timestamp or ""
    return {
        "domID": message.group_id,
        "content": content,
        "timestamp": ts,
        "refer": message.quoted_context if message.quoted_context else None,
        "position": message.get_position(),
        "history": list(message.history or []),
    }


class RecordManager:
    """
    负责：
    1. 创建新的 Record
    2. 管理程序启动后所有创建的 record（items）
    3. Record 处理完毕（message -> instruction -> order）后更新 message 到 data/origin_message.json
       - 无相同 domID
       - 按时间顺序追加/排序
    4. 分析处理失败的 record 放入 discard_items
    """

    def __init__(self, origin_message_path: str = None, page_type: str = "option"):
        if origin_message_path is None:
            origin_message_path = "data/stock_origin_message.json" if page_type == "stock" else "data/origin_message.json"
        self.origin_message_path = origin_message_path
        self.page_type = page_type  # "option" | "stock"
        self.items: List[Record] = []
        self.discard_items: List[Record] = []
        self.current_index: int = 0

    def create_record(self, message: MessageGroup) -> Record:
        """创建新 Record 并加入 items，返回该 Record。"""
        from models.record import Record

        record = Record(message=message)
        record.index = self.current_index
        self.current_index += 1
        self.items.append(record)
        return record

    def create_records(self, messages: List[MessageGroup]) -> List[Record]:
        """创建新 Record 并加入 items，返回该 Record。"""
        records = []
        for message in messages:
            record = self.create_record(message)
            records.append(record)
        return records

    def analyze_records(self, records: List[Record]) -> None:
        """
        对一批 Record 做上下文解析，将解析结果挂载到各 record.instruction。
        按 page_type 选择期权或股票解析器。
        """
        if not records:
            return
        if self.page_type == "stock":
            resolver = StockContextResolver()
            for record in records:
                resolver.resolve_instruction(record)
                # 仅监听关注列表中的股票；列表为空则不过滤
                if record.instruction is not None and isinstance(record.instruction, StockInstruction):
                    if not is_watched(record.instruction.ticker or ""):
                        record.instruction = None
        else:
            resolver = MessageContextResolver(self)
            for record in records:
                resolver.resolve_instruction(record)

    def mark_processed(
        self,
        record: Record,
        simple: Optional[dict] = None,
    ) -> None:
        """
        Record 全链路处理完毕（message -> instruction -> order）后调用。
        将对应 message 写入 origin_message.json：去重 domID、按时间排序。
        simple: 若提供则用其生成持久化行（含清理后的 content）；否则用 record.message 生成。
        """
        if simple is not None:
            row = _message_row_from_simple(simple)
        else:
            row = _message_row_from_message_group(record.message)
        self._append_message_row(row)

    def _append_message_row(self, row: dict) -> None:
        """将一条 message 并入 origin_message.json：无重复 domID，按 timestamp 排序后写回。"""
        dom_id = row.get("domID") or ""
        if not dom_id:
            return
        # 加载已有
        try:
            with open(self.origin_message_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            data = []
        if not isinstance(data, list):
            data = []
        # 按 domID 去重：已有则用新行覆盖（保证同一 domID 只保留一条）
        by_id = {item.get("domID"): item for item in data}
        by_id[dom_id] = row
        merged = list(by_id.values())
        # 按 timestamp 排序
        merged.sort(key=lambda m: _parse_timestamp_for_sort(m.get("timestamp", "")))
        # 写回
        os.makedirs(os.path.dirname(self.origin_message_path) or ".", exist_ok=True)
        with open(self.origin_message_path, "w", encoding="utf-8") as f:
            json.dump(merged, f, ensure_ascii=False, indent=4)
