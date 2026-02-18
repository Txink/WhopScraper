"""
单条消息记录模型：原始消息 + 解析后的指令
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, Optional
from models.message import MessageGroup
from models.instruction import OptionInstruction


def _clean_content(content: str) -> str:
    """清理消息内容：去掉引用前缀、时间戳行、占位符等。"""
    s = content.strip()
    s = re.sub(r'^\[引用\]\s*', '', s)
    s = re.sub(r'^[\w]+•[A-Z][a-z]{2,9}\s+\d{1,2},\s+\d{4}\s+\d{1,2}:\d{2}\s+[AP]M\s*', '', s)
    # 仅当开头是单独 X（后接非字母或结尾）时移除头像占位，保留 "XOM" 等 ticker
    s = re.sub(r'^[XxＸｘ]+\s*(?=[^A-Za-z]|$)', '', s)
    s = re.sub(r'^[\w]+•[A-Z][a-z]{2,9}\s+\d{1,2},\s+\d{4}\s+\d{1,2}:\d{2}\s+[AP]M\s*', '', s)
    s = re.sub(r'^•?\s*[A-Z][a-z]+\s+\d{1,2}:\d{2}\s+[AP]M\s*', '', s)
    return s.strip()


@dataclass
class Record:
    """
    单条消息的完整记录：原始消息 + 解析后的指令。
    监听到新消息时创建，将 MessageGroup 挂载到 message，
    经上下文解析器处理后把 OptionInstruction 挂载到 instruction。
    """
    message: MessageGroup
    instruction: Optional[OptionInstruction] = None
    index: Optional[int] = None  # 在列表中的下标，可由外部设置
    checkedIndex: Optional[int] = None  # 已检查过的下标，用于避免重复检查

    def __init__(self, message):
        self.message = message
        self.instruction = None
        self.index = None
        self.checkedIndex = None
        self.content = _clean_content(message.primary_message)

    def getDomID(self) -> str:
        return self.message.group_id

    @property
    def simple_dict(self) -> Dict:
        """供解析器使用的简化字典（content 已清理），等价于 message.to_dict() 并做内容清理。"""
        d = self.message.to_dict()
        d["content"] = _clean_content(d.get("content", "") or "")
        return d