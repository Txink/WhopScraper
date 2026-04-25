"""Tests for register_parser_service registry-based ticker resolution.

Covers Task F: ParserService takes a WhopRegistry and per-message looks up
page settings.tickers based on message.url instead of a process-wide watchlist.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.event_bus import Event, EventBus
from app.core.events import MessagePayload, Topics
from app.domain.message import Message
from app.parser.service import register_parser_service
from app.whop.page_settings import PageSettings, TickerConfig


@pytest.mark.asyncio
async def test_parser_service_uses_registry_tickers(
    monkeypatch: pytest.MonkeyPatch,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    bus = EventBus()
    fake_registry = MagicMock()
    fake_registry.get_settings_for_url.return_value = PageSettings(
        dedupe_processed_messages=True,
        price_deviation_tolerance=1.0,
        tickers={
            "NVDA": TickerConfig(trade_quantity=100),
            "TSLA": TickerConfig(trade_quantity=200),
        },
    )

    captured_watched: list[set[str]] = []

    async def fake_resolve(*, session_factory, msg, parsed, watched_tickers):  # noqa: ANN001
        captured_watched.append(watched_tickers)
        return parsed

    monkeypatch.setattr("app.parser.service.resolve_context", fake_resolve)
    monkeypatch.setattr(
        "app.parser.service.stock_parser.parse",
        lambda content, message_id: None,  # noqa: ARG005
    )

    register_parser_service(bus, session_factory, registry=fake_registry)

    msg = Message(
        id="m1",
        content="x",
        raw_content="x",
        author=None,
        posted_at=datetime.now(UTC),
        received_at=datetime.now(UTC),
        source="stock",
        url="https://whop.com/x/app/",
    )
    await bus.publish(Event(Topics.MESSAGE_RECEIVED, MessagePayload(msg)))
    await bus.wait_idle()

    assert len(captured_watched) == 1
    assert captured_watched[0] == {"NVDA", "TSLA"}
    fake_registry.get_settings_for_url.assert_called_with("https://whop.com/x/app/")


@pytest.mark.asyncio
async def test_parser_service_orphan_url_passes_empty_set(
    monkeypatch: pytest.MonkeyPatch,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    bus = EventBus()
    fake_registry = MagicMock()
    fake_registry.get_settings_for_url.return_value = None  # orphan

    captured: list[set[str]] = []

    async def fake_resolve(*, session_factory, msg, parsed, watched_tickers):  # noqa: ANN001
        captured.append(watched_tickers)
        return parsed

    monkeypatch.setattr("app.parser.service.resolve_context", fake_resolve)
    monkeypatch.setattr(
        "app.parser.service.stock_parser.parse",
        lambda c, message_id: None,  # noqa: ARG005
    )

    register_parser_service(bus, session_factory, registry=fake_registry)
    msg = Message(
        id="m2",
        content="x",
        raw_content="x",
        author=None,
        posted_at=datetime.now(UTC),
        received_at=datetime.now(UTC),
        source="stock",
        url=None,
    )
    await bus.publish(Event(Topics.MESSAGE_RECEIVED, MessagePayload(msg)))
    await bus.wait_idle()
    assert captured == [set()]


@pytest.mark.asyncio
async def test_parser_service_no_registry_passes_empty_set(
    monkeypatch: pytest.MonkeyPatch,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Backwards compat: if no registry passed (e.g., legacy tests), watched_tickers = set()."""
    bus = EventBus()

    captured: list[set[str]] = []

    async def fake_resolve(*, session_factory, msg, parsed, watched_tickers):  # noqa: ANN001
        captured.append(watched_tickers)
        return parsed

    monkeypatch.setattr("app.parser.service.resolve_context", fake_resolve)
    monkeypatch.setattr(
        "app.parser.service.stock_parser.parse",
        lambda c, message_id: None,  # noqa: ARG005
    )

    register_parser_service(bus, session_factory)  # no registry kwarg

    msg = Message(
        id="m3",
        content="x",
        raw_content="x",
        author=None,
        posted_at=datetime.now(UTC),
        received_at=datetime.now(UTC),
        source="stock",
        url="https://whop.com/x/app/",
    )
    await bus.publish(Event(Topics.MESSAGE_RECEIVED, MessagePayload(msg)))
    await bus.wait_idle()
    assert captured == [set()]
