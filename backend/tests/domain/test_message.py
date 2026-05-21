from dataclasses import FrozenInstanceError
from datetime import datetime, timezone

import pytest

from app.domain.message import Message


def _make(**overrides):
    defaults = dict(
        id="msg-abc-123",
        content="NVDA 135C 本周 2.15 进",
        raw_content="NVDA 135C 本周 2.15 进 🚀",
        author="big-elephant",
        posted_at=datetime(2026, 4, 25, 10, 42, 15, tzinfo=timezone.utc),
        received_at=datetime(2026, 4, 25, 10, 42, 15, 82_000, tzinfo=timezone.utc),
        source="option",
        quoted=None,
        history_hint=[],
    )
    defaults.update(overrides)
    return Message(**defaults)


def test_message_is_frozen():
    m = _make()
    with pytest.raises(FrozenInstanceError):
        m.content = "hacked"


def test_message_equal_by_id():
    a = _make()
    b = _make(content="different body")
    assert a == b, "Message 应按 id 唯一识别"


def test_message_source_must_be_stock_or_option():
    with pytest.raises(ValueError):
        _make(source="forex")


def test_message_history_hint_defaults_empty():
    m = _make()
    assert m.history_hint == []


def test_message_with_quoted_chain():
    parent = _make(id="msg-parent")
    child = _make(id="msg-child", quoted=parent)
    assert child.quoted is parent


def test_message_accepts_image_url():
    msg = _make(image_url="https://example.com/x.png")
    assert msg.image_url == "https://example.com/x.png"


def test_message_image_url_defaults_to_none():
    msg = _make()
    assert msg.image_url is None
