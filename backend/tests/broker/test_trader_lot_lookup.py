"""End-to-end trader tests for the lot-reference qty path.

Driven through the event bus with FakeBrokerClient + FakeTaskQueryRepo.
Asserts on the qty submitted to the broker via fake.submitted_orders.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.broker.config import LongPortConfig
from app.broker.trader import register_trader
from app.core.event_bus import Event, EventBus
from app.core.events import TaskPayload, Topics
from app.domain.instruction import InstructionType, StockInstruction
from app.domain.message import Message
from app.domain.task import Task
from app.whop.page_settings import PageSettings, TickerConfig
from tests.broker._fakes import FakeBrokerClient, FakeTaskQueryRepo


def _msg() -> Message:
    return Message(
        id="msg-test-001",
        content="test",
        raw_content="test",
        author="t",
        posted_at=datetime(2026, 4, 24, 10, 0, 0, tzinfo=UTC),
        received_at=datetime(2026, 4, 24, 10, 0, 0, 1000, tzinfo=UTC),
        source="stock",
    )


def _stock_task(
    *,
    side: InstructionType,
    price: float,
    referenced_lot_price: float | None = None,
    sell_quantity: str | None = None,
) -> Task:
    task = Task.new_from_message(_msg())
    task.mark_parsing()
    inst = StockInstruction(
        instruction_type=side,
        price=price,
        price_range=None,
        quantity=2000,  # parser/page default; will be overwritten by trader
        position_size=None,
        stop_loss_price=None,
        take_profit_price=None,
        context_source=None,
        parser_notes=[],
        ticker="TSLL",
        symbol="TSLL.US",
        sell_quantity=sell_quantity,
        referenced_lot_price=referenced_lot_price,
    )
    task.attach_instruction(inst)
    return task


def _config() -> LongPortConfig:
    return LongPortConfig(
        mode="paper", app_key="k", app_secret="s", access_token="t",
        auto_trade=True, dry_run=False,
        max_option_total_price=500.0, max_option_quantity=3,
    )


def _registry_with_default(default_qty: int = 2000):
    """A WhopRegistry-like stub returning page settings with one whitelisted ticker."""
    page = PageSettings(
        dedupe_processed_messages=True,
        price_deviation_tolerance=1.0,
        block_historical_messages=False,
        launch_headless=False,
        tickers={"TSLL": TickerConfig(trade_quantity=default_qty)},
    )

    class _Registry:
        def get_settings_for_url(self, url):
            return page

    return _Registry()


@pytest.mark.asyncio
async def test_lot_path_sell_half_uses_prior_buy_qty() -> None:
    """SELL with ref to BUY @12.42 (qty 4000), sell_quantity '1/2' → 2000."""
    bus = EventBus()
    fake = FakeBrokerClient()
    repo = FakeTaskQueryRepo(matches={("TSLL", "BUY", 12.42): 4000})
    register_trader(
        bus, fake, _config(),
        registry=_registry_with_default(default_qty=999),  # default would mismatch
        task_query_repo=repo,
    )

    task = _stock_task(
        side=InstructionType.SELL, price=12.87,
        referenced_lot_price=12.42, sell_quantity="1/2",
    )
    await bus.publish(Event(Topics.TASK_INSTRUCTION_READY, TaskPayload(task)))
    await bus.wait_idle(timeout=2.0)

    assert len(fake.submitted_orders) == 1
    assert fake.submitted_orders[0]["quantity"] == 2000


@pytest.mark.asyncio
async def test_lot_path_buy_full_uses_prior_sell_qty() -> None:
    """BUY referencing prior SELL @12.87 (qty 2000), sell_quantity '全部' → 2000."""
    bus = EventBus()
    fake = FakeBrokerClient()
    repo = FakeTaskQueryRepo(matches={("TSLL", "SELL", 12.87): 2000})
    register_trader(
        bus, fake, _config(),
        registry=_registry_with_default(default_qty=999),
        task_query_repo=repo,
    )

    task = _stock_task(
        side=InstructionType.BUY, price=12.32,
        referenced_lot_price=12.87, sell_quantity="全部",
    )
    await bus.publish(Event(Topics.TASK_INSTRUCTION_READY, TaskPayload(task)))
    await bus.wait_idle(timeout=2.0)

    assert fake.submitted_orders[0]["quantity"] == 2000


@pytest.mark.asyncio
async def test_lot_miss_falls_back_to_default_position() -> None:
    """No matching prior lot → falls back to page default × position_size_to_fraction."""
    bus = EventBus()
    fake = FakeBrokerClient()
    repo = FakeTaskQueryRepo(matches={})  # empty
    register_trader(
        bus, fake, _config(),
        registry=_registry_with_default(default_qty=300),
        task_query_repo=repo,
    )

    task = _stock_task(
        side=InstructionType.SELL, price=87.4,
        referenced_lot_price=85.65, sell_quantity="1/2",
    )
    await bus.publish(Event(Topics.TASK_INSTRUCTION_READY, TaskPayload(task)))
    await bus.wait_idle(timeout=2.0)

    # Falls back: default trade_quantity 300 × position_size_to_fraction(None)=1.0 → 300
    assert fake.submitted_orders[0]["quantity"] == 300


@pytest.mark.asyncio
async def test_no_repo_injected_falls_back_silently() -> None:
    """task_query_repo=None → instruction's lot ref is ignored, fallback used."""
    bus = EventBus()
    fake = FakeBrokerClient()
    register_trader(
        bus, fake, _config(),
        registry=_registry_with_default(default_qty=300),
        task_query_repo=None,  # explicitly absent
    )

    task = _stock_task(
        side=InstructionType.SELL, price=12.87,
        referenced_lot_price=12.42, sell_quantity="1/2",
    )
    await bus.publish(Event(Topics.TASK_INSTRUCTION_READY, TaskPayload(task)))
    await bus.wait_idle(timeout=2.0)

    assert fake.submitted_orders[0]["quantity"] == 300


