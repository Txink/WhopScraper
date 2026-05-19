"""Tests for WhopPageEntry.parent_chat_id serialization."""
from datetime import UTC, datetime

import pytest

from app.core.config import Settings
from app.core.event_bus import EventBus
from app.whop.registry import WhopPageEntry, WhopRegistry
from app.whop.page_settings import default_settings_for


@pytest.fixture
def registry(tmp_path) -> WhopRegistry:
    return WhopRegistry(
        bus=EventBus(),
        settings=Settings(
            app_token="test",
            database_url="sqlite+aiosqlite:///:memory:",
        ),
        pages_file=tmp_path / "pages.json",
    )


def test_to_dict_includes_parent_chat_id_when_set():
    entry = WhopPageEntry(
        id="abc123",
        url="https://whop.com/c/foo",
        source="stock",
        name="TSLL 监听",
        added_at=datetime(2026, 5, 20, tzinfo=UTC),
        settings=default_settings_for("stock"),
        parent_chat_id="parent_xyz",
    )
    d = entry.to_dict()
    assert d["parent_chat_id"] == "parent_xyz"


def test_to_dict_emits_none_when_unset():
    entry = WhopPageEntry(
        id="abc123",
        url="https://whop.com/c/foo",
        source="stock",
        name="TSLL 监听",
        added_at=datetime(2026, 5, 20, tzinfo=UTC),
        settings=default_settings_for("stock"),
    )
    d = entry.to_dict()
    assert "parent_chat_id" in d
    assert d["parent_chat_id"] is None


def test_from_dict_legacy_missing_field_defaults_to_none():
    legacy = {
        "id": "abc123",
        "url": "https://whop.com/c/foo",
        "source": "stock",
        "name": "TSLL 监听",
        "added_at": "2026-05-20T00:00:00+00:00",
        "settings": {"dedupe_processed_messages": True},
    }
    entry = WhopPageEntry.from_dict(legacy)
    assert entry.parent_chat_id is None


def test_from_dict_explicit_none_returns_none():
    """Explicit null in JSON (key present, value None) must also deserialise to None."""
    d = {
        "id": "abc123",
        "url": "https://whop.com/c/foo",
        "source": "stock",
        "name": "TSLL 监听",
        "added_at": "2026-05-20T00:00:00+00:00",
        "settings": {"dedupe_processed_messages": True},
        "parent_chat_id": None,
    }
    entry = WhopPageEntry.from_dict(d)
    assert entry.parent_chat_id is None


def test_from_dict_roundtrip_preserves_parent_chat_id():
    src = WhopPageEntry(
        id="abc123",
        url="https://whop.com/c/foo",
        source="stock",
        name="TSLL 监听",
        added_at=datetime(2026, 5, 20, tzinfo=UTC),
        settings=default_settings_for("stock"),
        parent_chat_id="parent_xyz",
    )
    dst = WhopPageEntry.from_dict(src.to_dict())
    assert dst.parent_chat_id == "parent_xyz"


@pytest.mark.asyncio
async def test_add_page_with_valid_parent(registry):
    parent = await registry.add_page(
        url="https://whop.com/c/chat-1", source="chat", name="alpha-room"
    )
    child = await registry.add_page(
        url="https://whop.com/c/stock-1",
        source="stock",
        name="TSLL 监听",
        parent_chat_id=parent.id,
    )
    assert child.parent_chat_id == parent.id


@pytest.mark.asyncio
async def test_add_page_rejects_parent_not_found(registry):
    with pytest.raises(ValueError, match="parent_chat_id"):
        await registry.add_page(
            url="https://whop.com/c/stock-1",
            source="stock",
            name="TSLL",
            parent_chat_id="nonexistent",
        )


@pytest.mark.asyncio
async def test_add_page_rejects_non_chat_parent(registry):
    parent = await registry.add_page(
        url="https://whop.com/c/stock-parent", source="stock", name="Standalone TSLL"
    )
    with pytest.raises(ValueError, match="parent must be source=chat"):
        await registry.add_page(
            url="https://whop.com/c/stock-1",
            source="stock",
            name="TSLL",
            parent_chat_id=parent.id,
        )


@pytest.mark.asyncio
async def test_add_page_rejects_nested_sub(registry):
    chat = await registry.add_page(url="https://whop.com/c/chat-1", source="chat", name="c")
    sub = await registry.add_page(
        url="https://whop.com/c/stock-1", source="stock", name="s", parent_chat_id=chat.id
    )
    with pytest.raises(ValueError, match="cannot nest"):
        await registry.add_page(
            url="https://whop.com/c/stock-2",
            source="stock",
            name="s2",
            parent_chat_id=sub.id,
        )


@pytest.mark.asyncio
async def test_add_page_rejects_chat_as_sub(registry):
    chat = await registry.add_page(url="https://whop.com/c/chat-1", source="chat", name="c")
    with pytest.raises(ValueError, match="sub-monitor source must be stock or option"):
        await registry.add_page(
            url="https://whop.com/c/chat-2",
            source="chat",
            name="c2",
            parent_chat_id=chat.id,
        )
