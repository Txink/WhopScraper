"""Tests for Task G — trader 反查 page settings + 偏差→order_type 决策。"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from app.broker.config import LongPortConfig
from app.broker.trader import register_trader
from app.core.event_bus import Event, EventBus
from app.core.events import TaskPayload, Topics
from app.domain.instruction import (
    InstructionType,
    StockInstruction,
)
from app.domain.message import Message
from app.domain.task import Task
from app.whop.page_settings import PageSettings, TickerConfig


def _stock_task(
    ticker: str = "TSLL",
    qty: int | None = None,
    position_size: str | None = None,
    url: str | None = "https://whop.com/x/app/",
    price: float = 10.0,
) -> Task:
    msg = Message(
        id="t-" + ticker,
        content="x",
        raw_content="x",
        author=None,
        posted_at=datetime.now(UTC),
        received_at=datetime.now(UTC),
        source="stock",
        url=url,
    )
    task = Task.new_from_message(msg)
    inst = StockInstruction(
        instruction_type=InstructionType.BUY,
        price=price,
        price_range=None,
        quantity=qty,
        position_size=position_size,
        stop_loss_price=None,
        take_profit_price=None,
        context_source=None,
        ticker=ticker,
        symbol=f"{ticker}.US",
    )
    task.mark_parsing()
    task.attach_instruction(inst)
    return task


class _RecordingBroker:
    is_paper = True
    dry_run = False

    def __init__(self):
        self.submitted: list[dict] = []

    def submit_stock_order(self, *, symbol, side, quantity, price, order_type, remark):
        self.submitted.append(
            {
                "symbol": symbol,
                "side": side,
                "quantity": quantity,
                "price": price,
                "order_type": order_type,
                "remark": remark,
            }
        )
        return f"ord-{symbol}"

    def submit_option_order(self, *, symbol, side, quantity, price, order_type, remark):
        self.submitted.append(
            {
                "symbol": symbol,
                "side": side,
                "quantity": quantity,
                "price": price,
                "order_type": order_type,
                "remark": remark,
            }
        )
        return f"ord-opt-{symbol}"

    def cancel_order(self, oid):
        return None

    def close(self):
        return None

    def subscribe_order_push(self, h):
        return None

    def get_quote(self, syms):
        return {}


def _config() -> LongPortConfig:
    return LongPortConfig(
        mode="paper",
        app_key="",
        app_secret="",
        access_token="",
        auto_trade=True,
        dry_run=False,
        max_option_total_price=10000,
        max_option_quantity=10,
    )


def _registry_with(settings: PageSettings | None) -> MagicMock:
    reg = MagicMock()
    reg.get_settings_for_url.return_value = settings
    return reg


@pytest.mark.asyncio
async def test_skip_when_ticker_not_whitelisted():
    bus = EventBus()
    broker = _RecordingBroker()
    page_settings = PageSettings(
        dedupe_processed_messages=True,
        price_deviation_tolerance=1.0,
        tickers={"NVDA": TickerConfig(trade_quantity=100)},  # TSLL not in
    )
    register_trader(bus, broker, _config(), registry=_registry_with(page_settings))

    task = _stock_task("TSLL", position_size="常规仓")
    await bus.publish(Event(Topics.TASK_INSTRUCTION_READY, TaskPayload(task)))
    await bus.wait_idle()

    assert broker.submitted == []
    assert task.status.value == "SKIPPED"
    reason = (task.reject_reason or "").lower()
    assert "tsll" in reason or "whitelist" in reason


@pytest.mark.asyncio
async def test_qty_calc_normal_position():
    bus = EventBus()
    broker = _RecordingBroker()
    page_settings = PageSettings(
        dedupe_processed_messages=True,
        price_deviation_tolerance=1.0,
        tickers={"TSLL": TickerConfig(trade_quantity=2000)},
    )
    register_trader(bus, broker, _config(), registry=_registry_with(page_settings))

    task = _stock_task("TSLL", position_size="常规仓")
    await bus.publish(Event(Topics.TASK_INSTRUCTION_READY, TaskPayload(task)))
    await bus.wait_idle()

    assert len(broker.submitted) == 1
    assert broker.submitted[0]["quantity"] == 2000


@pytest.mark.asyncio
async def test_qty_calc_half_position():
    bus = EventBus()
    broker = _RecordingBroker()
    page_settings = PageSettings(
        dedupe_processed_messages=True,
        price_deviation_tolerance=1.0,
        tickers={"TSLL": TickerConfig(trade_quantity=2000)},
    )
    register_trader(bus, broker, _config(), registry=_registry_with(page_settings))

    task = _stock_task("TSLL", position_size="半仓")
    await bus.publish(Event(Topics.TASK_INSTRUCTION_READY, TaskPayload(task)))
    await bus.wait_idle()

    assert broker.submitted[0]["quantity"] == 1000


@pytest.mark.asyncio
async def test_qty_calc_one_third():
    bus = EventBus()
    broker = _RecordingBroker()
    page_settings = PageSettings(
        dedupe_processed_messages=True,
        price_deviation_tolerance=1.0,
        tickers={"TSLL": TickerConfig(trade_quantity=2000)},
    )
    register_trader(bus, broker, _config(), registry=_registry_with(page_settings))

    task = _stock_task("TSLL", position_size="1/3")
    await bus.publish(Event(Topics.TASK_INSTRUCTION_READY, TaskPayload(task)))
    await bus.wait_idle()

    assert broker.submitted[0]["quantity"] == 666  # int(2000 * 1/3) = 666


@pytest.mark.asyncio
async def test_qty_min_one():
    bus = EventBus()
    broker = _RecordingBroker()
    page_settings = PageSettings(
        dedupe_processed_messages=True,
        price_deviation_tolerance=1.0,
        tickers={"TSLL": TickerConfig(trade_quantity=2)},
    )
    register_trader(bus, broker, _config(), registry=_registry_with(page_settings))

    task = _stock_task("TSLL", position_size="1/3")  # 2 * 1/3 = 0.666 → max(0, 1) = 1
    await bus.publish(Event(Topics.TASK_INSTRUCTION_READY, TaskPayload(task)))
    await bus.wait_idle()

    assert broker.submitted[0]["quantity"] == 1


@pytest.mark.asyncio
async def test_orphan_stock_uses_instruction_quantity():
    bus = EventBus()
    broker = _RecordingBroker()
    register_trader(bus, broker, _config(), registry=_registry_with(None))  # orphan

    task = _stock_task("TSLL", qty=300, position_size=None, url=None)
    await bus.publish(Event(Topics.TASK_INSTRUCTION_READY, TaskPayload(task)))
    await bus.wait_idle()

    assert broker.submitted[0]["quantity"] == 300


@pytest.mark.asyncio
async def test_orphan_stock_no_qty_skipped():
    bus = EventBus()
    broker = _RecordingBroker()
    register_trader(bus, broker, _config(), registry=_registry_with(None))

    task = _stock_task("TSLL", qty=None, position_size=None, url=None)
    await bus.publish(Event(Topics.TASK_INSTRUCTION_READY, TaskPayload(task)))
    await bus.wait_idle()

    assert broker.submitted == []
    assert task.status.value == "SKIPPED"


@pytest.mark.asyncio
async def test_market_when_within_tolerance():
    """First-pass: market_price = signal_price → deviation 0 → always MARKET."""
    bus = EventBus()
    broker = _RecordingBroker()
    page_settings = PageSettings(
        dedupe_processed_messages=True,
        price_deviation_tolerance=1.0,
        tickers={"TSLL": TickerConfig(trade_quantity=100)},
    )
    register_trader(bus, broker, _config(), registry=_registry_with(page_settings))

    task = _stock_task("TSLL", position_size="常规仓")
    await bus.publish(Event(Topics.TASK_INSTRUCTION_READY, TaskPayload(task)))
    await bus.wait_idle()

    assert broker.submitted[0]["order_type"] == "MARKET"
