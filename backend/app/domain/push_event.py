"""PushEvent —— 来自 broker 的订单推送事件流式记录。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class PushState(StrEnum):
    NEW = "NEW"
    SUBMITTED = "SUBMITTED"
    MODIFIED = "MODIFIED"
    PARTIAL = "PARTIAL"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    FAILED = "FAILED"


@dataclass(frozen=True)
class PushEvent:
    id: str
    task_id: str
    order_id: str
    state: PushState
    received_at: datetime
    payload: dict[str, object]
    delta_qty: int | None = None
    delta_price: float | None = None
    cumulative_qty: int | None = None
    cumulative_avg_price: float | None = None
    note: str | None = None

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, PushEvent):
            return NotImplemented
        return self.id == other.id

    def __hash__(self) -> int:
        return hash(self.id)
