"""Tests for Task G — trader 反查 page settings、数量规则与市价/限价（行情）决策。"""

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
    OptionInstruction,
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


def _option_task(
    ticker: str = "NVDA",
    qty: int | None = None,
    url: str | None = "https://whop.com/o/app/",
    price: float = 2.0,
) -> Task:
    msg = Message(
        id="o-" + ticker,
        content="x",
        raw_content="x",
        author=None,
        posted_at=datetime.now(UTC),
        received_at=datetime.now(UTC),
        source="option",
        url=url,
    )
    task = Task.new_from_message(msg)
    inst = OptionInstruction(
        instruction_type=InstructionType.BUY,
        price=price,
        price_range=None,
        quantity=qty,
        position_size=None,
        stop_loss_price=None,
        take_profit_price=None,
        context_source=None,
        ticker=ticker,
        symbol=f"{ticker}260426C100000.US",
        option_type="CALL",
        strike=100.0,
        expiry=datetime.now(UTC).date(),
    )
    task.mark_parsing()
    task.attach_instruction(inst)
    return task


class _RecordingBroker:
    is_paper = True
    dry_run = False

    def __init__(self):
        self.submitted: list[dict] = []
        #: symbol → last_done for ``get_quote`` (0 = no valid quote).
        self.quote_last: dict[str, float] = {}

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
        return {s: {"last_done": float(self.quote_last.get(s, 0.0))} for s in syms}


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
    assert task.instruction is not None
    assert task.instruction.quantity == 2000


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
async def test_buy_limit_when_quote_missing_or_zero():
    """No valid last_done → LIMIT @ signal."""
    bus = EventBus()
    broker = _RecordingBroker()
    page_settings = PageSettings(
        dedupe_processed_messages=True,
        price_deviation_tolerance=1.0,
        tickers={"TSLL": TickerConfig(trade_quantity=100)},
    )
    register_trader(bus, broker, _config(), registry=_registry_with(page_settings))

    task = _stock_task("TSLL", position_size="常规仓", price=10.0)
    await bus.publish(Event(Topics.TASK_INSTRUCTION_READY, TaskPayload(task)))
    await bus.wait_idle()

    assert broker.submitted[0]["order_type"] == "LIMIT"
    assert broker.submitted[0]["price"] == 10.0
    assert task.submit_order_type == "LIMIT"
    assert task.submit_quote_last_done is None


@pytest.mark.asyncio
async def test_buy_market_when_quote_below_signal():
    bus = EventBus()
    broker = _RecordingBroker()
    broker.quote_last["TSLL.US"] = 9.5
    page_settings = PageSettings(
        dedupe_processed_messages=True,
        price_deviation_tolerance=1.0,
        tickers={"TSLL": TickerConfig(trade_quantity=100)},
    )
    register_trader(bus, broker, _config(), registry=_registry_with(page_settings))

    task = _stock_task("TSLL", position_size="常规仓", price=10.0)
    await bus.publish(Event(Topics.TASK_INSTRUCTION_READY, TaskPayload(task)))
    await bus.wait_idle()

    assert broker.submitted[0]["order_type"] == "MARKET"
    assert broker.submitted[0]["price"] is None
    assert task.submit_order_type == "MARKET"
    assert task.submit_quote_last_done == pytest.approx(9.5)


@pytest.mark.asyncio
async def test_sell_market_when_quote_above_signal():
    bus = EventBus()
    broker = _RecordingBroker()
    broker.quote_last["TSLL.US"] = 10.5
    page_settings = PageSettings(
        dedupe_processed_messages=True,
        price_deviation_tolerance=1.0,
        tickers={"TSLL": TickerConfig(trade_quantity=100)},
    )
    register_trader(bus, broker, _config(), registry=_registry_with(page_settings))

    task = _stock_task("TSLL", position_size="常规仓", price=10.0)
    task.instruction = StockInstruction(  # type: ignore[assignment]
        instruction_type=InstructionType.SELL,
        price=10.0,
        price_range=None,
        quantity=100,
        position_size="常规仓",
        stop_loss_price=None,
        take_profit_price=None,
        context_source=None,
        parser_notes=[],
        ticker="TSLL",
        symbol="TSLL.US",
        sell_quantity=None,
    )
    await bus.publish(Event(Topics.TASK_INSTRUCTION_READY, TaskPayload(task)))
    await bus.wait_idle()

    assert broker.submitted[0]["order_type"] == "MARKET"
    assert broker.submitted[0]["side"] == "SELL"


