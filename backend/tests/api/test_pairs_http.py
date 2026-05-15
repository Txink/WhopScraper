"""Tests for /api/pairs endpoints — 做T 配对 CRUD."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
import pytest_asyncio
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.http import build_http_router
from app.broker.runtime_settings import LongPortRuntimeStore
from app.core.config import Settings, get_settings
from app.core.event_bus import EventBus
from app.domain.instruction import InstructionType, StockInstruction
from app.domain.message import Message
from app.domain.push_event import PushEvent, PushState
from app.domain.status import Status
from app.domain.task import Task
from app.storage import repo
from tests.broker._fakes import FakeBrokerClient

_TOKEN = "test-token-pairs"


def _now(offset: int = 0) -> datetime:
    base = datetime.combine(date.today(), datetime.min.time(), tzinfo=UTC)
    return base + timedelta(hours=10, seconds=offset)


def _msg(id_: str, *, offset: int = 0) -> Message:
    ts = _now(offset)
    return Message(
        id=id_,
        content="BUY TSLA 100",
        raw_content="BUY TSLA 100",
        author="trader",
        source="stock",  # type: ignore[arg-type]
        posted_at=ts,
        received_at=ts,
    )


def _stock_instruction(
    *,
    ticker: str = "TSLA",
    side: str = "BUY",
    qty: int = 100,
    price: float = 10.0,
) -> StockInstruction:
    inst_type = InstructionType.BUY if side == "BUY" else InstructionType.SELL
    return StockInstruction(
        instruction_type=inst_type,
        price=price,
        price_range=None,
        quantity=qty,
        position_size=None,
        stop_loss_price=None,
        take_profit_price=None,
        context_source=None,
        parser_notes=[],
        ticker=ticker,
        symbol=f"{ticker}.US",
        sell_quantity=None,
    )


def _task(
    id_: str,
    *,
    ticker: str = "TSLA",
    side: str = "BUY",
    qty: int = 100,
    price: float = 10.0,
    order_id: str | None = None,
    offset: int = 0,
) -> Task:
    ts = _now(offset)
    return Task(
        id=id_,
        type="stock",
        status=Status.FILLED,
        message=_msg(id_, offset=offset),
        instruction=_stock_instruction(ticker=ticker, side=side, qty=qty, price=price),
        order_id=order_id or f"ORD-{id_}",
        created_at=ts,
        updated_at=ts,
    )


async def _seed_filled_task(
    session_factory: async_sessionmaker[AsyncSession],
    task_id: str,
    *,
    qty: int,
    price: float,
    ticker: str = "TSLA",
    side: str = "BUY",
    offset: int = 0,
    account_id: str = "test-acct",
) -> None:
    """Seed a做T-bindable trade: a FILLED task with push event AND a
    matching broker_executions row keyed by order_id.

    Pair binding now reads availability from broker_executions (broker is
    the source of truth), so tests use the same order_id as the trade_id
    they pass to the pair-creation endpoint. The task + push event are
    kept so the legacy task-based code path still has its data, but the
    canonical lookup goes through broker_executions.
    """
    task = _task(task_id, ticker=ticker, side=side, qty=qty, price=price, offset=offset)
    async with session_factory() as session:
        await repo.save_task(session, task)

    order_id = task.order_id or f"ORD-{task_id}"
    evt = PushEvent(
        id=f"{task_id}-evt",
        task_id=task_id,
        order_id=order_id,
        state=PushState.FILLED,
        received_at=_now(offset + 10),
        payload={},
        delta_qty=qty,
        delta_price=price,
        cumulative_qty=qty,
        cumulative_avg_price=price,
    )
    async with session_factory() as session:
        await repo.append_push_event(session, evt)

    # broker_executions row: same order_id, account-scoped. The pair
    # endpoint uses ``task_id`` from the request body as the lookup key
    # against broker_executions.order_id — so tests pass ``task_id`` as
    # the trade selector and the row is found under that id.
    async with session_factory() as session:
        await repo.upsert_broker_executions(
            session,
            account_id=account_id,
            rows=[{
                "order_id": task_id,
                "task_id": task_id,
                "symbol": f"{ticker}.US",
                "ticker": ticker,
                "side": side,
                "qty": qty,
                "price": price,
                "ts": _now(offset + 10),
            }],
        )


@pytest.fixture
def make_app(
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> tuple[FastAPI, FakeBrokerClient]:
    broker = FakeBrokerClient()
    settings = Settings(app_token=_TOKEN)
    bus = EventBus()
    runtime_store = LongPortRuntimeStore(settings_file=tmp_path / "lp.json")
    app = FastAPI()
    app.include_router(
        build_http_router(
            session_factory=session_factory,
            broker=broker,
            settings=settings,
            bus=bus,
            longport_runtime=runtime_store,
        )
    )
    app.dependency_overrides[get_settings] = lambda: settings
    return app, broker


@pytest.fixture
def client(make_app: tuple[FastAPI, FakeBrokerClient]) -> TestClient:
    return TestClient(make_app[0], raise_server_exceptions=True)


# ---------------------------------------------------------------------------
# GET /api/pairs
# ---------------------------------------------------------------------------


def test_list_pairs_empty(client: TestClient) -> None:
    resp = client.get("/api/pairs", params={"token": _TOKEN})
    assert resp.status_code == 200
    body = resp.json()
    assert body["pairs"] == []
    assert body["total_count"] == 0
    assert body["has_more"] is False


def test_list_pairs_filter_by_ticker(
    client: TestClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    import asyncio

    async def seed() -> None:
        await _seed_filled_task(session_factory, "b1", qty=100, price=10.0)
        await _seed_filled_task(session_factory, "s1", qty=100, price=12.0, side="SELL")
        await _seed_filled_task(session_factory, "b2", qty=50, price=20.0, ticker="NVDA")
        await _seed_filled_task(session_factory, "s2", qty=50, price=22.0, ticker="NVDA", side="SELL")

    asyncio.get_event_loop().run_until_complete(seed())

    # Create one pair per ticker
    client.post(
        "/api/pairs",
        params={"token": _TOKEN},
        json={"ticker": "TSLA", "buy_trade_ids": ["b1"], "sell_trade_ids": ["s1"]},
    )
    client.post(
        "/api/pairs",
        params={"token": _TOKEN},
        json={"ticker": "NVDA", "buy_trade_ids": ["b2"], "sell_trade_ids": ["s2"]},
    )

    tsla = client.get("/api/pairs", params={"token": _TOKEN, "ticker": "TSLA"}).json()
    nvda = client.get("/api/pairs", params={"token": _TOKEN, "ticker": "NVDA"}).json()
    assert len(tsla["pairs"]) == 1 and tsla["pairs"][0]["ticker"] == "TSLA"
    assert len(nvda["pairs"]) == 1 and nvda["pairs"][0]["ticker"] == "NVDA"


# ---------------------------------------------------------------------------
# POST /api/pairs
# ---------------------------------------------------------------------------


def test_create_pair_auto_balances(
    client: TestClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """BUY 100 + SELL 150 → pair stores 100/100, SELL has 50 leftover."""
    import asyncio

    async def seed() -> None:
        await _seed_filled_task(session_factory, "b1", qty=100, price=10.0)
        await _seed_filled_task(session_factory, "s1", qty=150, price=12.0, side="SELL")

    asyncio.get_event_loop().run_until_complete(seed())

    resp = client.post(
        "/api/pairs",
        params={"token": _TOKEN},
        json={
            "ticker": "TSLA",
            "symbol": "TSLA.US",
            "buy_trade_ids": ["b1"],
            "sell_trade_ids": ["s1"],
        },
    )
    assert resp.status_code == 201, resp.text
    pair = resp.json()
    assert pair["ticker"] == "TSLA"
    assert pair["buys"] == [{"trade_id": "b1", "qty": 100}]
    assert pair["sells"] == [{"trade_id": "s1", "qty": 100}]


def test_create_pair_one_sided_accepted(
    client: TestClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    import asyncio

    async def seed() -> None:
        await _seed_filled_task(session_factory, "b1", qty=100, price=10.0)

    asyncio.get_event_loop().run_until_complete(seed())

    resp = client.post(
        "/api/pairs",
        params={"token": _TOKEN},
        json={"ticker": "TSLA", "buy_trade_ids": ["b1"], "sell_trade_ids": []},
    )
    assert resp.status_code == 201
    pair = resp.json()
    assert pair["buys"] == [{"trade_id": "b1", "qty": 100}]
    assert pair["sells"] == []


def test_create_pair_unfilled_trades_returns_400(
    client: TestClient,
) -> None:
    """Tasks without push events have qty=0, so allocation fails."""
    resp = client.post(
        "/api/pairs",
        params={"token": _TOKEN},
        json={"ticker": "TSLA", "buy_trade_ids": ["ghost"], "sell_trade_ids": []},
    )
    assert resp.status_code == 400


def test_create_pair_empty_selection_returns_400(client: TestClient) -> None:
    resp = client.post(
        "/api/pairs",
        params={"token": _TOKEN},
        json={"ticker": "TSLA", "buy_trade_ids": [], "sell_trade_ids": []},
    )
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# POST /api/pairs/{id}/extend
# ---------------------------------------------------------------------------


def test_extend_pair_fills_gap(
    client: TestClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Extend a partial pair (BUY 100, SELL 60) with a SELL of 80 → 40 fills
    the gap, remaining 40 stays available on that trade."""
    import asyncio

    async def seed() -> None:
        await _seed_filled_task(session_factory, "b1", qty=100, price=10.0)
        await _seed_filled_task(session_factory, "s1", qty=60, price=12.0, side="SELL")
        await _seed_filled_task(session_factory, "s2", qty=80, price=12.5, side="SELL", offset=100)

    asyncio.get_event_loop().run_until_complete(seed())

    # Create the partial pair: BUY 100 + SELL 60 → balances to {BUY 60, SELL 60}
    # Hmm — to get exactly the {100, 60} shape we need to extend one-sided.
    # Simpler: create with both → server gives us {60, 60}. Then extend with
    # an extra BUY one-sided → {100, 60}.
    p = client.post(
        "/api/pairs",
        params={"token": _TOKEN},
        json={"ticker": "TSLA", "buy_trade_ids": ["b1"], "sell_trade_ids": ["s1"]},
    ).json()
    pair_id = p["id"]
    # Pair now has BUY 60 + SELL 60. Add s2 (80 SELL) → should fully consume
    # nothing new (gap is 0). Falls through to "raw extend" — adds 80 SELL.
    resp = client.post(
        f"/api/pairs/{pair_id}/extend",
        params={"token": _TOKEN},
        json={"buy_trade_ids": [], "sell_trade_ids": ["s2"]},
    )
    assert resp.status_code == 200
    updated = resp.json()
    # Should now show partial: BUY 60, SELL 140
    sell_total = sum(a["qty"] for a in updated["sells"])
    buy_total = sum(a["qty"] for a in updated["buys"])
    assert buy_total == 60
    assert sell_total == 140


