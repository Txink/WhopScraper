"""Scenario runner — drives a Scenario through the real bus + DB pipeline.

Sim's role is **strictly** to skip the LongPort broker calls
(``submit_order`` and friends). Everything else — parser, trader gates,
qty resolution, quote-vs-signal decision, mark_submitted, storage,
WebSocket bridge, push processing — runs on the real production code.

How the trader knows it's a sim task
------------------------------------
The runner injects a ``Message`` with ``url=sim://scenarios``. The trader
checks that URL in its submit step and substitutes a synthetic order_id
instead of calling ``broker.submit_order``. See
``app.broker.trader._handle_instruction_ready`` and
``app.sim.virtual_page`` (which registers the sim page so trader's
whitelist + qty resolution gates pass).

Synchronous broker failures (SUBMIT_FAILED) are simulated by stashing
the failure reason in :data:`PENDING_SIM_FAILURES` keyed on message_id
*before* publishing ``MESSAGE_RECEIVED``. The trader's sim branch
pops the entry and raises the corresponding error, falling into its
existing ``except Exception`` → ``mark_submit_failed`` path.
"""

from __future__ import annotations

import asyncio
import logging
import secrets
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.event_bus import Event, EventBus
from app.core.events import MessagePayload, Topics
from app.domain.message import Message
from app.domain.status import TERMINAL, Status
from app.sim.scenarios import SCENARIOS, PushStep, Scenario
from app.storage.repo import load_task

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Cross-module signal: trader reads this dict in its sim branch.
# ---------------------------------------------------------------------------

#: ``{message_id: failure_reason}``. Populated by :func:`run_scenario` BEFORE
#: publishing ``MESSAGE_RECEIVED`` so the trader can pop-and-raise inside its
#: synthetic submit branch. Pop semantics ensure each entry fires once.
PENDING_SIM_FAILURES: dict[str, str] = {}


@dataclass(frozen=True)
class SimRunResult:
    """Returned to the API caller — gives the frontend something to look up."""

    scenario_name: str
    message_id: str
    order_id: str | None  # None when scenario halts pre-submit (parse error / sync fail)
    push_count: int


# ---------------------------------------------------------------------------
# Push event stand-in
# ---------------------------------------------------------------------------


class _SimPushEvent:
    """Plain-object stand-in for ``longport.openapi.PushOrderChanged``.

    ``PushListener._handle_raw_push`` accesses fields via ``getattr`` and
    ``_to_payload_dict`` walks ``dir()`` for serialisation, so a plain class
    with attributes works identically to the SDK's C-extension type for our
    purposes. Decimal-typed price/qty matches the production shape so the
    Decimal handling in ``_serialise_value`` stays exercised.
    """

    def __init__(
        self,
        *,
        order_id: str,
        status: str,
        submitted_price: float | None,
        submitted_quantity: int | None,
        executed_quantity: int,
        executed_price: float | None,
        msg: str,
    ) -> None:
        self.order_id = order_id
        self.status = status  # plain str — _map_sdk_status accepts both Enum and str
        self.submitted_price = (
            Decimal(f"{submitted_price:.4f}") if submitted_price is not None else None
        )
        self.submitted_quantity = (
            Decimal(str(submitted_quantity)) if submitted_quantity is not None else None
        )
        self.executed_quantity = Decimal(str(executed_quantity))
        self.executed_price = Decimal(f"{executed_price:.4f}") if executed_price is not None else None
        self.msg = msg
        # Padding fields the production payload usually carries.
        self.side = "Buy"
        self.symbol = "SIM.US"
        self.account_no = "SIMULATOR"
        self.remark = "sim"


def _build_sim_push(order_id: str, step: PushStep) -> _SimPushEvent:
    return _SimPushEvent(
        order_id=order_id,
        status=step.status,
        submitted_price=step.sub_px,
        submitted_quantity=step.sub_qty,
        executed_quantity=step.exec_qty,
        executed_price=step.exec_px,
        msg=step.msg,
    )


# ---------------------------------------------------------------------------
# Message construction
# ---------------------------------------------------------------------------


def build_scenario_message(name: str) -> Message:
    """Eagerly build the synthetic Message for a scenario.

    Exposed so the REST endpoint can pre-allocate a message_id and return it
    to the caller before kicking off the async runner — the frontend uses
    that id to highlight / scroll-to the resulting card.
    """
    scenario = SCENARIOS.get(name)
    if scenario is None:
        raise KeyError(f"Unknown scenario: {name!r}")
    msg_id = f"sim_{int(time.time() * 1000)}_{secrets.token_hex(3)}"
    now = datetime.now(UTC)
    return Message(
        id=msg_id,
        content=scenario.message_text,
        raw_content=scenario.message_text,
        author="simulator",
        posted_at=now,
        received_at=now,
        source=scenario.source,  # type: ignore[arg-type]
        url="sim://scenarios",
    )


