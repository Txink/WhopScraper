"""Trader — subscribes to TASK_INSTRUCTION_READY, validates, submits orders.

Behavior (Task G):
- Looks up the per-page ``PageSettings`` by ``task.message.url`` via the
  ``WhopRegistry`` reverse-index. ``None`` => orphan task → use instruction.quantity.
- Stock whitelist gate: if page settings has tickers, ticker must be in whitelist
  or task is SKIPPED with a clear reason.
- Stock qty: ``max(int(trade_quantity * position_size_to_fraction(position_size)), 1)``.
- Option qty: unchanged from previous behavior + max_option_total_price /
  max_option_quantity guards.
- Order type decision based on ``deviation = abs(market - signal) / signal * 100``.
  ≤ tolerance → MARKET; > tolerance → LIMIT @ signal_price.
  First-pass: market_price = signal_price (deviation always 0 → always MARKET).
  TODO: hook real quote via ``broker.get_quote(...)``.

Deferred:
- Real-quote integration for genuine deviation check.
- Stop-loss / take-profit follow-up orders.
- MODIFY / CLOSE instruction types.
- Cancel order API.
- ``asyncio.to_thread`` wrapping for blocking SDK calls.
"""
from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any

from app.broker.broker_client import BrokerClient, OrderSide, OrderType
from app.broker.config import LongPortConfig
from app.core.event_bus import Event, EventBus
from app.core.events import TaskPayload, Topics
from app.domain.instruction import (
    Instruction,
    InstructionType,
    OptionInstruction,
    StockInstruction,
)
from app.domain.task import Task
from app.whop.page_settings import position_size_to_fraction

logger = logging.getLogger(__name__)


