from dataclasses import FrozenInstanceError
from datetime import UTC, datetime

import pytest

from app.domain.push_event import PushEvent, PushState


def _make(**overrides):
    defaults = dict(
        id="evt-001",
        task_id="msg-abc-123",
        order_id="729308570398740480",
        state=PushState.NEW,
        received_at=datetime(2026, 4, 25, 10, 42, 15, 498_000, tzinfo=UTC),
        payload={"raw": "..."},
        delta_qty=None,
        delta_price=None,
        cumulative_qty=None,
        cumulative_avg_price=None,
        note=None,
    )
    defaults.update(overrides)
    return PushEvent(**defaults)


def test_push_event_frozen():
    e = _make()
    with pytest.raises(FrozenInstanceError):
        e.state = PushState.FILLED


def test_push_event_equal_by_id():
    a = _make()
    b = _make(payload={"other": "data"})
    assert a == b


def test_push_state_values():
    assert PushState.NEW.value == "NEW"
    assert PushState.PARTIAL.value == "PARTIAL"
    assert PushState.FILLED.value == "FILLED"


def test_partial_fill_carries_deltas():
    e = _make(
        state=PushState.PARTIAL,
        delta_qty=100,
        delta_price=26.47,
        cumulative_qty=100,
        cumulative_avg_price=26.47,
    )
    assert e.delta_qty == 100
    assert e.cumulative_avg_price == 26.47
