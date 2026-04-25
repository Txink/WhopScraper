"""Tests for app.broker.config — LongPortConfig and load_longport_config()."""
from __future__ import annotations

import pytest

from app.broker.config import LongPortConfig, load_longport_config


class TestLongPortConfigDataclass:
    """Unit-test the dataclass itself (no I/O)."""

    def test_paper_config_fields(self) -> None:
        cfg = LongPortConfig(
            mode="paper",
            app_key="pk",
            app_secret="ps",
            access_token="pt",
        )
        assert cfg.mode == "paper"
        assert cfg.app_key == "pk"
        assert cfg.dry_run is True  # default
        assert cfg.auto_trade is True  # default

    def test_real_config_fields(self) -> None:
        cfg = LongPortConfig(
            mode="real",
            app_key="rk",
            app_secret="rs",
            access_token="rt",
            dry_run=False,
        )
        assert cfg.mode == "real"
        assert cfg.dry_run is False

    def test_frozen(self) -> None:
        cfg = LongPortConfig(
            mode="paper", app_key="k", app_secret="s", access_token="t"
        )
        with pytest.raises((AttributeError, TypeError)):
            cfg.app_key = "other"  # type: ignore[misc]


class TestLoadLongportConfig:
    """Tests for the load_longport_config() factory via Settings patches."""

    def test_paper_mode_loads_paper_credentials(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LONGPORT_MODE", "paper")
        monkeypatch.setenv("LONGPORT_PAPER_APP_KEY", "paper-key")
        monkeypatch.setenv("LONGPORT_PAPER_APP_SECRET", "paper-secret")
        monkeypatch.setenv("LONGPORT_PAPER_ACCESS_TOKEN", "paper-token")
        # Bust the settings cache so our env vars take effect.
        from app.core.config import get_settings
        get_settings.cache_clear()

        cfg = load_longport_config()

        assert cfg.mode == "paper"
        assert cfg.app_key == "paper-key"
        assert cfg.app_secret == "paper-secret"
        assert cfg.access_token == "paper-token"

    def test_real_mode_loads_real_credentials(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LONGPORT_MODE", "real")
        monkeypatch.setenv("LONGPORT_REAL_APP_KEY", "real-key")
        monkeypatch.setenv("LONGPORT_REAL_APP_SECRET", "real-secret")
        monkeypatch.setenv("LONGPORT_REAL_ACCESS_TOKEN", "real-token")
        from app.core.config import get_settings
        get_settings.cache_clear()

        cfg = load_longport_config()

        assert cfg.mode == "real"
        assert cfg.app_key == "real-key"

    def test_missing_paper_key_raises_value_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LONGPORT_MODE", "paper")
        monkeypatch.setenv("LONGPORT_PAPER_APP_KEY", "")
        monkeypatch.setenv("LONGPORT_PAPER_APP_SECRET", "s")
        monkeypatch.setenv("LONGPORT_PAPER_ACCESS_TOKEN", "t")
        from app.core.config import get_settings
        get_settings.cache_clear()

        with pytest.raises(ValueError, match="LONGPORT_PAPER_APP_KEY"):
            load_longport_config()

    def test_missing_real_token_raises_value_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LONGPORT_MODE", "real")
        monkeypatch.setenv("LONGPORT_REAL_APP_KEY", "k")
        monkeypatch.setenv("LONGPORT_REAL_APP_SECRET", "s")
        monkeypatch.setenv("LONGPORT_REAL_ACCESS_TOKEN", "")
        from app.core.config import get_settings
        get_settings.cache_clear()

        with pytest.raises(ValueError, match="LONGPORT_REAL_ACCESS_TOKEN"):
            load_longport_config()

    def test_invalid_mode_raises_value_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LONGPORT_MODE", "sandbox")
        from app.core.config import get_settings
        get_settings.cache_clear()

        with pytest.raises(ValueError, match="LONGPORT_MODE"):
            load_longport_config()
