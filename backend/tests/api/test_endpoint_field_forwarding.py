"""Field-forwarding contracts between data sources and Pydantic *Out
schemas.

Each test here walks ``ModelName.model_fields`` and asserts that an
exhaustive synthetic input round-trips every field to the output
model. When a new field is added to a schema, the corresponding test
fails with a precise message ("QuoteOut has new fields not covered:
{'foo'}") until the test's ``exhaustive`` fixture is extended — at
which point the assertion loop then verifies the new field is
actually forwarded by the marshaller.

This protects against the class of bug fixed in 5dfcd02 (where
``quote_endpoint`` silently dropped a newly added ``trading_day``
field) by making the contract impossible to extend without
acknowledging every consumer.

Each test targets one (model, marshaller) pair. The marshallers live
either in ``app.api.http`` (broker dict / ORM row → schema) or
``app.api.schemas`` (domain object → schema).
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from types import SimpleNamespace
from typing import Any

import pytest

from app.api.http import (
    _broker_dict_to_position_out,
    _broker_dict_to_quote_out,
    _broker_status_dict_to_out,
    _execution_row_to_out,
    _row_to_chat_out,
)
from app.api.schemas import (
    BrokerStatusOut,
    ChatMessageOut,
    ExecutionOut,
    PositionOut,
    QuoteOut,
    TaskOut,
    TaskSummaryOut,
    task_to_out,
    task_to_summary,
)
from app.domain.instruction import InstructionType, StockInstruction
from app.domain.message import Message
from app.domain.push_event import PushEvent, PushState
from app.domain.status import Status
from app.domain.task import Task

_NOW = datetime(2026, 5, 22, 14, 30, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Helper: assert every model_fields key (minus exclusions) is in fixture,
# then assert every fixture key round-trips to the output.
# ---------------------------------------------------------------------------


def _assert_exhaustive_fixture(
    model_cls: type, fixture: dict[str, Any], excluded: set[str] | None = None,
) -> None:
    """Fail loudly if ``fixture`` doesn't cover every field on
    ``model_cls``. Excluded names are fields populated by the
    marshaller from a separate source (e.g. ``symbol`` comes from the
    request, not the broker dict)."""
    excluded = excluded or set()
    expected = set(model_cls.model_fields) - excluded
    missing = expected - set(fixture)
    assert not missing, (
        f"{model_cls.__name__} has new fields not covered by this test: "
        f"{missing}. Add them to the ``exhaustive`` dict in this test "
        f"with distinct values so field forwarding is verified end-to-end."
    )


# ---------------------------------------------------------------------------
# QuoteOut — already covered by test_quote_endpoint_forwards_every_quote_out_field
# in test_quote_candles_http.py; included here too for direct helper coverage.
# ---------------------------------------------------------------------------


def test_broker_dict_to_quote_out_forwards_every_field() -> None:
    exhaustive: dict[str, Any] = {
        "last_done": 1.0, "prev_close": 2.0, "today_close": 3.0,
        "open": 4.0, "high": 5.0, "low": 6.0,
        "volume": 7, "turnover": 8.0,
        "change": 9.0, "change_pct": 10.0,
        "trade_session": "post",
        "trading_day": "2026-05-22",
    }
    _assert_exhaustive_fixture(QuoteOut, exhaustive, excluded={"symbol"})
    out = _broker_dict_to_quote_out("X.US", exhaustive)
    for field, value in exhaustive.items():
        assert getattr(out, field) == value, f"{field!r} dropped"


# ---------------------------------------------------------------------------
# BrokerStatusOut
# ---------------------------------------------------------------------------


def test_broker_status_dict_to_out_forwards_every_field() -> None:
    exhaustive: dict[str, Any] = {
        "is_real": True,
        "account_label": "real-1",
        "dry_run": False,
        "last_init_error": "previous attempt timed out",
    }
    _assert_exhaustive_fixture(BrokerStatusOut, exhaustive)
    out = _broker_status_dict_to_out(exhaustive)
    for field, value in exhaustive.items():
        assert getattr(out, field) == value, f"{field!r} dropped"


# ---------------------------------------------------------------------------
# ChatMessageOut
# ---------------------------------------------------------------------------


def test_row_to_chat_out_forwards_every_field() -> None:
    """Walks ChatMessageOut.model_fields. The marshaller derives
    ``image_url`` from ``row.image_filename`` and ``quoted`` from the
    denormalised ``quoted_*`` columns — both verified individually."""
    row = SimpleNamespace(
        id="msg-1",
        page_id="page-1",
        author="alice",
        content="hello",
        posted_at=_NOW,
        image_filename="abc.png",
        quoted_message_id="parent-1",
        quoted_author="bob",
        quoted_content="quoted text",
        quoted_posted_at=_NOW,
    )
    # The fixture mirrors what ChatMessageOut should ultimately contain.
    expected_out: dict[str, Any] = {
        "id": "msg-1",
        "page_id": "page-1",
        "author": "alice",
        "content": "hello",
        "posted_at": _NOW,
        # quoted + image_url are computed by the marshaller; checked separately below.
        "quoted": "<COMPUTED>",
        "image_url": "<COMPUTED>",
    }
    _assert_exhaustive_fixture(ChatMessageOut, expected_out)
    out = _row_to_chat_out(row)
    assert out.id == "msg-1"
    assert out.page_id == "page-1"
    assert out.author == "alice"
    assert out.content == "hello"
    assert out.posted_at == _NOW
    assert out.image_url == "/api/chat-images/msg-1"
    assert out.quoted is not None
    assert out.quoted.message_id == "parent-1"
    assert out.quoted.author == "bob"
    assert out.quoted.content == "quoted text"
    assert out.quoted.posted_at == _NOW


# ---------------------------------------------------------------------------
# ExecutionOut
# ---------------------------------------------------------------------------


def test_execution_row_to_out_forwards_every_field() -> None:
    """``side`` accepts only ``BUY | SELL``; pick BUY and verify the
    Literal coercion."""
    row = SimpleNamespace(
        order_id="ord-1",
        task_id="task-1",
        symbol="TSLA.US",
        ticker="TSLA",
        side="BUY",
        qty=100,
        price=195.0,
        ts=_NOW,
        t_pair_tags=[(7, 50), (8, 50)],
    )
    exhaustive: dict[str, Any] = {
        "order_id": "ord-1",
        "task_id": "task-1",
        "symbol": "TSLA.US",
        "ticker": "TSLA",
        "side": "BUY",
        "qty": 100,
        "price": 195.0,
        "ts": _NOW,
        "t_pair_tags": [(7, 50), (8, 50)],
    }
    _assert_exhaustive_fixture(ExecutionOut, exhaustive)
    out = _execution_row_to_out(row)
    for field, value in exhaustive.items():
        assert getattr(out, field) == value, f"{field!r} dropped"


def test_execution_row_to_out_attaches_utc_on_naive_ts() -> None:
    """SQLite returns naive datetimes; marshaller must re-attach UTC."""
    naive = datetime(2026, 5, 22, 14, 30, 0)
    row = SimpleNamespace(
        order_id="o", task_id=None, symbol="X.US", ticker="X",
        side="BUY", qty=1, price=1.0, ts=naive, t_pair_tags=[],
    )
    out = _execution_row_to_out(row)
    assert out.ts.tzinfo is not None
    assert out.ts.utcoffset() == datetime.now(UTC).utcoffset() or out.ts.tzinfo.utcoffset(out.ts) is not None


# ---------------------------------------------------------------------------
# PositionOut
# ---------------------------------------------------------------------------


def test_broker_dict_to_position_out_forwards_every_field_stock() -> None:
    """Stock branch: option_strike/expiry/type are None by construction
    but still must be present on the output."""
    p: dict[str, Any] = {
        "symbol": "TSLA.US",
        "ticker": "TSLA",
        "quantity": 100,
        "avg_cost": 200.0,
        "name": "Tesla Inc.",
    }
    expected: dict[str, Any] = {
        "symbol": "TSLA.US",
        "type": "stock",
        "ticker": "TSLA",
        "quantity": 100,
        "avg_cost": 200.0,
        "name": "Tesla Inc.",
        "option_strike": None,
        "option_expiry": None,
        "option_type": None,
    }
    _assert_exhaustive_fixture(PositionOut, expected)
    out = _broker_dict_to_position_out(p)
    for field, value in expected.items():
        assert getattr(out, field) == value, f"{field!r} dropped"


def test_broker_dict_to_position_out_forwards_every_field_option() -> None:
    """Option branch: option_strike/expiry/type are populated from the
    OCC-format symbol, ticker is the underlying."""
    p: dict[str, Any] = {
        "symbol": "TSLA250620C00300000.US",
        "quantity": 5,
        "avg_cost": 4.20,
        "name": "TSLA 250620 C 300",
    }
    out = _broker_dict_to_position_out(p)
    assert out.type == "option"
    assert out.ticker == "TSLA"
    assert out.symbol == "TSLA250620C00300000.US"
    assert out.quantity == 5
    assert out.avg_cost == pytest.approx(4.20)
    assert out.name == "TSLA 250620 C 300"
    assert out.option_strike == pytest.approx(300.0)
    assert out.option_expiry == date(2025, 6, 20)
    assert out.option_type in ("CALL", "C")  # parser may use either


# ---------------------------------------------------------------------------
# TaskOut / TaskSummaryOut
# ---------------------------------------------------------------------------


def _make_full_task() -> Task:
    """A Task with every populatable field set to a distinct, non-default
    value — so a marshaller dropping any field would produce a different
    output than the input claims."""
    msg = Message(
        id="msg-task-out",
        content="buy AAPL 200",
        raw_content="buy AAPL 200",
        author="trader",
        posted_at=_NOW,
        received_at=_NOW,
        source="stock",
        quoted=None,
    )
    inst = StockInstruction(
        instruction_type=InstructionType.BUY,
        price=195.0, price_range=None, quantity=200,
        position_size=None, stop_loss_price=None, take_profit_price=None,
        context_source=None, parser_notes=[],
        ticker="AAPL", symbol="AAPL.US", sell_quantity=None,
    )
    push = PushEvent(
        id="evt-1", task_id="msg-task-out", order_id="ord-1",
        state=PushState.FILLED, received_at=_NOW, payload={},
        delta_qty=100, delta_price=195.0,
        cumulative_qty=200, cumulative_avg_price=195.25,
        note="filled",
    )
    task = Task(
        id="msg-task-out", type="stock", status=Status.FILLED,
        message=msg, instruction=inst, push_events=[push],
        order_id="ord-1",
        submit_order_type="LIMIT",
        submit_order_context="买入：现价 ≥ 信号价 → 限价单",
        submit_quote_last_done=194.5,
        submit_price=195.0,
        created_at=_NOW, updated_at=_NOW,
    )
    return task


def test_task_to_out_forwards_every_field() -> None:
    """Every TaskOut field must be reachable from a fully-populated Task.
    If a new field is added without wiring it up in ``task_to_out``,
    the assertion at the bottom catches it."""
    task = _make_full_task()
    out = task_to_out(task)

    # Required to be non-None for every field that has a known source
    # on the Task domain object.
    fields_with_known_source = {
        "id", "type", "status", "order_id", "submit_order_type",
        "submit_order_context", "submit_quote_last_done", "submit_price",
        "stage_timings", "created_at", "updated_at",
        "message", "instruction", "push_events",
        "last_cum_qty", "last_cum_avg_price",
    }
    # Optional / derived — present in model but may legitimately be
    # None even with a fully-populated task. ``reject_reason`` is None
    # on a successful task; ``last_submitted_*`` come from
    # PushEvent.submitted_* which aren't always populated.
    optional_fields = {
        "reject_reason", "last_submitted_price", "last_submitted_qty",
        "label",
    }

    # Every field on TaskOut is either sourced or optional — catch new
    # fields that fall into neither bucket.
    coverage = fields_with_known_source | optional_fields
    missing = set(TaskOut.model_fields) - coverage
    assert not missing, (
        f"TaskOut has new fields not classified by this test: {missing}. "
        f"Decide whether each new field has a known Task-domain source "
        f"(add to ``fields_with_known_source``) or is legitimately optional "
        f"(add to ``optional_fields``), and verify ``task_to_out`` wires "
        f"the source up. Then add the new field's name here."
    )

    # Now verify the sourced fields are non-None / non-empty.
    for field in fields_with_known_source:
        value = getattr(out, field)
        assert value is not None and value != [], (
            f"task_to_out dropped field {field!r}: got {value!r}"
        )


def test_task_to_summary_forwards_every_field() -> None:
    """Same protection as task_to_out, but for the list-endpoint
    summary serializer (excludes push_events)."""
    task = _make_full_task()
    out = task_to_summary(task)

    fields_with_known_source = {
        "id", "type", "status", "order_id", "submit_order_type",
        "submit_order_context", "submit_quote_last_done", "submit_price",
        "stage_timings", "created_at", "updated_at",
        "message", "instruction",
        "last_cum_qty", "last_cum_avg_price",
    }
    optional_fields = {
        "reject_reason", "last_submitted_price", "last_submitted_qty",
        "label",
    }
    coverage = fields_with_known_source | optional_fields
    missing = set(TaskSummaryOut.model_fields) - coverage
    assert not missing, (
        f"TaskSummaryOut has new fields not classified by this test: "
        f"{missing}. See test_task_to_out_forwards_every_field for the "
        f"pattern."
    )
    for field in fields_with_known_source:
        value = getattr(out, field)
        assert value is not None and value != [], (
            f"task_to_summary dropped field {field!r}: got {value!r}"
        )
