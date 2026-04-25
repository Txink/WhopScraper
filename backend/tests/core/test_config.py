"""Tests for core/config.py Settings and get_settings."""

from __future__ import annotations

import pytest

from app.core.config import Settings, get_settings


class TestSettingsDefaults:
    def test_database_url_default(self) -> None:
        """Default DATABASE_URL must match the sqlite aiosqlite path from .env.example."""
        s = Settings()
        assert s.database_url == "sqlite+aiosqlite:///./data/signals.db"

    def test_get_settings_returns_settings_instance(self) -> None:
        s = get_settings()
        assert isinstance(s, Settings)

    def test_get_settings_cached(self) -> None:
        """Repeated calls return the same instance."""
        get_settings.cache_clear()
        a = get_settings()
        b = get_settings()
        assert a is b


class TestSettingsEnvOverride:
    def test_database_url_env_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """monkeypatch.setenv overrides DATABASE_URL when cache is cleared."""
        monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
        get_settings.cache_clear()
        s = get_settings()
        assert s.database_url == "sqlite+aiosqlite:///:memory:"
        # cleanup: clear cache so later tests don't get the patched value
        get_settings.cache_clear()

    def test_log_level_env_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LOG_LEVEL", "DEBUG")
        get_settings.cache_clear()
        s = get_settings()
        assert s.log_level == "DEBUG"
        get_settings.cache_clear()
