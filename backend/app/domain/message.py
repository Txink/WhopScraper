"""Message —— 来自 Whop 的单条消息，id 为 whop domID，也是后续 Task 的唯一标识。"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

Source = Literal["stock", "option"]


@dataclass(frozen=True)
class Message:
    id: str
    content: str
    raw_content: str
    author: str | None
    posted_at: datetime
    received_at: datetime
    source: Source
    quoted: Message | None = None
    history_hint: list[Message] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.source not in ("stock", "option"):
            raise ValueError(f"invalid source: {self.source}")

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Message):
            return NotImplemented
        return self.id == other.id

    def __hash__(self) -> int:
        return hash(self.id)
