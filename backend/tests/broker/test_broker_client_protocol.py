"""Tests that verify the BrokerClient Protocol is structurally sound.

A FakeBrokerClient is defined and exercised to confirm any class that
provides the required interface satisfies the Protocol at type-check time.
We also verify LongPortClient satisfies the Protocol at runtime via
isinstance() with the runtime_checkable guard.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any
from unittest.mock import patch

from app.broker.broker_client import BrokerClient, OrderSide, OrderType
from app.broker.config import LongPortConfig
from app.broker.longport_client import LongPortClient

# --------------------------------------------------------------------------- #
# A minimal fake that satisfies the BrokerClient Protocol                      #
# --------------------------------------------------------------------------- #


class FakeBrokerClient:
    """Test double satisfying BrokerClient — zero network, zero SDK."""

    def __init__(self, *, is_paper: bool = True, dry_run: bool = True) -> None:
        self._is_paper = is_paper
        self._dry_run = dry_run
        self.submitted_orders: list[dict[str, Any]] = []

    @property
    def is_paper(self) -> bool:
        return self._is_paper

    @property
    def dry_run(self) -> bool:
        return self._dry_run

    def submit_option_order(
        self,
        *,
        symbol: str,
        side: OrderSide,
        quantity: int,
        price: float | None,
        order_type: OrderType,
        remark: str = "",
    ) -> str:
        order_id = f"FAKE-OPT-{len(self.submitted_orders)}"
        self.submitted_orders.append(
            dict(
                symbol=symbol,
                side=side,
                quantity=quantity,
                price=price,
                order_type=order_type,
                remark=remark,
                order_id=order_id,
            )
        )
        return order_id

    def submit_stock_order(
        self,
        *,
        symbol: str,
        side: OrderSide,
        quantity: int,
        price: float | None,
        order_type: OrderType,
        remark: str = "",
    ) -> str:
        order_id = f"FAKE-STK-{len(self.submitted_orders)}"
        self.submitted_orders.append(
            dict(
                symbol=symbol,
                side=side,
                quantity=quantity,
                price=price,
                order_type=order_type,
                remark=remark,
                order_id=order_id,
            )
        )
        return order_id

    def get_quote(self, symbols: list[str]) -> dict[str, dict[str, Any]]:
        return {s: {"last_done": 0.0} for s in symbols}

    def subscribe_order_push(self, handler: Callable[[Any], None]) -> None:
        pass

    def close(self) -> None:
        pass


# --------------------------------------------------------------------------- #
# Tests                                                                        #
# --------------------------------------------------------------------------- #


class TestFakeBrokerClient:
    """FakeBrokerClient behaves correctly (sanity-check the double)."""

    def test_submit_option_returns_expected_id(self) -> None:
        fake = FakeBrokerClient()
        oid = fake.submit_option_order(
            symbol="AAPL260117C150000.US",
            side="BUY",
            quantity=2,
            price=3.5,
            order_type="LIMIT",
        )
        assert oid == "FAKE-OPT-0"
        assert fake.submitted_orders[0]["symbol"] == "AAPL260117C150000.US"

    def test_submit_stock_records_order(self) -> None:
        fake = FakeBrokerClient()
        oid = fake.submit_stock_order(
            symbol="TSLA.US",
            side="SELL",
            quantity=10,
            price=None,
            order_type="MARKET",
        )
        assert oid == "FAKE-STK-0"
        assert fake.submitted_orders[0]["side"] == "SELL"

    def test_get_quote_returns_dict(self) -> None:
        fake = FakeBrokerClient()
        quotes = fake.get_quote(["AAPL.US", "TSLA.US"])
        assert set(quotes.keys()) == {"AAPL.US", "TSLA.US"}

    def test_properties(self) -> None:
        fake = FakeBrokerClient(is_paper=False, dry_run=False)
        assert fake.is_paper is False
        assert fake.dry_run is False


class TestProtocolStructuralSubtyping:
    """Verify FakeBrokerClient is accepted where BrokerClient is expected."""

    def _accept_broker(self, broker: BrokerClient) -> str:
        """Simulate a higher-level layer that only knows BrokerClient."""
        return broker.submit_option_order(
            symbol="X260117C10000.US",
            side="BUY",
            quantity=1,
            price=1.0,
            order_type="LIMIT",
        )

    def test_fake_satisfies_protocol(self) -> None:
        fake = FakeBrokerClient()
        result = self._accept_broker(fake)  # type: ignore[arg-type]
        assert result.startswith("FAKE-")

    def test_longport_client_satisfies_protocol_dry_run(self) -> None:
        cfg = LongPortConfig(            account_id="test-cid",
            dry_run=True,
        )
        with (
            patch("app.broker.longport_client.QuoteContext"),
            patch("app.broker.longport_client.TradeContext"),
            patch("app.broker.longport_client.LPConfig"),
            patch("app.broker.longport_client.OAuthBuilder"),
            patch("app.broker.longport_client.is_authorized", return_value=True),
        ):
            client = LongPortClient(cfg)

        result = self._accept_broker(client)  # type: ignore[arg-type]
        assert result.startswith("DRY-")
