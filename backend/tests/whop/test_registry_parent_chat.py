"""Tests for WhopPageEntry.parent_chat_id serialization."""
from datetime import UTC, datetime

from app.whop.registry import WhopPageEntry
from app.whop.page_settings import default_settings_for


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
