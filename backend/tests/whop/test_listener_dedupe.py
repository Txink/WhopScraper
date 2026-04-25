import pytest
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

from app.core.event_bus import Event, EventBus
from app.core.events import MessagePayload, Topics
from app.domain.message import Message
from app.whop.listener import WhopListener


def _fake_message(mid: str) -> Message:
    return Message(
        id=mid,
        content="x",
        raw_content="x",
        author=None,
        posted_at=datetime.now(UTC),
        received_at=datetime.now(UTC),
        source="stock",
    )


@pytest.mark.asyncio
async def test_dedupe_on_loads_seen_from_db(monkeypatch):
    bus = EventBus()
    received: list[Message] = []

    async def _h(evt):
        received.append(evt.payload.message)
    bus.subscribe(Topics.MESSAGE_RECEIVED, _h)

    async def fake_load(_session, _url):
        return {"existing-1", "existing-2"}
    monkeypatch.setattr("app.whop.listener.load_seen_ids_for_url", fake_load, raising=False)

    listener = WhopListener(
        bus=bus,
        url="https://whop.com/x/app/",
        source="stock",
        dedupe_processed_messages=True,
        session_factory=MagicMock(),
        skip_initial=False,
    )
    listener._browser = MagicMock()
    listener._browser.scrape_html = AsyncMock(return_value="<html/>")
    monkeypatch.setattr(
        "app.whop.listener.extract_messages",
        lambda _h, *, source, received_at=None: [_fake_message("existing-1"), _fake_message("new-1")],
    )

    await listener._prime_dedupe()
    await listener._scan_once()
    await bus.wait_idle()

    assert {m.id for m in received} == {"new-1"}


@pytest.mark.asyncio
async def test_dedupe_off_uses_skip_initial(monkeypatch):
    bus = EventBus()
    received: list[Message] = []

    async def _h(evt):
        received.append(evt.payload.message)
    bus.subscribe(Topics.MESSAGE_RECEIVED, _h)

    listener = WhopListener(
        bus=bus,
        url="https://whop.com/y/app/",
        source="stock",
        dedupe_processed_messages=False,
        session_factory=MagicMock(),
        skip_initial=True,
    )
    listener._browser = MagicMock()
    listener._browser.scrape_html = AsyncMock(return_value="<html/>")
    monkeypatch.setattr(
        "app.whop.listener.extract_messages",
        lambda _h, *, source, received_at=None: [_fake_message("a"), _fake_message("b")],
    )

    await listener._prime_skip_initial()
    await listener._scan_once()
    await bus.wait_idle()

    assert received == []


@pytest.mark.asyncio
async def test_scan_once_injects_url(monkeypatch):
    bus = EventBus()
    captured: list[Message] = []

    async def _h(evt):
        captured.append(evt.payload.message)
    bus.subscribe(Topics.MESSAGE_RECEIVED, _h)

    listener = WhopListener(
        bus=bus,
        url="https://whop.com/inject/app/",
        source="stock",
        dedupe_processed_messages=False,
        session_factory=MagicMock(),
        skip_initial=False,
    )
    listener._browser = MagicMock()
    listener._browser.scrape_html = AsyncMock(return_value="<html/>")
    monkeypatch.setattr(
        "app.whop.listener.extract_messages",
        lambda _h, *, source, received_at=None: [_fake_message("m1")],
    )

    await listener._scan_once()
    await bus.wait_idle()
    assert len(captured) == 1
    assert captured[0].url == "https://whop.com/inject/app/"
