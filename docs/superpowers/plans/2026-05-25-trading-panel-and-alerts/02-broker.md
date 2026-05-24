# Task 2: Broker `replace_order` + `today_orders`

**Files:**
- Modify: `backend/app/broker/broker_client.py` (Protocol)
- Modify: `backend/app/broker/longport_client.py`
- Modify: `backend/app/broker/noop_client.py`
- Test: `backend/tests/broker/test_replace_order.py`
- Test: `backend/tests/broker/test_today_orders.py`

## Steps

- [ ] **Step 1: Write failing tests**

`backend/tests/broker/test_replace_order.py`:

```python
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
    # Should not raise; should log internally; no broker side effect.
    client.replace_order("ord-1", quantity=100, price=10.0)
```

`backend/tests/broker/test_today_orders.py`:

```python
"""LongPortClient.today_orders — SDK call + ticker filter + Noop empty."""
from __future__ import annotations

from datetime import datetime, timezone
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
    now = datetime(2026, 5, 25, 10, 0, tzinfo=timezone.utc)
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
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
cd backend
uv run pytest tests/broker/test_replace_order.py tests/broker/test_today_orders.py -v
```

Expected: AttributeError — methods don't exist.

- [ ] **Step 3: Extend BrokerClient Protocol**

Append to `backend/app/broker/broker_client.py` inside the `BrokerClient` Protocol class:

```python
    def replace_order(
        self,
        order_id: str,
        *,
        quantity: int | None = None,
        price: float | None = None,
    ) -> None:
        """Modify an existing live order; preserves queue priority.

        At least one of quantity or price must be supplied. Raises
        ValueError if neither is given; lets SDK exceptions propagate
        for caller-side translation to HTTP 409/502.
        """
        ...

    def today_orders(
        self, *, ticker: str | None = None
    ) -> list[dict[str, Any]]:
        """Return today's orders across all states (pending, partial,
        filled, cancelled, rejected). Optional client-side ticker filter.
        Schema: ``{order_id, symbol, ticker, side, order_type, price,
        quantity, executed_quantity, status, submitted_at}``.
        """
        ...
```

- [ ] **Step 4: Implement on LongPortClient**

Append to `backend/app/broker/longport_client.py`:

```python
    def replace_order(
        self,
        order_id: str,
        *,
        quantity: int | None = None,
        price: float | None = None,
    ) -> None:
        if quantity is None and price is None:
            raise ValueError("replace_order requires quantity or price")
        if self._dry_run:
            logger.info(
                "[DRY RUN] replace_order order_id=%s qty=%s price=%s — skipped",
                order_id, quantity, price,
            )
            return
        kwargs: dict[str, Any] = {"order_id": order_id}
        if quantity is not None:
            kwargs["quantity"] = quantity
        if price is not None:
            kwargs["price"] = price
        self._trade_ctx.replace_order(**kwargs)

    def today_orders(
        self, *, ticker: str | None = None
    ) -> list[dict[str, Any]]:
        raw = self._trade_ctx.today_orders() or []
        out: list[dict[str, Any]] = []
        for o in raw:
            symbol = getattr(o, "symbol", None) or ""
            tkr = symbol.split(".")[0] if symbol else ""
            if ticker is not None and tkr != ticker:
                continue
            out.append({
                "order_id": getattr(o, "order_id", ""),
                "symbol": symbol,
                "ticker": tkr,
                "side": str(getattr(o, "side", "")),
                "order_type": str(getattr(o, "order_type", "")),
                "price": float(getattr(o, "price", 0.0) or 0.0),
                "quantity": int(getattr(o, "quantity", 0) or 0),
                "executed_quantity": int(getattr(o, "executed_quantity", 0) or 0),
                "status": str(getattr(o, "status", "")),
                "submitted_at": getattr(o, "submitted_at", None),
            })
        return out
```

- [ ] **Step 5: Implement Noop versions**

Append to `backend/app/broker/noop_client.py`:

```python
    def replace_order(
        self,
        order_id: str,
        *,
        quantity: int | None = None,
        price: float | None = None,
    ) -> None:
        logger.info(
            "[NOOP] replace_order order_id=%s qty=%s price=%s",
            order_id, quantity, price,
        )

    def today_orders(
        self, *, ticker: str | None = None
    ) -> list[dict[str, Any]]:
        return []
```

- [ ] **Step 6: Verify tests pass**

```bash
cd backend
uv run pytest tests/broker/test_replace_order.py tests/broker/test_today_orders.py -v
uv run mypy app
uv run ruff check .
```

Expected: 7 passed; mypy clean; ruff clean.

- [ ] **Step 7: Commit**

```bash
git add backend/app/broker/broker_client.py backend/app/broker/longport_client.py \
        backend/app/broker/noop_client.py backend/tests/broker/test_replace_order.py \
        backend/tests/broker/test_today_orders.py
git commit -m "$(cat <<'EOF'
feat(broker): replace_order + today_orders

LongPort SDK supports both natively; surface them on BrokerClient
Protocol so the upcoming orders service can drive manual order
modify/list flows. Noop stubs preserve no-LongPort fallback.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```