@pytest.mark.asyncio
async def test_missing_sell_quantity_falls_back() -> None:
    """ref_price set but sell_quantity=None → fallback (incomplete reference)."""
    bus = EventBus()
    fake = FakeBrokerClient()
    repo = FakeTaskQueryRepo(matches={("TSLL", "BUY", 12.42): 4000})
    register_trader(
        bus, fake, _config(),
        registry=_registry_with_default(default_qty=300),
        task_query_repo=repo,
    )

    task = _stock_task(
        side=InstructionType.SELL, price=12.87,
        referenced_lot_price=12.42, sell_quantity=None,  # missing
    )
    await bus.publish(Event(Topics.TASK_INSTRUCTION_READY, TaskPayload(task)))
    await bus.wait_idle(timeout=2.0)

    assert fake.submitted_orders[0]["quantity"] == 300


@pytest.mark.asyncio
async def test_unknown_sell_quantity_uses_one_with_warning() -> None:
    """sell_quantity '一点点' is unknown → fraction 1.0 (full lot) + warning."""
    bus = EventBus()
    fake = FakeBrokerClient()
    repo = FakeTaskQueryRepo(matches={("TSLL", "BUY", 12.42): 2000})
    register_trader(
        bus, fake, _config(),
        registry=_registry_with_default(default_qty=999),
        task_query_repo=repo,
    )

    task = _stock_task(
        side=InstructionType.SELL, price=12.87,
        referenced_lot_price=12.42, sell_quantity="一点点",
    )
    await bus.publish(Event(Topics.TASK_INSTRUCTION_READY, TaskPayload(task)))
    await bus.wait_idle(timeout=2.0)

    assert fake.submitted_orders[0]["quantity"] == 2000  # 2000 × 1.0


@pytest.mark.asyncio
async def test_remainder_half_treated_as_one_half() -> None:
    """sell_quantity '剩下一半' → 0.5 (decision 5: no lot consumption tracking)."""
    bus = EventBus()
    fake = FakeBrokerClient()
    repo = FakeTaskQueryRepo(matches={("TSLL", "BUY", 11.73): 4000})
    register_trader(
        bus, fake, _config(),
        registry=_registry_with_default(default_qty=999),
        task_query_repo=repo,
    )

    task = _stock_task(
        side=InstructionType.SELL, price=12.37,
        referenced_lot_price=11.73, sell_quantity="剩下一半",
    )
    await bus.publish(Event(Topics.TASK_INSTRUCTION_READY, TaskPayload(task)))
    await bus.wait_idle(timeout=2.0)

    assert fake.submitted_orders[0]["quantity"] == 2000  # 4000 × 0.5


@pytest.mark.asyncio
async def test_repo_called_with_opposite_side() -> None:
    """SELL with ref → repo asked for opposite side BUY."""
    bus = EventBus()
    fake = FakeBrokerClient()
    repo = FakeTaskQueryRepo(matches={("TSLL", "BUY", 12.42): 4000})
    register_trader(
        bus, fake, _config(),
        registry=_registry_with_default(),
        task_query_repo=repo,
    )

    task = _stock_task(
        side=InstructionType.SELL, price=12.87,
        referenced_lot_price=12.42, sell_quantity="1/2",
    )
    await bus.publish(Event(Topics.TASK_INSTRUCTION_READY, TaskPayload(task)))
    await bus.wait_idle(timeout=2.0)

    assert len(repo.calls) == 1
    assert repo.calls[0]["side"] == InstructionType.BUY
    assert repo.calls[0]["price"] == 12.42
    assert repo.calls[0]["window_hours"] == 24 * 7


@pytest.mark.asyncio
async def test_repo_exception_falls_back_to_default() -> None:
    """If the repo raises, trader logs and falls back to default qty (Decision 6)."""

    class _RaisingRepo:
        async def find_recent_task_by_ref(self, **_kw: object) -> int | None:
            raise RuntimeError("simulated DB blip")

    bus = EventBus()
    fake = FakeBrokerClient()
    register_trader(
        bus, fake, _config(),
        registry=_registry_with_default(default_qty=300),
        task_query_repo=_RaisingRepo(),  # type: ignore[arg-type]
    )

    task = _stock_task(
        side=InstructionType.SELL, price=12.87,
        referenced_lot_price=12.42, sell_quantity="1/2",
    )
    await bus.publish(Event(Topics.TASK_INSTRUCTION_READY, TaskPayload(task)))
    await bus.wait_idle(timeout=2.0)

    # The task is NOT silently dropped: order is submitted with default qty.
    assert len(fake.submitted_orders) == 1
    assert fake.submitted_orders[0]["quantity"] == 300