@pytest.mark.asyncio
async def test_sell_limit_when_quote_at_or_below_signal():
    bus = EventBus()
    broker = _RecordingBroker()
    broker.quote_last["TSLL.US"] = 10.0
    page_settings = PageSettings(
        dedupe_processed_messages=True,
        price_deviation_tolerance=1.0,
        tickers={"TSLL": TickerConfig(trade_quantity=100)},
    )
    register_trader(bus, broker, _config(), registry=_registry_with(page_settings))

    task = _stock_task("TSLL", position_size="常规仓", price=10.0)
    task.instruction = StockInstruction(  # type: ignore[assignment]
        instruction_type=InstructionType.SELL,
        price=10.0,
        price_range=None,
        quantity=100,
        position_size="常规仓",
        stop_loss_price=None,
        take_profit_price=None,
        context_source=None,
        parser_notes=[],
        ticker="TSLL",
        symbol="TSLL.US",
        sell_quantity=None,
    )
    await bus.publish(Event(Topics.TASK_INSTRUCTION_READY, TaskPayload(task)))
    await bus.wait_idle()

    assert broker.submitted[0]["order_type"] == "LIMIT"
    assert broker.submitted[0]["price"] == 10.0


@pytest.mark.asyncio
async def test_block_historical_skips_stock_when_marker_true():
    """is_historical=True + block_historical_messages=True → SKIPPED, reason '历史消息'."""
    bus = EventBus()
    broker = _RecordingBroker()
    page_settings = PageSettings(
        dedupe_processed_messages=True,
        price_deviation_tolerance=1.0,
        block_historical_messages=True,
        tickers={"TSLL": TickerConfig(trade_quantity=100)},
    )
    register_trader(bus, broker, _config(), registry=_registry_with(page_settings))

    task = _stock_task("TSLL", position_size="常规仓")
    task.is_historical = True

    await bus.publish(Event(Topics.TASK_INSTRUCTION_READY, TaskPayload(task)))
    await bus.wait_idle()

    assert broker.submitted == []
    assert task.status.value == "SKIPPED"
    assert "历史消息" in (task.reject_reason or "")


@pytest.mark.asyncio
async def test_block_historical_skips_option_when_marker_true():
    """is_historical=True + block_historical_messages=True → SKIPPED for an option task too."""
    bus = EventBus()
    broker = _RecordingBroker()
    page_settings = PageSettings(
        dedupe_processed_messages=True,
        price_deviation_tolerance=5.0,
        block_historical_messages=True,
        tickers=None,
        # An option page typically lacks tickers; the gate is checked before
        # the option-rule gate, so this skip should fire regardless of option_*
        # settings being unset.
    )
    register_trader(bus, broker, _config(), registry=_registry_with(page_settings))

    task = _option_task("NVDA")
    task.is_historical = True

    await bus.publish(Event(Topics.TASK_INSTRUCTION_READY, TaskPayload(task)))
    await bus.wait_idle()

    assert broker.submitted == []
    assert task.status.value == "SKIPPED"
    assert "历史消息" in (task.reject_reason or "")


@pytest.mark.asyncio
async def test_block_historical_setting_off_proceeds_even_with_marker_true():
    """is_historical=True + block_historical_messages=False → passes the gate, submits."""
    bus = EventBus()
    broker = _RecordingBroker()
    page_settings = PageSettings(
        dedupe_processed_messages=True,
        price_deviation_tolerance=1.0,
        block_historical_messages=False,
        tickers={"TSLL": TickerConfig(trade_quantity=100)},
    )
    register_trader(bus, broker, _config(), registry=_registry_with(page_settings))

    task = _stock_task("TSLL", position_size="常规仓")
    task.is_historical = True

    await bus.publish(Event(Topics.TASK_INSTRUCTION_READY, TaskPayload(task)))
    await bus.wait_idle()

    assert len(broker.submitted) == 1


