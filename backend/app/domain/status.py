"""Status 状态机 —— Task 生命周期，合法转换显式列表维护。"""
from __future__ import annotations

from enum import StrEnum


class Status(StrEnum):
    RECEIVED = "RECEIVED"
    PARSING = "PARSING"
    PARSE_ERROR = "PARSE_ERROR"
    INSTRUCTION_READY = "INSTRUCTION_READY"
    SUBMITTING = "SUBMITTING"
    SUBMIT_FAILED = "SUBMIT_FAILED"
    PENDING = "PENDING"
    PARTIAL = "PARTIAL"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    SKIPPED = "SKIPPED"


TERMINAL: frozenset[Status] = frozenset(
    {
        Status.PARSE_ERROR,
        Status.SUBMIT_FAILED,
        Status.FILLED,
        Status.CANCELLED,
        Status.REJECTED,
        Status.SKIPPED,
    }
)


# 合法转换表：src -> 允许的 dst 集合
_ALLOWED: dict[Status, frozenset[Status]] = {
    Status.RECEIVED: frozenset({Status.PARSING}),
    Status.PARSING: frozenset({Status.PARSE_ERROR, Status.INSTRUCTION_READY}),
    Status.INSTRUCTION_READY: frozenset({Status.SUBMITTING, Status.SKIPPED}),
    Status.SUBMITTING: frozenset({Status.PENDING, Status.SUBMIT_FAILED, Status.SKIPPED}),
    Status.PENDING: frozenset(
        {Status.PARTIAL, Status.FILLED, Status.CANCELLED, Status.REJECTED}
    ),
    Status.PARTIAL: frozenset({Status.PARTIAL, Status.FILLED, Status.CANCELLED}),
    # 终态不可转出
    Status.PARSE_ERROR: frozenset(),
    Status.SUBMIT_FAILED: frozenset(),
    Status.FILLED: frozenset(),
    Status.CANCELLED: frozenset(),
    Status.REJECTED: frozenset(),
    Status.SKIPPED: frozenset(),
}


def can_transition(src: Status, dst: Status) -> bool:
    return dst in _ALLOWED.get(src, frozenset())


def next_status(src: Status, dst: Status) -> Status:
    if not can_transition(src, dst):
        raise ValueError(f"illegal transition: {src} -> {dst}")
    return dst
