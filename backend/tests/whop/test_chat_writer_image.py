"""Tests for download_image (app.whop.image_store) and the image-aware chat_writer handler.

Unit tests for download_image cover:
- Happy path: file written, correct filename returned
- Content-type → extension mapping
- HTTP error → None returned, no file written
- Timeout → None returned

Integration test: full handler flow with image download + DB write.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

from app.core.event_bus import Event, EventBus
from app.core.events import ChatMessagePayload, Topics
from app.domain.message import Message
from app.storage.db import session_scope
from app.storage.schema import ChatMessageRow
from app.whop.chat_writer import register_chat_writer
from app.whop.image_store import download_image


async def test_download_image_happy_path(tmp_path: Path) -> None:
    fake_resp = MagicMock()
    fake_resp.status_code = 200
    fake_resp.content = b"fakebytes"
    fake_resp.headers = {"Content-Type": "image/avif"}
    fake_resp.raise_for_status = MagicMock()

    fake_client = AsyncMock()
    fake_client.get = AsyncMock(return_value=fake_resp)
    fake_client.__aenter__.return_value = fake_client
    fake_client.__aexit__.return_value = None

    with patch("app.whop.image_store.httpx.AsyncClient", return_value=fake_client):
        filename = await download_image(
            "msg_1", "https://example.com/x.avif", tmp_path
        )

    assert filename == "msg_1.avif"
    assert (tmp_path / "chat-images" / "msg_1.avif").read_bytes() == b"fakebytes"


async def test_download_image_maps_content_types(tmp_path: Path) -> None:
    cases = [
        ("image/png", "msg_a.png"),
        ("image/jpeg", "msg_b.jpg"),
        ("image/webp", "msg_c.webp"),
        ("application/octet-stream", "msg_d.bin"),
    ]
    for ct, expected_name in cases:
        msg_id = expected_name.split(".")[0]
        fake_resp = MagicMock(
            status_code=200, content=b"x", headers={"Content-Type": ct}
        )
        fake_resp.raise_for_status = MagicMock()
        fake_client = AsyncMock()
        fake_client.get = AsyncMock(return_value=fake_resp)
        fake_client.__aenter__.return_value = fake_client
        fake_client.__aexit__.return_value = None

        with patch("app.whop.image_store.httpx.AsyncClient", return_value=fake_client):
            filename = await download_image(msg_id, "https://example.com/x", tmp_path)

        assert filename == expected_name


async def test_download_image_returns_none_on_http_error(tmp_path: Path) -> None:
    fake_resp = MagicMock(status_code=403, content=b"", headers={})
    fake_resp.raise_for_status = MagicMock(
        side_effect=httpx.HTTPStatusError("403", request=MagicMock(), response=fake_resp)
    )
    fake_client = AsyncMock()
    fake_client.get = AsyncMock(return_value=fake_resp)
    fake_client.__aenter__.return_value = fake_client
    fake_client.__aexit__.return_value = None

    with patch("app.whop.image_store.httpx.AsyncClient", return_value=fake_client):
        filename = await download_image("msg_x", "https://example.com/x", tmp_path)

    assert filename is None
    assert not (tmp_path / "chat-images").exists() or not any(
        (tmp_path / "chat-images").iterdir()
    )


async def test_download_image_returns_none_on_timeout(tmp_path: Path) -> None:
    fake_client = AsyncMock()
    fake_client.get = AsyncMock(side_effect=httpx.TimeoutException("timed out"))
    fake_client.__aenter__.return_value = fake_client
    fake_client.__aexit__.return_value = None

    with patch("app.whop.image_store.httpx.AsyncClient", return_value=fake_client):
        filename = await download_image("msg_y", "https://example.com/x", tmp_path)

    assert filename is None


# ---------------------------------------------------------------------------
# Integration tests: handler downloads image + writes row
# ---------------------------------------------------------------------------


async def test_handler_downloads_image_and_writes_row(
    tmp_path: Path,
    session_factory: object,
) -> None:
    bus = EventBus()
    register_chat_writer(bus, session_factory, tmp_path)  # type: ignore[arg-type]

    fake_resp = MagicMock(
        status_code=200, content=b"PNG", headers={"Content-Type": "image/png"}
    )
    fake_resp.raise_for_status = MagicMock()
    fake_client = AsyncMock()
    fake_client.get = AsyncMock(return_value=fake_resp)
    fake_client.__aenter__.return_value = fake_client
    fake_client.__aexit__.return_value = None

    msg = Message(
        id="m_int_1",
        content="caption",
        raw_content="caption",
        author="alice",
        posted_at=datetime(2026, 5, 21, tzinfo=UTC),
        received_at=datetime(2026, 5, 21, tzinfo=UTC),
        source="chat",
        image_url="https://example.com/x.png",
    )
    payload = ChatMessagePayload(
        page_id="page_1", message=msg, is_historical=False
    )

    with patch("app.whop.image_store.httpx.AsyncClient", return_value=fake_client):
        await bus.publish(Event(topic=Topics.CHAT_MESSAGE_RECEIVED, payload=payload))
        await bus.wait_idle(timeout=2)

    # File written
    assert (tmp_path / "chat-images" / "m_int_1.png").read_bytes() == b"PNG"

    # Row written with image_filename
    async with session_scope(session_factory) as session:  # type: ignore[arg-type]
        row = await session.get(ChatMessageRow, "m_int_1")
        assert row is not None
        assert row.image_filename == "m_int_1.png"


async def test_handler_skips_row_when_image_only_and_download_fails(
    tmp_path: Path,
    session_factory: object,
) -> None:
    """Image-only message (content="") + download failure → row NOT written.

    Guards the second half of the ``and`` in the skip guard at
    chat_writer.py:148 — a future change to ``or`` would let empty
    rows leak into the DB and produce ghost bubbles in the UI."""
    bus = EventBus()
    register_chat_writer(bus, session_factory, tmp_path)  # type: ignore[arg-type]

    fake_client = AsyncMock()
    fake_client.get = AsyncMock(side_effect=httpx.TimeoutException("timed out"))
    fake_client.__aenter__.return_value = fake_client
    fake_client.__aexit__.return_value = None

    msg = Message(
        id="m_image_only_failed",
        content="",
        raw_content="",
        author="alice",
        posted_at=datetime(2026, 5, 21, tzinfo=UTC),
        received_at=datetime(2026, 5, 21, tzinfo=UTC),
        source="chat",
        image_url="https://example.com/expired.png",
    )
    payload = ChatMessagePayload(
        page_id="page_1", message=msg, is_historical=False
    )

    with patch("app.whop.image_store.httpx.AsyncClient", return_value=fake_client):
        await bus.publish(Event(topic=Topics.CHAT_MESSAGE_RECEIVED, payload=payload))
        await bus.wait_idle(timeout=2)

    # No image file
    assert not (tmp_path / "chat-images").exists() or not any(
        (tmp_path / "chat-images").iterdir()
    )

    # No row in DB — message was correctly skipped
    async with session_scope(session_factory) as session:  # type: ignore[arg-type]
        row = await session.get(ChatMessageRow, "m_image_only_failed")
        assert row is None


async def test_handler_writes_row_with_text_when_image_download_fails(
    tmp_path: Path,
    session_factory: object,
) -> None:
    """Message has BOTH text caption AND image_url, but download fails:
    row must still be written with content set and image_filename=None.

    Guards the ``and`` in the skip-empty rule at chat_writer.py:146 — a
    future change to ``or`` would silently drop these rows."""
    bus = EventBus()
    register_chat_writer(bus, session_factory, tmp_path)  # type: ignore[arg-type]

    fake_client = AsyncMock()
    fake_client.get = AsyncMock(side_effect=httpx.TimeoutException("timed out"))
    fake_client.__aenter__.return_value = fake_client
    fake_client.__aexit__.return_value = None

    msg = Message(
        id="m_text_with_failed_image",
        content="here is the caption",
        raw_content="here is the caption",
        author="alice",
        posted_at=datetime(2026, 5, 21, tzinfo=UTC),
        received_at=datetime(2026, 5, 21, tzinfo=UTC),
        source="chat",
        image_url="https://example.com/expired.png",
    )
    payload = ChatMessagePayload(
        page_id="page_1", message=msg, is_historical=False
    )

    with patch("app.whop.image_store.httpx.AsyncClient", return_value=fake_client):
        await bus.publish(Event(topic=Topics.CHAT_MESSAGE_RECEIVED, payload=payload))
        await bus.wait_idle(timeout=2)

    assert not (tmp_path / "chat-images" / "m_text_with_failed_image.png").exists()

    async with session_scope(session_factory) as session:  # type: ignore[arg-type]
        row = await session.get(ChatMessageRow, "m_text_with_failed_image")
        assert row is not None
        assert row.content == "here is the caption"
        assert row.image_filename is None