# ---------------------------------------------------------------------------
# Wait helper — drains the bus before each DB read so handler races don't
# rewind state (e.g. a queued INSTRUCTION_READY save landing AFTER the
# trader's PENDING save and silently overwriting it).
# ---------------------------------------------------------------------------


_TRANSIENT: frozenset[Status] = frozenset({
    Status.RECEIVED, Status.PARSING, Status.INSTRUCTION_READY, Status.SUBMITTING,
})


async def _wait_until_settled(
    bus: EventBus,
    session_factory: async_sessionmaker[AsyncSession],
    task_id: str,
    *,
    timeout_s: float = 5.0,
    poll_interval_s: float = 0.05,
):
    """Poll DB until the task settles past the transient parse/submit stages.

    "Settled" means: status is PENDING (live, awaiting fills), PARTIAL,
    or any TERMINAL state. Returns the loaded Task or None on timeout.
    """
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            await bus.wait_idle(timeout=0.5)
        except TimeoutError:
            pass
        async with session_factory() as session:
            task = await load_task(session, task_id)
        if task is not None and task.status not in _TRANSIENT:
            return task
        await asyncio.sleep(poll_interval_s)
    return None


# ---------------------------------------------------------------------------
# Public entrypoint
# ---------------------------------------------------------------------------


async def run_scenario(
    name: str,
    msg: Message,
    *,
    bus: EventBus,
    session_factory: async_sessionmaker[AsyncSession],
    push_listener: Any | None,  # PushListener | None — Any to avoid circular import
) -> SimRunResult:
    """Drive a scenario end-to-end through the real production pipeline.

    Steps:
      1. (If sync-failure scenario) register the failure in
         :data:`PENDING_SIM_FAILURES` keyed on msg.id so the trader's
         sim branch raises during its synthetic submit.
      2. Inject ``MESSAGE_RECEIVED``. The real parser + trader handle
         everything from here through ``mark_submitted`` (or a terminal
         state for parse errors / sync failures).
      3. Wait for the task to settle (past PARSING/SUBMITTING).
      4. If the task ended up at PENDING and the scenario carries push
         steps, replay each step through ``PushListener._handle_raw_push``.
    """
    scenario = SCENARIOS.get(name)
    if scenario is None:
        raise KeyError(f"Unknown scenario: {name!r}")

    logger.info("sim: starting scenario=%s message_id=%s", scenario.name, msg.id)

    # 1. Register sync-failure intent (consumed by trader's sim branch).
    if scenario.submit_failure is not None:
        PENDING_SIM_FAILURES[msg.id] = scenario.submit_failure

    # 2. Inject MESSAGE_RECEIVED — real parser + trader pick this up.
    await bus.publish(Event(Topics.MESSAGE_RECEIVED, MessagePayload(msg, is_historical=False)))

    # 3. Wait for the trader (or parser, on PARSE_ERROR) to settle the task.
    task = await _wait_until_settled(bus, session_factory, msg.id, timeout_s=5.0)
    if task is None:
        logger.warning("sim: scenario %s timed out waiting for task to settle", scenario.name)
        # Defensive cleanup so a never-fired failure doesn't leak.
        PENDING_SIM_FAILURES.pop(msg.id, None)
        return SimRunResult(scenario_name=name, message_id=msg.id, order_id=None, push_count=0)

    logger.info(
        "sim: scenario %s settled — status=%s order_id=%s",
        scenario.name, task.status, task.order_id,
    )

    # 4a. Terminal / no-pushes paths return immediately.
    if scenario.push_steps is None or not scenario.push_steps:
        return SimRunResult(
            scenario_name=name, message_id=msg.id,
            order_id=task.order_id, push_count=0,
        )
    if task.status in TERMINAL:
        # Parse error, SKIPPED, sync SUBMIT_FAILED — no order_id to push to.
        return SimRunResult(
            scenario_name=name, message_id=msg.id,
            order_id=task.order_id, push_count=0,
        )
    if task.order_id is None:
        logger.warning("sim: scenario %s reached %s but has no order_id", scenario.name, task.status)
        return SimRunResult(scenario_name=name, message_id=msg.id, order_id=None, push_count=0)
    if push_listener is None:
        logger.warning("sim: scenario %s — push_listener unavailable; skipping pushes", scenario.name)
        return SimRunResult(scenario_name=name, message_id=msg.id, order_id=task.order_id, push_count=0)

    # 4b. Replay push steps with their configured delays. The trader has
    # already committed task.order_id; PushListener resolves the task by
    # order_id from a fresh DB session on each handler invocation.
    for step in scenario.push_steps:
        await asyncio.sleep(step.delay_s)
        raw = _build_sim_push(task.order_id, step)
        await push_listener._handle_raw_push(raw)

    logger.info(
        "sim: scenario %s done — %d push(es) replayed against order %s",
        scenario.name, len(scenario.push_steps), task.order_id,
    )
    return SimRunResult(
        scenario_name=name,
        message_id=msg.id,
        order_id=task.order_id,
        push_count=len(scenario.push_steps),
    )
