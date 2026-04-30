"""PushEvent —— 来自 broker 的订单推送事件流式记录。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class PushState(StrEnum):
    """Broker-faithful order push state.

    Values match LongPort SDK ``OrderStatus`` labels so the UI can show
    each state transition the broker actually reports (e.g. ``WaitToNew``
    → ``New`` → ``Filled``) instead of collapsing them all into a single
    ``NEW`` bucket.

    ``FAILED`` is kept as an internal sentinel for unmapped SDK statuses.
    """

    # Pre-exchange (broker received, awaiting routing/exchange acceptance)
    WAIT_TO_NEW = "WaitToNew"
    NOT_REPORTED = "NotReported"
    WAIT_TO_REPLACE = "WaitToReplace"
    PENDING_REPLACE = "PendingReplace"
    REPLACED_NOT_REPORTED = "ReplacedNotReported"
    PROTECTED_NOT_REPORTED = "ProtectedNotReported"
    VARIETIES_NOT_REPORTED = "VarietiesNotReported"

    # Live on exchange / accepted
    NEW = "New"
    REPLACED = "Replaced"
    PENDING_CANCEL = "PendingCancel"
    WAIT_TO_CANCEL = "WaitToCancel"

    # Partial fill
    PARTIAL_FILLED = "PartialFilled"
    PARTIAL_WITHDRAWAL = "PartialWithdrawal"

    # Terminal
    FILLED = "Filled"
    CANCELED = "Canceled"
    EXPIRED = "Expired"
    REJECTED = "Rejected"
    UNKNOWN = "Unknown"

    # Internal sentinel for SDK statuses we don't recognise (note carries the
    # raw label).  Distinct from ``Rejected`` which the broker itself emits.
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
    #: Current limit price the order is sitting at on the broker side.
    #: Captured from SDK's ``submitted_price`` on every push so post-submit
    #: limit modifications (which the broker labels ``New``) can be detected
    #: by comparing with the previous live event's price.
    submitted_price: float | None = None
    #: Current ordered quantity sitting on the broker side. Captured from
    #: SDK's ``submitted_quantity`` so qty-only modifications (e.g. user
    #: changing 1 share → 2 shares from the broker app) can be detected
    #: alongside price changes — same broker label (``New``), but
    #: ``submitted_quantity`` differs from the prior live event.
    submitted_quantity: int | None = None

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, PushEvent):
            return NotImplemented
        return self.id == other.id

    def __hash__(self) -> int:
        return hash(self.id)