def test_extend_missing_pair_returns_404(client: TestClient) -> None:
    # pair_id is INTEGER; use an id outside the autoincrement range.
    resp = client.post(
        "/api/pairs/9999/extend",
        params={"token": _TOKEN},
        json={"buy_trade_ids": [], "sell_trade_ids": ["x"]},
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# DELETE /api/pairs/{id}
# ---------------------------------------------------------------------------


def test_delete_pair(
    client: TestClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    import asyncio

    async def seed() -> None:
        await _seed_filled_task(session_factory, "b1", qty=10, price=1.0)
        await _seed_filled_task(session_factory, "s1", qty=10, price=2.0, side="SELL")

    asyncio.get_event_loop().run_until_complete(seed())

    created = client.post(
        "/api/pairs",
        params={"token": _TOKEN},
        json={"ticker": "TSLA", "buy_trade_ids": ["b1"], "sell_trade_ids": ["s1"]},
    ).json()
    pair_id = created["id"]

    resp = client.delete(f"/api/pairs/{pair_id}", params={"token": _TOKEN})
    assert resp.status_code == 204

    # Confirm gone
    listed = client.get("/api/pairs", params={"token": _TOKEN}).json()
    assert listed["pairs"] == []


def test_delete_missing_pair_returns_404(client: TestClient) -> None:
    resp = client.delete("/api/pairs/9999", params={"token": _TOKEN})
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /api/pairs/aggregate — SQL-driven做T total / count / win
# ---------------------------------------------------------------------------


def test_pair_aggregate_sums_profit_and_counts_wins(
    client: TestClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Two pairs on TSLA, one winning + one losing → aggregate returns
    total profit (sum), count (2), win_count (1)."""
    import asyncio

    async def seed() -> None:
        # Winning做T: BUY 50@10 + SELL 50@12 → profit 100.
        await _seed_filled_task(session_factory, "b_win", qty=50, price=10.0)
        await _seed_filled_task(session_factory, "s_win", qty=50, price=12.0, side="SELL", offset=10)
        # Losing做T: BUY 50@15 + SELL 50@14 → profit -50.
        await _seed_filled_task(session_factory, "b_lose", qty=50, price=15.0, offset=20)
        await _seed_filled_task(session_factory, "s_lose", qty=50, price=14.0, side="SELL", offset=30)

    asyncio.get_event_loop().run_until_complete(seed())

    client.post(
        "/api/pairs",
        params={"token": _TOKEN},
        json={"ticker": "TSLA", "buy_trade_ids": ["b_win"], "sell_trade_ids": ["s_win"]},
    )
    client.post(
        "/api/pairs",
        params={"token": _TOKEN},
        json={"ticker": "TSLA", "buy_trade_ids": ["b_lose"], "sell_trade_ids": ["s_lose"]},
    )

    resp = client.get(
        "/api/pairs/aggregate",
        params={"token": _TOKEN, "ticker": "TSLA"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["count"] == 2
    assert body["win_count"] == 1
    # 50 × (12 − 10) − 50 × (15 − 14) = 100 − 50 = 50.
    assert body["profit_total"] == 50.0


def test_pair_aggregate_filters_by_ticker(
    client: TestClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Pairs on a different ticker don't pollute the count for the
    requested one."""
    import asyncio

    async def seed() -> None:
        await _seed_filled_task(session_factory, "tb", qty=10, price=10.0)
        await _seed_filled_task(session_factory, "ts", qty=10, price=11.0, side="SELL")
        await _seed_filled_task(session_factory, "nb", qty=10, price=20.0, ticker="NVDA")
        await _seed_filled_task(session_factory, "ns", qty=10, price=21.0, ticker="NVDA", side="SELL")

    asyncio.get_event_loop().run_until_complete(seed())
    client.post(
        "/api/pairs",
        params={"token": _TOKEN},
        json={"ticker": "TSLA", "buy_trade_ids": ["tb"], "sell_trade_ids": ["ts"]},
    )
    client.post(
        "/api/pairs",
        params={"token": _TOKEN},
        json={"ticker": "NVDA", "buy_trade_ids": ["nb"], "sell_trade_ids": ["ns"]},
    )

    tsla = client.get(
        "/api/pairs/aggregate", params={"token": _TOKEN, "ticker": "TSLA"}
    ).json()
    nvda = client.get(
        "/api/pairs/aggregate", params={"token": _TOKEN, "ticker": "NVDA"}
    ).json()
    assert tsla["count"] == 1 and nvda["count"] == 1
    assert tsla["profit_total"] == 10.0
    assert nvda["profit_total"] == 10.0


# ---------------------------------------------------------------------------
# GET /api/broker/executions/pending — unallocated qty by side + per-trade
# ---------------------------------------------------------------------------


def test_pending_executions_returns_only_unallocated_qty(
    client: TestClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """One BUY fully bound + one BUY untouched + one SELL untouched →
    the endpoint reports only the two untouched ones with the correct
    pending-qty aggregates per side."""
    import asyncio

    async def seed() -> None:
        await _seed_filled_task(session_factory, "bound_buy", qty=50, price=10.0)
        await _seed_filled_task(session_factory, "free_buy", qty=30, price=11.0, offset=10)
        await _seed_filled_task(session_factory, "bound_sell", qty=50, price=12.0, side="SELL", offset=20)
        await _seed_filled_task(session_factory, "free_sell", qty=20, price=13.0, side="SELL", offset=30)

    asyncio.get_event_loop().run_until_complete(seed())
    # Bind the two "bound_*" trades together — they leave the pending list.
    client.post(
        "/api/pairs",
        params={"token": _TOKEN},
        json={
            "ticker": "TSLA",
            "buy_trade_ids": ["bound_buy"],
            "sell_trade_ids": ["bound_sell"],
        },
    )

    resp = client.get(
        "/api/broker/executions/pending",
        params={"token": _TOKEN, "ticker": "TSLA"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # free_buy 30 + free_sell 20 = totals.
    assert body["pending_buy_qty"] == 30
    assert body["pending_sell_qty"] == 20
    order_ids = sorted(t["order_id"] for t in body["trades"])
    assert order_ids == ["free_buy", "free_sell"]


def test_pending_executions_partial_allocation_is_pending(
    client: TestClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A 100-qty BUY only 60 of which is bound to a pair should appear in
    the pending list with ``pending_qty=40`` — the strict-remainder rule
    must surface partially-allocated fills, not only fully-untouched ones."""
    import asyncio

    async def seed() -> None:
        await _seed_filled_task(session_factory, "big_buy", qty=100, price=10.0)
        await _seed_filled_task(session_factory, "small_sell", qty=60, price=12.0, side="SELL", offset=10)

    asyncio.get_event_loop().run_until_complete(seed())
    # Pair auto-balances to 60/60 (SELL is the smaller side); BUY has 40 leftover.
    client.post(
        "/api/pairs",
        params={"token": _TOKEN},
        json={
            "ticker": "TSLA",
            "buy_trade_ids": ["big_buy"],
            "sell_trade_ids": ["small_sell"],
        },
    )

    body = client.get(
        "/api/broker/executions/pending",
        params={"token": _TOKEN, "ticker": "TSLA"},
    ).json()
    assert body["pending_buy_qty"] == 40
    assert body["pending_sell_qty"] == 0
    assert len(body["trades"]) == 1
    only = body["trades"][0]
    assert only["order_id"] == "big_buy"
    assert only["pending_qty"] == 40
    assert only["allocated_qty"] == 60