def register_trader(
    bus: EventBus,
    client: BrokerClient,
    config: LongPortConfig,
    *,
    registry: Any | None = None,
) -> Callable[[], None]:
    """Subscribe trader handler to TASK_INSTRUCTION_READY.

    Parameters
    ----------
    bus, client, config:
        Standard wiring.
    registry:
        WhopRegistry-like object exposing ``get_settings_for_url(url)`` →
        ``PageSettings | None``. If ``None``, every task is treated as an
        "orphan" (no page settings) and falls back to ``instruction.quantity``
        + global Settings tolerance.

    Returns the unsubscribe callable.
    """

    async def _publish_skip(task: Task, reason: str) -> None:
        task.mark_skipped(reason)
        await bus.publish(Event(Topics.TASK_STATUS_CHANGED, TaskPayload(task)))

    def _resolve_settings(task: Task):
        if registry is None:
            return None
        return registry.get_settings_for_url(task.message.url)

    def _fallback_tolerance_pct(task_type: str) -> float:
        from app.core.config import get_settings  # local import for testability
        s = get_settings()
        if task_type == "stock":
            return s.stock_price_deviation_tolerance
        return s.price_deviation_tolerance

    async def _handle_instruction_ready(event: Event) -> None:
        payload = event.payload
        if not isinstance(payload, TaskPayload):
            return
        task: Task = payload.task
        inst: Instruction | None = task.instruction
        if inst is None:
            return

        # ---- Top-level validation ----
        if not config.auto_trade:
            await _publish_skip(task, "auto_trade disabled in config")
            return
        if not getattr(inst, "symbol", None):
            await _publish_skip(task, "instruction missing symbol")
            return
        if inst.instruction_type not in (InstructionType.BUY, InstructionType.SELL):
            await _publish_skip(task, f"unsupported instruction type: {inst.instruction_type}")
            return

        page_settings = _resolve_settings(task)

        # ---- qty calc + per-asset gates ----
        if isinstance(inst, StockInstruction):
            ticker_upper = (inst.ticker or "").upper()
            if page_settings is not None and page_settings.tickers is not None:
                # Stock page with explicit whitelist
                if ticker_upper not in page_settings.tickers:
                    await _publish_skip(
                        task, f"ticker {ticker_upper} not in trade whitelist"
                    )
                    return
                base_qty = page_settings.tickers[ticker_upper].trade_quantity
                fraction = position_size_to_fraction(inst.position_size)
                computed_qty = max(int(base_qty * fraction), 1)
            else:
                # Orphan stock task — fall back to instruction.quantity
                computed_qty = inst.quantity or 0
                if computed_qty <= 0:
                    await _publish_skip(
                        task, "orphan stock task missing instruction.quantity"
                    )
                    return
        elif isinstance(inst, OptionInstruction):
            computed_qty = inst.quantity or 1
            price_for_check = inst.price if inst.price is not None else (
                inst.price_range[0] if inst.price_range else 0.0
            )
            # One option contract = 100 shares equivalent (matches old auto_trader.py)
            total = price_for_check * computed_qty * 100
            if total > config.max_option_total_price:
                await _publish_skip(
                    task,
                    f"option total ${total:.2f} exceeds limit ${config.max_option_total_price}",
                )
                return
            if computed_qty > config.max_option_quantity:
                await _publish_skip(
                    task,
                    f"option quantity {computed_qty} exceeds limit {config.max_option_quantity}",
                )
                return
        else:
            computed_qty = inst.quantity or 1

        # ---- Deviation → order_type decision ----
        signal_price = inst.price if inst.price is not None else (
            inst.price_range[0] if inst.price_range else None
        )
        if signal_price is None:
            await _publish_skip(task, "no price available for submission")
            return

        # First-pass: market_price = signal_price (no real quote integration yet).
        # TODO: hook real quote via broker.get_quote(...) — currently always evaluates
        # to deviation=0 → MARKET. When real quotes land, this falls back to LIMIT
        # @ signal_price for stale signals.
        market_price = signal_price
        tolerance_pct = (
            page_settings.price_deviation_tolerance
            if page_settings is not None
            else _fallback_tolerance_pct(task.type)
        )
        deviation_pct = abs(market_price - signal_price) / signal_price * 100
        if deviation_pct <= tolerance_pct:
            order_type: OrderType = "MARKET"
            limit_price: float | None = None
        else:
            order_type = "LIMIT"
            limit_price = signal_price

        # ---- Submit ----
        task.mark_submitting()
        await bus.publish(Event(Topics.TASK_STATUS_CHANGED, TaskPayload(task)))
        started = time.perf_counter()
        try:
            order_id = _submit(
                client,
                inst,
                quantity=computed_qty,
                price=limit_price if limit_price is not None else signal_price,
                order_type=order_type,
            )
        except Exception as exc:
            elapsed = (time.perf_counter() - started) * 1000
            task.stage_timings["submit"] = elapsed
            task.mark_submit_failed(f"broker error: {exc}")
            logger.error(
                "Trader: order submission failed for task %s: %s",
                task.id, exc, exc_info=True,
            )
            await bus.publish(Event(Topics.TASK_SUBMIT_FAILED, TaskPayload(task)))
            return

        elapsed_ms = (time.perf_counter() - started) * 1000
        task.mark_submitted(order_id=order_id, timing_ms=elapsed_ms)
        logger.info(
            "Trader: submitted order %s for task %s in %.1f ms (type=%s, qty=%d)",
            order_id, task.id, elapsed_ms, order_type, computed_qty,
        )
        await bus.publish(Event(Topics.TASK_ORDER_SUBMITTED, TaskPayload(task)))

    return bus.subscribe(Topics.TASK_INSTRUCTION_READY, _handle_instruction_ready)


def _submit(
    client: BrokerClient,
    inst: Instruction,
    *,
    quantity: int,
    price: float,
    order_type: OrderType,
) -> str:
    """Dispatch to the appropriate broker method based on instruction subtype."""
    side: OrderSide = "BUY" if inst.instruction_type == InstructionType.BUY else "SELL"
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
