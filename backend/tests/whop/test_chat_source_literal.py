from __future__ import annotations

from app.whop.page_settings import default_settings_for


def test_default_settings_for_chat_source_does_not_raise() -> None:
    settings = default_settings_for("chat")
    # Defaults inherited from existing PageSettings remain unchanged:
    assert settings.dedupe_processed_messages is True
