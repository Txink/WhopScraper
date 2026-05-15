"""Tests for app.broker.config — LongPortConfig (multi-account era) and the
``load_longport_config_from_runtime`` factory."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from app.broker.config import LongPortConfig, load_longport_config_from_runtime
from app.broker.runtime_settings import LongPortAccount, LongPortRuntimeSettings
from app.core.config import Settings


class TestLongPortConfigDataclass:
    def test_basic_fields(self) -> None:
        cfg = LongPortConfig(account_id="acct-1", label="主账户")
        assert cfg.account_id == "acct-1"
        assert cfg.label == "主账户"
        assert cfg.auto_trade is True
        assert cfg.dry_run is True

    def test_dry_run_override(self) -> None:
        cfg = LongPortConfig(account_id="acct-1", dry_run=False)
        assert cfg.dry_run is False

    def test_frozen(self) -> None:
        cfg = LongPortConfig(account_id="acct-1")
        with pytest.raises((AttributeError, TypeError)):
            cfg.account_id = "other"  # type: ignore[misc]


def _runtime_with_accounts(
    *,
    accounts: list[tuple[str, str]] = (),
    active: str | None = None,
) -> LongPortRuntimeSettings:
    return LongPortRuntimeSettings(
        active_account_id=active,
        accounts=[
            LongPortAccount(account_id=cid, label=lbl, authorized=True)
            for cid, lbl in accounts
        ],
        auto_trade=True,
        region="cn",
        dry_run=True,
    )


class TestLoadFromRuntime:
    def test_loads_when_active_account_authorized(self) -> None:
        runtime = _runtime_with_accounts(
            accounts=[("acct-paper", "paper")],
            active="acct-paper",
        )
        with patch("app.broker.config.is_authorized", return_value=True):
            cfg = load_longport_config_from_runtime(runtime, settings=Settings())
        assert cfg.account_id == "acct-paper"
        assert cfg.label == "paper"

    def test_no_active_account_raises(self) -> None:
        runtime = _runtime_with_accounts()
        with pytest.raises(ValueError, match="No active"):
            load_longport_config_from_runtime(runtime, settings=Settings())

    def test_unauthorized_active_raises(self) -> None:
        runtime = _runtime_with_accounts(
            accounts=[("acct-1", "主")],
            active="acct-1",
        )
        with patch("app.broker.config.is_authorized", return_value=False):
            with pytest.raises(ValueError, match="not authorized"):
                load_longport_config_from_runtime(runtime, settings=Settings())
