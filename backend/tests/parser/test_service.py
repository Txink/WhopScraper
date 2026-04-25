"""Tests for app.parser.service — Task 20.

Five test cases covering the parser event-bus service:
1. test_stock_message_resolves_to_instruction_ready
2. test_option_message_resolves
3. test_unparseable_message_emits_parse_failed
4. test_task_created_emitted_before_final_event
5. test_parse_timing_recorded
"""
from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.event_bus import Event, EventBus
from app.core.events import MessagePayload, TaskPayload, Topics
from app.domain.message import Message
from app.domain.status import Status
from app.parser.service import register_parser_service

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 4, 24, 14, 0, 0, tzinfo=UTC)


def _stock_msg(
    id_: str,
    content: str,
    posted_at: datetime = _NOW,
) -> Message:
    return Message(
        id=id_,
        content=content,
        raw_content=content,
        author="trader",
        posted_at=posted_at,
        received_at=posted_at,
        source="stock",
    )


def _option_msg(
    id_: str,
    content: str,
    posted_at: datetime = _NOW,
) -> Message:
    return Message(
        id=id_,
        content=content,
        raw_content=content,
        author="trader",
        posted_at=posted_at,
        received_at=posted_at,
        source="option",
    )


async def _run(bus: EventBus, msg: Message) -> list[Event]:
    """Publish MESSAGE_RECEIVED and drain the bus; return all observed events."""
    observed: list[Event] = []

    async def _capture(evt: Event) -> None:
        observed.append(evt)

    # Subscribe to all task topics to capture ordering
    for topic in (
        Topics.TASK_CREATED,
        Topics.TASK_INSTRUCTION_READY,
        Topics.TASK_PARSE_FAILED,
    ):
        bus.subscribe(topic, _capture)

    await bus.publish(Event(Topics.MESSAGE_RECEIVED, MessagePayload(msg)))
    # wait_idle twice: first pass drains MESSAGE_RECEIVED handler which
    # schedules downstream publishes; second pass drains those.
    await bus.wait_idle(timeout=5)
    await bus.wait_idle(timeout=5)
    return observed


# ---------------------------------------------------------------------------
# Test 1: stock message resolves to INSTRUCTION_READY
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stock_message_resolves_to_instruction_ready(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Valid stock message 'TSLL 26.5 加一半' (TSLL in watched_tickers) →
    TASK_INSTRUCTION_READY with status=INSTRUCTION_READY, type=stock, ticker=TSLL."""
    bus = EventBus()
    register_parser_service(bus, session_factory, watched_tickers={"TSLL"})

    msg = _stock_msg("s1", "TSLL 26.5 买一半")
    observed = await _run(bus, msg)

    instruction_ready_events = [
        e for e in observed if e.topic == Topics.TASK_INSTRUCTION_READY
    ]
    assert len(instruction_ready_events) >= 1, (
        f"Expected TASK_INSTRUCTION_READY; got topics: {[e.topic for e in observed]}"
    )

    payload = instruction_ready_events[0].payload
    assert isinstance(payload, TaskPayload)
    task = payload.task
    from app.domain.instruction import StockInstruction

    assert task.status == Status.INSTRUCTION_READY
    assert task.type == "stock"
    assert isinstance(task.instruction, StockInstruction)
    assert task.instruction.ticker == "TSLL"


# ---------------------------------------------------------------------------
# Test 2: option message resolves
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_option_message_resolves(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Valid option message → TASK_INSTRUCTION_READY with type=option."""
    bus = EventBus()
    register_parser_service(bus, session_factory, watched_tickers=None)

    # A clear option message that the option parser can parse
    msg = _option_msg("o1", "NVDA 135C 本周 2.15 买")
    observed = await _run(bus, msg)

    instruction_ready_events = [
        e for e in observed if e.topic == Topics.TASK_INSTRUCTION_READY
    ]
    assert len(instruction_ready_events) >= 1, (
        f"Expected TASK_INSTRUCTION_READY; got topics: {[e.topic for e in observed]}"
    )

    payload = instruction_ready_events[0].payload
    assert isinstance(payload, TaskPayload)
    task = payload.task
    from app.domain.instruction import OptionInstruction

    assert task.status == Status.INSTRUCTION_READY
    assert task.type == "option"
    assert isinstance(task.instruction, OptionInstruction)
    assert task.instruction.ticker == "NVDA"


# ---------------------------------------------------------------------------
# Test 3: unparseable message → TASK_PARSE_FAILED
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unparseable_message_emits_parse_failed(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Content '盘后信息参考' (chatter, no action/price) → TASK_PARSE_FAILED
    with status=PARSE_ERROR and reject_reason present."""
    bus = EventBus()
    register_parser_service(bus, session_factory, watched_tickers=None)

    msg = _stock_msg("s-fail", "盘后信息参考")
    observed = await _run(bus, msg)

    parse_failed_events = [
        e for e in observed if e.topic == Topics.TASK_PARSE_FAILED
    ]
    assert len(parse_failed_events) >= 1, (
        f"Expected TASK_PARSE_FAILED; got topics: {[e.topic for e in observed]}"
    )

    payload = parse_failed_events[0].payload
    assert isinstance(payload, TaskPayload)
    task = payload.task
    assert task.status == Status.PARSE_ERROR
    assert task.reject_reason is not None
    assert len(task.reject_reason) > 0


# ---------------------------------------------------------------------------
# Test 4: TASK_CREATED emitted before final event
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_task_created_emitted_before_final_event(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """TASK_CREATED must appear before TASK_INSTRUCTION_READY or TASK_PARSE_FAILED."""
    bus = EventBus()
    register_parser_service(bus, session_factory, watched_tickers={"TSLL"})

    # Use a message that will succeed so we get TASK_INSTRUCTION_READY
    msg = _stock_msg("s-order", "TSLL 26.5 买一半")
    observed = await _run(bus, msg)

    topics = [e.topic for e in observed]
    assert Topics.TASK_CREATED in topics, f"TASK_CREATED missing; got: {topics}"

    final_topics = {Topics.TASK_INSTRUCTION_READY, Topics.TASK_PARSE_FAILED}
    final_events = [e for e in observed if e.topic in final_topics]
    assert len(final_events) >= 1, f"No final event found; got: {topics}"

    created_idx = topics.index(Topics.TASK_CREATED)
    final_idx = topics.index(final_events[0].topic)
    assert created_idx < final_idx, (
        f"TASK_CREATED (idx={created_idx}) must precede final event (idx={final_idx})"
    )


# ---------------------------------------------------------------------------
# Test 5: parse timing recorded
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_parse_timing_recorded(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Task.stage_timings should have 'parse' key after handling."""
    bus = EventBus()
    register_parser_service(bus, session_factory, watched_tickers={"TSLL"})

    msg = _stock_msg("s-timing", "TSLL 26.5 买一半")
    observed = await _run(bus, msg)

    # Find any task event that carries the final task
    task_events = [
        e for e in observed
        if e.topic in (Topics.TASK_INSTRUCTION_READY, Topics.TASK_PARSE_FAILED)
    ]
    assert len(task_events) >= 1

    payload = task_events[0].payload
    assert isinstance(payload, TaskPayload)
    task = payload.task
    assert "parse" in task.stage_timings, (
        f"Expected 'parse' in stage_timings; got: {task.stage_timings}"
    )
    assert task.stage_timings["parse"] >= 0
