"""Tests for /api/trades — per-ticker fill aggregation."""

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

_TOKEN = "test-token-trades"


def _now(offset: int = 0) -> datetime:
    base = datetime.combine(date.today(), datetime.min.time(), tzinfo=UTC)
    return base + timedelta(hours=10, seconds=offset)


def _msg(id_: str, *, offset: int = 0, author: str = "Andrew") -> Message:
    ts = _now(offset)
    return Message(
        id=id_,
        content="BUY TSLA 100 @ 245",
        raw_content="BUY TSLA 100 @ 245",
        author=author,
        source="stock",  # type: ignore[arg-type]
        posted_at=ts,
        received_at=ts,
    )


def _stock_instruction(
    *, ticker: str = "TSLA", side: str = "BUY", qty: int = 100, price: float = 10.0,
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


async def _seed_filled(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    task_id: str,
    ticker: str = "TSLA",
    side: str = "BUY",
    qty: int = 100,
    price: float = 10.0,
    offset: int = 0,
    author: str = "Andrew",
) -> None:
    ts = _now(offset)
    task = Task(
        id=task_id,
        type="stock",
        status=Status.FILLED,
        message=_msg(task_id, offset=offset, author=author),
        instruction=_stock_instruction(ticker=ticker, side=side, qty=qty, price=price),
        order_id=f"ORD-{task_id}",
        created_at=ts,
        updated_at=ts,
    )
    async with session_factory() as session:
        await repo.save_task(session, task)
        await repo.append_push_event(
            session,
            PushEvent(
                id=f"{task_id}-evt",
                task_id=task_id,
                order_id=f"ORD-{task_id}",
                state=PushState.FILLED,
                received_at=_now(offset + 5),
                payload={},
                delta_qty=qty,
                delta_price=price,
                cumulative_qty=qty,
                cumulative_avg_price=price,
            ),
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
# Tests
# ---------------------------------------------------------------------------


def test_trades_empty_for_unknown_ticker(client: TestClient) -> None:
    resp = client.get("/api/trades", params={"token": _TOKEN, "ticker": "TSLA"})
    assert resp.status_code == 200
    body = resp.json()
    assert body == {"ticker": "TSLA", "trades": []}


def test_trades_returns_filled_in_chronological_order(
    client: TestClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    import asyncio

    async def seed() -> None:
        await _seed_filled(session_factory, task_id="t3", offset=3000)
        await _seed_filled(session_factory, task_id="t1", offset=1000)
        await _seed_filled(session_factory, task_id="t2", offset=2000)

    asyncio.get_event_loop().run_until_complete(seed())

    resp = client.get("/api/trades", params={"token": _TOKEN, "ticker": "TSLA"})
    assert resp.status_code == 200
    ids = [t["id"] for t in resp.json()["trades"]]
    assert ids == ["t1", "t2", "t3"]


def test_trades_filters_by_ticker(
    client: TestClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    import asyncio

    async def seed() -> None:
        await _seed_filled(session_factory, task_id="t-tsla", ticker="TSLA")
        await _seed_filled(session_factory, task_id="t-nvda", ticker="NVDA")

    asyncio.get_event_loop().run_until_complete(seed())

    tsla = client.get("/api/trades", params={"token": _TOKEN, "ticker": "TSLA"}).json()
    nvda = client.get("/api/trades", params={"token": _TOKEN, "ticker": "NVDA"}).json()

    assert [t["id"] for t in tsla["trades"]] == ["t-tsla"]
    assert [t["id"] for t in nvda["trades"]] == ["t-nvda"]


def test_trades_includes_qty_and_price(
    client: TestClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    import asyncio

    async def seed() -> None:
        await _seed_filled(
            session_factory, task_id="t1", side="BUY", qty=150, price=245.30,
        )
        await _seed_filled(
            session_factory, task_id="t2", side="SELL", qty=100, price=247.80, offset=100,
        )

    asyncio.get_event_loop().run_until_complete(seed())

    trades = client.get("/api/trades", params={"token": _TOKEN, "ticker": "TSLA"}).json()["trades"]
    assert len(trades) == 2
    by_id = {t["id"]: t for t in trades}
    assert by_id["t1"]["side"] == "BUY"
    assert by_id["t1"]["qty"] == 150
    assert by_id["t1"]["price"] == pytest.approx(245.30)
    assert by_id["t2"]["side"] == "SELL"


def test_trades_excludes_unfilled_tasks(
    client: TestClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A task without push events (or with zero cumulative qty) is skipped."""
    import asyncio

    async def seed() -> None:
        ts = _now(0)
        task = Task(
            id="unfilled-1",
            type="stock",
            status=Status.PENDING,
            message=_msg("unfilled-1"),
            instruction=_stock_instruction(),
            order_id="ORD-unfilled-1",
            created_at=ts,
            updated_at=ts,
        )
        async with session_factory() as session:
            await repo.save_task(session, task)
        # Also seed one fully filled to confirm filtering, not just empty result
        await _seed_filled(session_factory, task_id="filled-1", offset=100)

    asyncio.get_event_loop().run_until_complete(seed())

    trades = client.get("/api/trades", params={"token": _TOKEN, "ticker": "TSLA"}).json()["trades"]
    assert [t["id"] for t in trades] == ["filled-1"]


def test_trades_source_from_message_author(
    client: TestClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    import asyncio

    async def seed() -> None:
        await _seed_filled(session_factory, task_id="t1", author="RoaringKitty")

    asyncio.get_event_loop().run_until_complete(seed())

    trades = client.get("/api/trades", params={"token": _TOKEN, "ticker": "TSLA"}).json()["trades"]
    assert trades[0]["source"] == "RoaringKitty"
