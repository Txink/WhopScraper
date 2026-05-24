"""LongPortClient.replace_order — SDK call wiring + dry-run + error paths."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.broker.longport_client import LongPortClient
from app.broker.noop_client import NoopBrokerClient


def _make_client(dry_run: bool = False) -> tuple[LongPortClient, MagicMock]:
    trade_ctx = MagicMock()
    client = LongPortClient.__new__(LongPortClient)
    client._trade_ctx = trade_ctx
    client._dry_run = dry_run
    client._account_id = "acct-1"
    client._account_label = "Paper"
    client._is_paper = True
    return client, trade_ctx


def test_replace_order_calls_sdk_with_price_and_quantity() -> None:
    client, trade_ctx = _make_client()
    client.replace_order("ord-1", quantity=300, price=199.50)
    trade_ctx.replace_order.assert_called_once_with(
        order_id="ord-1", quantity=300, price=199.50
    )


def test_replace_order_dry_run_skips_sdk() -> None:
    client, trade_ctx = _make_client(dry_run=True)
    client.replace_order("ord-1", quantity=200, price=None)
    trade_ctx.replace_order.assert_not_called()


def test_replace_order_requires_at_least_one_field() -> None:
    client, _ = _make_client()
    with pytest.raises(ValueError, match="quantity or price"):
        client.replace_order("ord-1")


def test_replace_order_propagates_sdk_exception() -> None:
    client, trade_ctx = _make_client()
    trade_ctx.replace_order.side_effect = RuntimeError("order finished")
    with pytest.raises(RuntimeError, match="order finished"):
        client.replace_order("ord-1", price=199.0)


def test_noop_replace_order_is_silent() -> None:
    client = NoopBrokerClient()
    client.replace_order("ord-1", quantity=100, price=10.0)
