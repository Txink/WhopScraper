"""MessagePayload should carry an is_historical flag (default False)."""

from datetime import UTC, datetime

from app.core.events import MessagePayload
from app.domain.message import Message


def _msg() -> Message:
    return Message(
        id="m1",
        content="x",
        raw_content="x",
        author=None,
        posted_at=datetime.now(UTC),
        received_at=datetime.now(UTC),
        source="stock",
        url=None,
        quoted=None,
        history_hint=[],
    )


def test_message_payload_default_is_historical_false():
    p = MessagePayload(message=_msg())
    assert p.is_historical is False


def test_message_payload_accepts_is_historical_true():
    p = MessagePayload(message=_msg(), is_historical=True)
    assert p.is_historical is True
