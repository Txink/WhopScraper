from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.event_bus import EventBus
from app.core.events import Topics
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
        lambda _h, *, source, received_at=None: [
            _fake_message("existing-1"),
            _fake_message("new-1"),
        ],
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
async def test_start_dispatches_to_dedupe_when_enabled(monkeypatch):
    """end-to-end: start() with dedupe=True calls _prime_dedupe (not _prime_skip_initial)."""
    bus = EventBus()

    # Stub browser via the same monkeypatch path used in test_listener.py
    fake_browser = MagicMock()
    fake_browser.start = AsyncMock(return_value=None)
    fake_browser.navigate = AsyncMock(return_value=True)
    fake_browser.scrape_html = AsyncMock(return_value="<html/>")
    fake_browser.close = AsyncMock(return_value=None)
    monkeypatch.setattr("app.whop.listener.WhopBrowser", lambda *a, **kw: fake_browser)

    # Stub repo.load_seen_ids_for_url to record the call
    load_calls: list = []

    async def fake_load(_session, url):
        load_calls.append(url)
        return {"seeded-id"}

    monkeypatch.setattr("app.whop.listener.load_seen_ids_for_url", fake_load, raising=False)

    # Stub session_scope to a no-op async context manager
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def fake_scope(_factory):
        yield MagicMock()

    monkeypatch.setattr("app.whop.listener.session_scope", fake_scope, raising=False)

    listener = WhopListener(
        bus=bus,
        url="https://whop.com/dispatch/app/",
        source="stock",
        dedupe_processed_messages=True,
        session_factory=MagicMock(),
        # would call _prime_skip_initial if dedupe path were skipped —
        # verify it's NOT called below
        skip_initial=True,
        poll_interval=10.0,
    )
    await listener.start()
    try:
        # Verify dedupe branch was taken
        assert load_calls == ["https://whop.com/dispatch/app/"]
        assert "seeded-id" in listener._seen
    finally:
        await listener.stop()


@pytest.mark.asyncio
async def test_start_dispatches_to_skip_initial_when_dedupe_off(monkeypatch):
    """end-to-end: start() with dedupe=False + skip_initial=True calls _prime_skip_initial."""
    bus = EventBus()

    fake_browser = MagicMock()
    fake_browser.start = AsyncMock(return_value=None)
    fake_browser.navigate = AsyncMock(return_value=True)
    fake_browser.scrape_html = AsyncMock(return_value="<html><div>existing</div></html>")
    fake_browser.close = AsyncMock(return_value=None)
    monkeypatch.setattr("app.whop.listener.WhopBrowser", lambda *a, **kw: fake_browser)

    extract_calls: list = []

    def fake_extract(html, *, source, received_at=None):
        extract_calls.append(html)
        return [_fake_message("dom-existing")]

    monkeypatch.setattr("app.whop.listener.extract_messages", fake_extract)

    listener = WhopListener(
        bus=bus,
        url="https://whop.com/skip/app/",
        source="stock",
        dedupe_processed_messages=False,
        session_factory=None,
        skip_initial=True,
        poll_interval=10.0,
    )
    await listener.start()
    try:
        # Verify _prime_skip_initial was called (extract called once during prime)
        assert len(extract_calls) >= 1
        assert "dom-existing" in listener._seen
    finally:
        await listener.stop()


@pytest.mark.asyncio
async def test_start_no_priming_when_both_off(monkeypatch):
    """end-to-end: dedupe=False + skip_initial=False → _seen starts empty."""
    bus = EventBus()
    fake_browser = MagicMock()
    fake_browser.start = AsyncMock(return_value=None)
    fake_browser.navigate = AsyncMock(return_value=True)
    fake_browser.scrape_html = AsyncMock(return_value="<html/>")
    fake_browser.close = AsyncMock(return_value=None)
    monkeypatch.setattr("app.whop.listener.WhopBrowser", lambda *a, **kw: fake_browser)
    extract_calls: list = []

    def fake_extract(html, *, source, received_at=None):
        extract_calls.append(html)
        return []

    monkeypatch.setattr("app.whop.listener.extract_messages", fake_extract)

    listener = WhopListener(
        bus=bus,
        url="https://whop.com/empty/app/",
        source="stock",
        dedupe_processed_messages=False,
        session_factory=None,
        skip_initial=False,
        poll_interval=10.0,
    )
    await listener.start()
    try:
        # No priming → no extract call (only the polling loop's first scrape will call it)
        # Allow short delay for the loop to start (or not)
        assert listener._seen == set()
    finally:
        await listener.stop()


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
