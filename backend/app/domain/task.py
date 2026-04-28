"""Task 聚合根 —— 一条消息 → 一个 Task，贯穿整个处理生命周期。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal

from .instruction import Instruction, OptionInstruction, StockInstruction
from .message import Message
from .push_event import PushEvent, PushState
from .status import Status, next_status

# PushState → Status 映射
_PUSH_TO_STATUS: dict[PushState, Status] = {
    PushState.NEW: Status.PENDING,
    PushState.SUBMITTED: Status.PENDING,
    PushState.MODIFIED: Status.PENDING,
    PushState.PARTIAL: Status.PARTIAL,
    PushState.FILLED: Status.FILLED,
    PushState.CANCELLED: Status.CANCELLED,
    PushState.REJECTED: Status.REJECTED,
    PushState.FAILED: Status.REJECTED,
}


@dataclass
class Task:
    id: str
    type: Literal["stock", "option", "unknown"]
    status: Status
    message: Message
    instruction: Instruction | None = None
    order_id: str | None = None
    push_events: list[PushEvent] = field(default_factory=list)
    stage_timings: dict[str, float] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    reject_reason: str | None = None
    is_historical: bool = False
    #: ``LIMIT`` / ``MARKET`` — set when auto-trade submits (before ``TASK_ORDER_SUBMITTED``).
    submit_order_type: str | None = None
    #: Human-readable reason (CN) for UI: quote vs signal price rule.
    submit_order_context: str | None = None

    @classmethod
    def new_from_message(cls, msg: Message, *, is_historical: bool = False) -> Task:
        now = datetime.now(UTC)
        return cls(
            id=msg.id,
            type="unknown",
            status=Status.RECEIVED,
            message=msg,
            created_at=now,
            updated_at=now,
            is_historical=is_historical,
        )

    def _transition(self, dst: Status) -> None:
        self.status = next_status(self.status, dst)
        self.updated_at = datetime.now(UTC)

    def mark_parsing(self) -> None:
        self._transition(Status.PARSING)

    def mark_parse_failed(self, reason: str) -> None:
        self.reject_reason = reason
        self._transition(Status.PARSE_ERROR)

    def attach_instruction(self, inst: Instruction) -> None:
        self.instruction = inst
        if isinstance(inst, OptionInstruction):
            self.type = "option"
        elif isinstance(inst, StockInstruction):
            self.type = "stock"
        else:
            self.type = "unknown"
        self._transition(Status.INSTRUCTION_READY)

    def mark_submitting(self) -> None:
        self._transition(Status.SUBMITTING)

    def mark_submitted(self, *, order_id: str, timing_ms: float) -> None:
        self.order_id = order_id
        self.stage_timings["submit"] = timing_ms
        self._transition(Status.PENDING)

    def mark_submit_failed(self, reason: str) -> None:
        self.reject_reason = reason
        self._transition(Status.SUBMIT_FAILED)

    def mark_skipped(self, reason: str) -> None:
        self.reject_reason = reason
        self._transition(Status.SKIPPED)

    def record_parse_timing(self, ms: float) -> None:
        self.stage_timings["parse"] = ms

    def append_push_event(self, evt: PushEvent) -> None:
        self.push_events.append(evt)
        new_status = _PUSH_TO_STATUS[evt.state]
        # PARTIAL → PARTIAL 允许（状态机中已标记）
        if self.status != new_status:
            self._transition(new_status)
        else:
            self.updated_at = datetime.now(UTC)
