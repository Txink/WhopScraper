"""LongPortClient.today_orders — SDK call + ticker filter + Noop empty."""
from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.broker.longport_client import LongPortClient
from app.broker.noop_client import NoopBrokerClient


def _make_client() -> tuple[LongPortClient, MagicMock]:
    trade_ctx = MagicMock()
    client = LongPortClient.__new__(LongPortClient)
    client._trade_ctx = trade_ctx
    client._dry_run = False
    client._account_id = "acct-1"
    client._account_label = "Paper"
    client._is_paper = True
    return client, trade_ctx


def test_today_orders_filters_by_ticker() -> None:
    client, trade_ctx = _make_client()
    now = datetime(2026, 5, 25, 10, 0, tzinfo=UTC)
    trade_ctx.today_orders.return_value = [
        SimpleNamespace(
            order_id="ord-aapl", symbol="AAPL.US", side="Buy",
            order_type="LO", price=199.0, quantity=200, executed_quantity=0,
            status="NewStatus", submitted_at=now,
        ),
        SimpleNamespace(
            order_id="ord-nvda", symbol="NVDA.US", side="Sell",
            order_type="LO", price=500.0, quantity=10, executed_quantity=0,
            status="NewStatus", submitted_at=now,
        ),
    ]
    rows = client.today_orders(ticker="AAPL")
    assert len(rows) == 1
    assert rows[0]["order_id"] == "ord-aapl"
    assert rows[0]["ticker"] == "AAPL"
    assert rows[0]["status"] == "NewStatus"


def test_today_orders_unfiltered_returns_all() -> None:
    client, trade_ctx = _make_client()
    trade_ctx.today_orders.return_value = []
    assert client.today_orders() == []


def test_noop_today_orders_returns_empty() -> None:
    assert NoopBrokerClient().today_orders() == []
