"""Trader — subscribes to TASK_INSTRUCTION_READY, validates, submits orders.

Deferred (future tasks):
- Quote-based price adjustment / chase (get_quote + tolerance logic).
- Stock quantity calculation from watched_stocks.json / position_size.
- Stop-loss / take-profit follow-up orders.
- MODIFY / CLOSE instruction types.
- Cancel order API.
- asyncio.to_thread wrapping for blocking SDK calls.
"""
from __future__ import annotations

import logging
import time
from collections.abc import Callable

from app.broker.broker_client import BrokerClient, OrderSide, OrderType
from app.broker.config import LongPortConfig
from app.core.event_bus import Event, EventBus
from app.core.events import TaskPayload, Topics
from app.domain.instruction import Instruction, InstructionType, OptionInstruction
from app.domain.task import Task

logger = logging.getLogger(__name__)


def register_trader(
    bus: EventBus,
    client: BrokerClient,
    config: LongPortConfig,
) -> Callable[[], None]:
    """Subscribe trader handler to TASK_INSTRUCTION_READY.

    Returns an unsubscribe callable.
    """

    async def _handle_instruction_ready(event: Event) -> None:
        payload = event.payload
        if not isinstance(payload, TaskPayload):
            return
        task: Task = payload.task
        inst: Instruction | None = task.instruction
        if inst is None:
            return

        # --- Validation ---

        if not config.auto_trade:
            task.mark_skipped("auto_trade disabled in config")
            await bus.publish(Event(Topics.TASK_STATUS_CHANGED, TaskPayload(task)))
            return

        if not getattr(inst, "symbol", None):
            task.mark_skipped("instruction missing symbol")
            await bus.publish(Event(Topics.TASK_STATUS_CHANGED, TaskPayload(task)))
            return

        if isinstance(inst, OptionInstruction):
            qty = inst.quantity or 1
            price = inst.price if inst.price is not None else (
                inst.price_range[0] if inst.price_range else 0.0
            )
            # One option contract = 100 shares equivalent (matches old auto_trader.py)
            total = price * qty * 100
            if total > config.max_option_total_price:
                task.mark_skipped(
                    f"option total ${total:.2f} exceeds limit ${config.max_option_total_price}"
                )
                await bus.publish(Event(Topics.TASK_STATUS_CHANGED, TaskPayload(task)))
                return
            if qty > config.max_option_quantity:
                task.mark_skipped(
                    f"option quantity {qty} exceeds limit {config.max_option_quantity}"
                )
                await bus.publish(Event(Topics.TASK_STATUS_CHANGED, TaskPayload(task)))
                return

        if inst.instruction_type not in (InstructionType.BUY, InstructionType.SELL):
            task.mark_skipped(
                f"unsupported instruction type: {inst.instruction_type}"
            )
            await bus.publish(Event(Topics.TASK_STATUS_CHANGED, TaskPayload(task)))
            return

        # --- Submit ---

        task.mark_submitting()
        await bus.publish(Event(Topics.TASK_STATUS_CHANGED, TaskPayload(task)))

        started = time.perf_counter()
        try:
            order_id = _submit(client, inst)
        except Exception as exc:
            elapsed = (time.perf_counter() - started) * 1000
            task.stage_timings["submit"] = elapsed
            task.mark_submit_failed(f"broker error: {exc}")
            logger.error(
                "Trader: order submission failed for task %s: %s",
                task.id,
                exc,
                exc_info=True,
            )
            await bus.publish(Event(Topics.TASK_SUBMIT_FAILED, TaskPayload(task)))
            return

        elapsed_ms = (time.perf_counter() - started) * 1000
        task.mark_submitted(order_id=order_id, timing_ms=elapsed_ms)
        logger.info(
            "Trader: submitted order %s for task %s in %.1f ms",
            order_id,
            task.id,
            elapsed_ms,
        )
        await bus.publish(Event(Topics.TASK_ORDER_SUBMITTED, TaskPayload(task)))

    return bus.subscribe(Topics.TASK_INSTRUCTION_READY, _handle_instruction_ready)


def _submit(client: BrokerClient, inst: Instruction) -> str:
    """Dispatch to the appropriate broker method based on instruction subtype."""
    price: float | None = inst.price if inst.price is not None else (
        inst.price_range[0] if inst.price_range else None
    )
    if price is None:
        raise ValueError("no price available for submission")

    quantity = inst.quantity or 1
    side: OrderSide = "BUY" if inst.instruction_type == InstructionType.BUY else "SELL"
    order_type: OrderType = "LIMIT"
    remark = f"auto_trade: {type(inst).__name__}"

    if isinstance(inst, OptionInstruction):
        return client.submit_option_order(
            symbol=inst.symbol,
            side=side,
            quantity=quantity,
            price=price,
            order_type=order_type,
            remark=remark,
        )
    # StockInstruction (or any other Instruction subtype with a symbol attribute)
    symbol: str = getattr(inst, "symbol", "") or getattr(inst, "ticker", "")
    return client.submit_stock_order(
        symbol=symbol,
        side=side,
        quantity=quantity,
        price=price,
        order_type=order_type,
        remark=remark,
    )
