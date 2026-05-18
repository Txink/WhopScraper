from datetime import UTC, datetime

from app.core.events import Topics, ChatMessagePayload, ChatMessageStoredPayload
from app.domain.message import Message


def _msg() -> Message:
    return Message(
        id="m1",
        content="hi",
        raw_content="hi",
        author="alice",
        posted_at=datetime(2026, 5, 18, 9, 0, tzinfo=UTC),
        received_at=datetime(2026, 5, 18, 9, 0, tzinfo=UTC),
        source="chat",
        url="https://whop.example/p1",
        quoted=None,
        history_hint=[],
    )


def test_topics_constants_exist() -> None:
    assert Topics.CHAT_MESSAGE_RECEIVED == "chat.message_received"
    assert Topics.CHAT_MESSAGE_STORED == "chat.message_stored"


def test_chat_message_payload_fields() -> None:
    payload = ChatMessagePayload(page_id="p1", message=_msg(), is_historical=False)
    assert payload.page_id == "p1"
    assert payload.is_historical is False


def test_chat_message_stored_carries_row_reference() -> None:
    # ChatMessageStoredPayload is a thin marker payload; we only need page_id + msg_id
    stored = ChatMessageStoredPayload(page_id="p1", message_id="m1")
    assert stored.page_id == "p1"
    assert stored.message_id == "m1"


def test_message_domain_accepts_chat_source() -> None:
    msg = _msg()
    assert msg.source == "chat"