@pytest.mark.asyncio
async def test_block_historical_marker_false_proceeds_even_with_setting_on():
    """is_historical=False + block_historical_messages=True → passes the gate, submits."""
    bus = EventBus()
    broker = _RecordingBroker()
    page_settings = PageSettings(
        dedupe_processed_messages=True,
        price_deviation_tolerance=1.0,
        block_historical_messages=True,
        tickers={"TSLL": TickerConfig(trade_quantity=100)},
    )
    register_trader(bus, broker, _config(), registry=_registry_with(page_settings))

    task = _stock_task("TSLL", position_size="常规仓")
    # task.is_historical defaults to False — leave as-is

    await bus.publish(Event(Topics.TASK_INSTRUCTION_READY, TaskPayload(task)))
    await bus.wait_idle()

    assert len(broker.submitted) == 1


@pytest.mark.asyncio
async def test_option_skips_when_no_option_rules_enabled():
    bus = EventBus()
    broker = _RecordingBroker()
    page_settings = PageSettings(
        dedupe_processed_messages=True,
        price_deviation_tolerance=5.0,
        tickers=None,
        option_buy_quantity_enabled=False,
        option_total_price_limit_enabled=False,
    )
    register_trader(bus, broker, _config(), registry=_registry_with(page_settings))

    task = _option_task()
    await bus.publish(Event(Topics.TASK_INSTRUCTION_READY, TaskPayload(task)))
    await bus.wait_idle()

    assert broker.submitted == []
    assert task.status.value == "SKIPPED"
    assert "disabled" in (task.reject_reason or "")


@pytest.mark.asyncio
async def test_option_uses_quantity_rule_when_enabled():
    bus = EventBus()
    broker = _RecordingBroker()
    page_settings = PageSettings(
        dedupe_processed_messages=True,
        price_deviation_tolerance=5.0,
        tickers=None,
        option_buy_quantity_enabled=True,
        option_buy_quantity=3,
        option_total_price_limit_enabled=False,
    )
    register_trader(bus, broker, _config(), registry=_registry_with(page_settings))

    task = _option_task(price=2.0)
    await bus.publish(Event(Topics.TASK_INSTRUCTION_READY, TaskPayload(task)))
    await bus.wait_idle()

    assert len(broker.submitted) == 1
    assert broker.submitted[0]["quantity"] == 3


@pytest.mark.asyncio
async def test_option_uses_total_limit_rule_when_enabled():
    bus = EventBus()
    broker = _RecordingBroker()
    page_settings = PageSettings(
        dedupe_processed_messages=True,
        price_deviation_tolerance=5.0,
        tickers=None,
        option_buy_quantity_enabled=False,
        option_total_price_limit_enabled=True,
        option_total_price_limit=450.0,
    )
    register_trader(bus, broker, _config(), registry=_registry_with(page_settings))

    task = _option_task(price=2.0)
    await bus.publish(Event(Topics.TASK_INSTRUCTION_READY, TaskPayload(task)))
    await bus.wait_idle()

    assert len(broker.submitted) == 1
    assert broker.submitted[0]["quantity"] == 2  # floor(450 / (2.0 * 100))


@pytest.mark.asyncio
async def test_option_uses_both_rules_with_min_quantity():
    bus = EventBus()
    broker = _RecordingBroker()
    page_settings = PageSettings(
        dedupe_processed_messages=True,
        price_deviation_tolerance=5.0,
        tickers=None,
        option_buy_quantity_enabled=True,
        option_buy_quantity=5,
        option_total_price_limit_enabled=True,
        option_total_price_limit=450.0,
    )
    register_trader(bus, broker, _config(), registry=_registry_with(page_settings))

    task = _option_task(price=2.0)
    await bus.publish(Event(Topics.TASK_INSTRUCTION_READY, TaskPayload(task)))
    await bus.wait_idle()

    assert len(broker.submitted) == 1
    assert broker.submitted[0]["quantity"] == 2
