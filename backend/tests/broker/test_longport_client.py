"""Tests for app.broker.longport_client.LongPortClient.

All tests use dry_run=True or mock the SDK contexts so no network
connections are ever made.
"""
from __future__ import annotations

from typing import Any
from unittest.mock import patch

from app.broker.config import LongPortConfig
from app.broker.longport_client import LongPortClient


def _dry_config(**overrides: Any) -> LongPortConfig:
    """Return a minimal LongPortConfig with dry_run=True."""
    defaults: dict[str, Any] = dict(
        mode="paper",
        app_key="test-key",
        app_secret="test-secret",
        access_token="test-token",
        dry_run=True,
    )
    defaults.update(overrides)
    return LongPortConfig(**defaults)


# Patch both SDK context classes so the constructor never opens a connection.
_SDK_PATCHES = (
    patch("app.broker.longport_client.QuoteContext"),
    patch("app.broker.longport_client.TradeContext"),
    patch("app.broker.longport_client.LPConfig"),
)


class TestDryRun:
    """dry_run=True paths must never call SDK methods."""

    def _make_client(self, **overrides: Any) -> LongPortClient:
        cfg = _dry_config(**overrides)
        with _SDK_PATCHES[0], _SDK_PATCHES[1], _SDK_PATCHES[2]:
            client = LongPortClient(cfg)
        return client

    def test_submit_option_order_returns_dry_id(self) -> None:
        client = self._make_client()
        order_id = client.submit_option_order(
            symbol="AAPL260117C150000.US",
            side="BUY",
            quantity=1,
            price=3.50,
            order_type="LIMIT",
        )
        assert order_id.startswith("DRY-")

    def test_submit_stock_order_returns_dry_id(self) -> None:
        client = self._make_client()
        order_id = client.submit_stock_order(
            symbol="AAPL.US",
            side="BUY",
            quantity=100,
            price=180.0,
            order_type="LIMIT",
        )
        assert order_id.startswith("DRY-")

    def test_dry_ids_are_unique(self) -> None:
        client = self._make_client()
        ids = {
            client.submit_option_order(
                symbol="AAPL260117C150000.US",
                side="BUY",
                quantity=1,
                price=3.0,
                order_type="LIMIT",
            )
            for _ in range(5)
        }
        assert len(ids) == 5  # each call produces a distinct id

    def test_market_order_dry_run(self) -> None:
        client = self._make_client()
        order_id = client.submit_stock_order(
            symbol="TSLA.US",
            side="SELL",
            quantity=10,
            price=None,
            order_type="MARKET",
        )
        assert order_id.startswith("DRY-")


class TestProperties:
    """Properties reflect config values."""

    def _make_client(self, **overrides: Any) -> LongPortClient:
        cfg = _dry_config(**overrides)
        with _SDK_PATCHES[0], _SDK_PATCHES[1], _SDK_PATCHES[2]:
            return LongPortClient(cfg)

    def test_is_paper_true_for_paper_mode(self) -> None:
        assert self._make_client(mode="paper").is_paper is True

    def test_is_paper_false_for_real_mode(self) -> None:
        assert self._make_client(mode="real").is_paper is False

    def test_dry_run_property(self) -> None:
        assert self._make_client(dry_run=True).dry_run is True

    def test_dry_run_false_property(self) -> None:
        assert self._make_client(dry_run=False).dry_run is False


class TestClose:
    """close() must be idempotent."""

    def _make_client(self) -> LongPortClient:
        cfg = _dry_config()
        with _SDK_PATCHES[0], _SDK_PATCHES[1], _SDK_PATCHES[2]:
            return LongPortClient(cfg)

    def test_close_is_idempotent(self) -> None:
        client = self._make_client()
        client.close()  # first call
        client.close()  # must not raise

    def test_close_nullifies_contexts(self) -> None:
        client = self._make_client()
        client.close()
        assert client._quote_ctx is None
        assert client._trade_ctx is None


class TestPushSubscription:
    """subscribe_order_push registers handlers; SDK callback fans out."""

    def _make_client(self) -> LongPortClient:
        cfg = _dry_config()
        with _SDK_PATCHES[0], _SDK_PATCHES[1], _SDK_PATCHES[2]:
            return LongPortClient(cfg)

    def test_subscribe_and_fanout(self) -> None:
        client = self._make_client()
        calls: list[Any] = []
        client.subscribe_order_push(calls.append)

        fake_event = object()
        client._on_order_changed(fake_event)

        assert calls == [fake_event]

    def test_multiple_subscribers(self) -> None:
        client = self._make_client()
        a: list[Any] = []
        b: list[Any] = []
        client.subscribe_order_push(a.append)
        client.subscribe_order_push(b.append)

        ev = object()
        client._on_order_changed(ev)

        assert a == [ev]
        assert b == [ev]

    def test_failing_handler_does_not_kill_others(self) -> None:
        client = self._make_client()
        results: list[str] = []

        def bad_handler(_: Any) -> None:
            raise RuntimeError("boom")

        def good_handler(_: Any) -> None:
            results.append("ok")

        client.subscribe_order_push(bad_handler)
        client.subscribe_order_push(good_handler)

        client._on_order_changed(object())  # must not propagate exception
        assert results == ["ok"]
