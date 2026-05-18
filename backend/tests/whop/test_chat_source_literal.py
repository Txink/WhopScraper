from __future__ import annotations

from app.whop.page_settings import default_settings_for


def test_default_settings_for_chat_source_does_not_raise() -> None:
    settings = default_settings_for("chat")
    # Defaults inherited from existing PageSettings remain unchanged:
    assert settings.dedupe_processed_messages is True


def test_default_settings_for_chat_includes_chat_fields() -> None:
    settings = default_settings_for("chat")
    assert settings.watched_senders == []
    assert settings.chat_card_max_msgs == 5


def test_default_settings_for_stock_also_has_chat_fields_with_defaults() -> None:
    """All sources share the PageSettings dataclass, so the chat fields exist
    with default values on stock/option pages too — they just go unused."""
    settings = default_settings_for("stock")
    assert settings.watched_senders == []
    assert settings.chat_card_max_msgs == 5
