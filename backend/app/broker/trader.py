"""Trader — subscribes to TASK_INSTRUCTION_READY, validates, submits orders.

Behavior (Task G):
- Looks up the per-page ``PageSettings`` by ``task.message.url`` via the
  ``WhopRegistry`` reverse-index. ``None`` => orphan task → use
  ``instruction.quantity``.
- Stock whitelist gate: if page settings has tickers, ticker must be in whitelist
  or task is SKIPPED with a clear reason.
- Stock qty: ``max(int(trade_quantity * position_size_to_fraction(position_size)), 1)``.
- Option qty: derived from per-page option settings (quantity rule / total-limit
  rule, independently switchable). If both are disabled, task is SKIPPED.
- Order type is always LIMIT. Limit price tracks the live ``last_done`` when
  it's more favorable than the signal (lower for BUY, higher for SELL),
  snapped to the $0.01 grid (floor for BUY, ceil for SELL) so the broker
  accepts the price; otherwise it stays at the signal price. If the quote is
  missing/invalid, LIMIT @ signal. ``submit_order_type``,
  ``submit_order_context`` and ``submit_quote_last_done`` on ``Task`` record
  the decision for API/UI and are kept on submission failure for debuggability.

Deferred:
- Optional: revive ``price_deviation_tolerance`` for additional bands.
- Stop-loss / take-profit follow-up orders.
- MODIFY / CLOSE instruction types.
- Cancel order API.
- ``asyncio.to_thread`` wrapping for blocking SDK calls.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from datetime import datetime
from decimal import ROUND_DOWN, ROUND_UP, Decimal
from typing import TYPE_CHECKING, Any, cast

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.broker.broker_client import BrokerClient, OrderSide, OrderType
from app.broker.config import LongPortConfig
from app.broker.order_id_norm import normalize_broker_order_id
from app.broker.validation import validate_for_submission
from app.core.event_bus import Event, EventBus
from app.core.events import TaskPayload, Topics
from app.domain.instruction import (
    Instruction,
    InstructionType,
    OptionInstruction,
    StockInstruction,
)
from app.domain.task import Task
from app.storage.db import session_scope
from app.storage.repo import TaskQueryRepo, save_task
from app.whop.page_settings import position_size_to_fraction, sell_quantity_to_fraction

if TYPE_CHECKING:
    from app.broker.push_listener import PushListener
    from app.whop.page_settings import PageSettings

logger = logging.getLogger(__name__)


_CENT = Decimal("0.01")


def _floor_to_cent(price: float) -> float:
    """Round *price* DOWN to the $0.01 grid (BUY-side snap)."""
    return float(Decimal(str(price)).quantize(_CENT, rounding=ROUND_DOWN))


def _ceil_to_cent(price: float) -> float:
    """Round *price* UP to the $0.01 grid (SELL-side snap)."""
    return float(Decimal(str(price)).quantize(_CENT, rounding=ROUND_UP))


def _last_done_from_quotes(quotes: dict[str, dict[str, Any]], symbol: str) -> float | None:
    """Extract a positive last_done for *symbol* from ``get_quote`` output."""
    row = quotes.get(symbol)
    if not row:
        return None
    raw = row.get("last_done")
    if raw is None:
        return None
    try:
        v = float(raw)
    except (TypeError, ValueError):
        return None
    if v <= 0.0:
        return None
    return v


def _decide_order_type_and_context(
    *,
    side: InstructionType,
    signal_price: float,
    last_done: float | None,
) -> tuple[OrderType, float | None, str]:
    """Return ``(order_type, submit_price, rationale_cn)``.

    Always emits LIMIT orders. When the live quote is more favorable than the
    signal price (lower for BUY, higher for SELL), the limit price tracks the
    live quote — otherwise it stays at the signal price. ``submit_price`` is
    the limit price (always non-None on the live path; the ``float | None`` return
    shape is preserved only because ``OrderType`` still permits ``"MARKET"`` for
    protocol-layer compatibility).
    """
    if last_done is None:
        return (
            "LIMIT",
            signal_price,
            f"未取到有效现价 → 限价单 @ {signal_price:.3f}",
        )
    if side == InstructionType.BUY:
        if last_done < signal_price:
            snapped = _floor_to_cent(last_done)
            return (
                "LIMIT",
                snapped,
                f"买入：现价 {last_done:.3f} < 信号价 {signal_price:.3f}"
                f" → 限价单 @ {snapped:.2f}（取更低价，向下取整到分）",
            )
        return (
            "LIMIT",
            signal_price,
            f"买入：现价 {last_done:.3f} ≥ 信号价 {signal_price:.3f} → 限价单 @ {signal_price:.3f}",
        )
    if side == InstructionType.SELL:
        if last_done > signal_price:
            snapped = _ceil_to_cent(last_done)
            return (
                "LIMIT",
                snapped,
                f"卖出：现价 {last_done:.3f} > 信号价 {signal_price:.3f}"
                f" → 限价单 @ {snapped:.2f}（取更高价，向上取整到分）",
            )
        return (
            "LIMIT",
            signal_price,
            f"卖出：现价 {last_done:.3f} ≤ 信号价 {signal_price:.3f} → 限价单 @ {signal_price:.3f}",
        )
    return "LIMIT", signal_price, f"未知方向 → 限价单 @ {signal_price:.3f}"


def _format_broker_error(exc: BaseException) -> str:
    """Reduce a broker exception to a user-facing reject_reason.

    longport's ``OpenApiException`` stringifies as
    ``"OpenApiException: (kind=..., code=..., trace_id=...) <message>"``,
    which exposes internals to the UI. When the exception carries the
    distinctive structural fields, surface only ``code`` + ``message``;
    otherwise fall back to ``str(exc)``. The full traceback still goes to
    the logger via ``exc_info=True`` at the call site.
    """
    code = getattr(exc, "code", None)
    message = getattr(exc, "message", None)
    if (
        code is not None
        and isinstance(message, str)
        and getattr(exc, "kind", None) is not None
        and getattr(exc, "trace_id", None) is not None
    ):
        return f"broker [{code}] {message}"
    return f"broker error: {exc}"


async def _qty_for_whitelisted_stock(
    inst: StockInstruction,
    ticker_upper: str,
    page_settings: "PageSettings",
    *,
    task_query_repo: TaskQueryRepo | None,
    now: datetime,
) -> int:
    """Compute submit qty for a whitelisted stock task.

    Lot path: if instruction carries (referenced_lot_price, sell_quantity)
    and a TaskQueryRepo is injected, look up the most recent reverse-side
    task and multiply by sell_quantity_to_fraction(...). Falls through to
    the default page-settings × position_size path on any miss / missing
    precondition.
    """
    if (
        inst.referenced_lot_price is not None
        and inst.sell_quantity is not None
        and task_query_repo is not None
    ):
        opposite = (
            InstructionType.BUY
            if inst.instruction_type == InstructionType.SELL
            else InstructionType.SELL
        )
        try:
            prior_qty = await task_query_repo.find_recent_task_by_ref(
                ticker=ticker_upper,
                side=opposite,
                price=inst.referenced_lot_price,
                before=now,
                window_hours=24 * 7,
            )
        except Exception as exc:  # noqa: BLE001 — Decision 6: never block submission on lookup failure
            logger.warning(
                "Trader: lot lookup failed for %s @%.4f (%s); falling back to default qty",
                ticker_upper,
                inst.referenced_lot_price,
                exc,
            )
            prior_qty = None

        if prior_qty is not None:
            fraction = sell_quantity_to_fraction(inst.sell_quantity)
            qty = max(int(prior_qty * fraction), 1)
            logger.info(
                "Trader: lot ref @%.4f qty=%d × %s → %d (ticker=%s)",
                inst.referenced_lot_price,
                prior_qty,
                inst.sell_quantity,
                qty,
                ticker_upper,
            )
            return qty
        # Either no row matched (the original miss path) OR the repo raised
        # (already logged WARN above). For the empty-miss case, log INFO so
        # operators can see why the fallback fired even when the ref looked OK.
        logger.info(
            "Trader: no prior %s within 7d for %s @%.4f, falling back to default qty",
            opposite.value,
            ticker_upper,
            inst.referenced_lot_price,
        )

    base_qty = page_settings.tickers[ticker_upper].trade_quantity
    fraction = position_size_to_fraction(inst.position_size)
    return max(int(base_qty * fraction), 1)


def register_trader(
    bus: EventBus,
    client: BrokerClient,
    config: LongPortConfig,
    *,
    registry: Any | None = None,
    auto_trade_getter: Callable[[], bool] | None = None,
    task_query_repo: TaskQueryRepo | None = None,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
    push_listener: "PushListener | None" = None,
) -> Callable[[], None]:
    """Subscribe trader handler to TASK_INSTRUCTION_READY.

    Parameters
    ----------
    bus, client, config:
        Standard wiring.
    registry:
        WhopRegistry-like object exposing ``get_settings_for_url(url)`` →
        ``PageSettings | None``. If ``None``, every task is treated as an
        "orphan" (no page settings) and falls back to ``instruction.quantity``.
        Per-page ``price_deviation_tolerance`` is not used for LIMIT submit-price selection
        (decision uses broker ``get_quote`` vs signal price).
    task_query_repo:
        Optional ``TaskQueryRepo``. When provided, instructions carrying both
        ``referenced_lot_price`` and ``sell_quantity`` resolve qty via the
        prior reverse-side task. None disables the path entirely.
    session_factory:
        When provided, after a successful broker submit the trader awaits
        ``save_task`` before publishing ``TASK_ORDER_SUBMITTED``. That way the
        tasks row carries ``order_id`` before the event loop can run concurrent
        PushListener lookups (avoids dropped FILLED pushes when storage lagged
        behind fire-and-forget bus handlers).
    push_listener:
        When provided, the trader calls ``push_listener.replay_for_order(...)``
        right after ``save_task`` commits. This drains any pushes the SDK fired
        while ``_submit`` was blocking the loop — the buffer in PushListener
        holds them under ``order_id`` precisely so they survive the gap between
        broker submit and DB commit, with no in-process registry needed.

    Returns the unsubscribe callable.
    """

    async def _publish_skip(task: Task, reason: str) -> None:
        task.mark_skipped(reason)
        await bus.publish(Event(Topics.TASK_STATUS_CHANGED, TaskPayload(task)))

    def _resolve_settings(task: Task) -> PageSettings | None:
        if registry is None:
            return None
        # registry is duck-typed (Any) to avoid a circular import; cast back so
        # the trader has a typed view of its only consumed method.
        return cast("PageSettings | None", registry.get_settings_for_url(task.message.url))

    async def _handle_instruction_ready(event: Event) -> None:
        payload = event.payload
        if not isinstance(payload, TaskPayload):
            return
        task: Task = payload.task
        inst: Instruction | None = task.instruction
        if inst is None:
            return

        page_settings = _resolve_settings(task)

        # ============== 完整信息校验节点 (gate ①) ==============
        # Order: whitelist → historical → validate_for_submission

        # ① a. Whitelist check (stock with configured tickers only).
        if (
            isinstance(inst, StockInstruction)
            and page_settings is not None
            and page_settings.tickers is not None
        ):
            ticker_upper = (inst.ticker or "").upper()
            if ticker_upper not in page_settings.tickers:
                await _publish_skip(task, f"{ticker_upper} 不在白名单")
                return

        # ① b. Historical-message check (per-page setting).
        # The listener tagged this task at capture time when
        # message.posted_at was earlier than the listener's started_at.
        # Setting + marker → SKIP (parse-only, do not order).
        if (
            page_settings is not None
            and page_settings.block_historical_messages
            and task.is_historical
        ):
            await _publish_skip(
                task,
                f"历史消息（posted={task.message.posted_at}）",
            )
            return

        # ① c. Parameter completeness — ticker + side + price (for stock);
        # ticker + side + price + strike + CP + expiry (for option).
        reason = validate_for_submission(inst)
        if reason is not None:
            await _publish_skip(task, reason)
            return

        # ============== auto_trade 节点 (gate ②) ==============
        auto_trade_enabled = (
            auto_trade_getter() if auto_trade_getter is not None else config.auto_trade
        )
        if not auto_trade_enabled:
            task.reject_reason = "auto_trade disabled in config; awaiting manual confirmation"
            await bus.publish(Event(Topics.TASK_STATUS_CHANGED, TaskPayload(task)))
            return

        # ============== 既有防御 / 数量 / 偏离 / 下单 (gate ③+) ==============
        # Defensive (unreachable when gates ①+② were honored).
        if not getattr(inst, "symbol", None):
            await _publish_skip(task, "instruction missing symbol")
            return
        if inst.instruction_type not in (InstructionType.BUY, InstructionType.SELL):
            await _publish_skip(task, f"unsupported instruction type: {inst.instruction_type}")
            return

        # ---- qty calc + per-asset gates ----
        if isinstance(inst, StockInstruction):
            ticker_upper = (inst.ticker or "").upper()
            if page_settings is not None and page_settings.tickers is not None:
                computed_qty = await _qty_for_whitelisted_stock(
                    inst,
                    ticker_upper,
                    page_settings,
                    task_query_repo=task_query_repo,
                    now=task.created_at,
                )
            else:
                # Orphan stock task — fall back to instruction.quantity
                computed_qty = inst.quantity or 0
                if computed_qty <= 0:
                    await _publish_skip(task, "orphan stock task missing instruction.quantity")
                    return
        elif isinstance(inst, OptionInstruction):
            price_for_check = (
                inst.price
                if inst.price is not None
                else (inst.price_range[0] if inst.price_range else 0.0)
            )
            option_qty_enabled = (
                page_settings.option_buy_quantity_enabled if page_settings is not None else False
            )
            option_total_enabled = (
                page_settings.option_total_price_limit_enabled if page_settings is not None else False
            )
            if page_settings is not None and not option_qty_enabled and not option_total_enabled:
                await _publish_skip(
                    task,
                    "option settings: both quantity and total-limit rules are disabled",
                )
                return

            qty_by_config: int | None = None
            if option_qty_enabled:
                qty_by_config = page_settings.option_buy_quantity if page_settings is not None else None
                if qty_by_config is None or qty_by_config <= 0:
                    await _publish_skip(task, "option settings: invalid option_buy_quantity")
                    return

            qty_by_total: int | None = None
            if option_total_enabled:
                if page_settings is None or page_settings.option_total_price_limit is None:
                    await _publish_skip(task, "option settings: missing option_total_price_limit")
                    return
                if price_for_check <= 0:
                    await _publish_skip(task, "option settings: no valid option price for total-limit")
                    return
                per_contract_total = price_for_check * 100
                qty_by_total = int(page_settings.option_total_price_limit // per_contract_total)
                if qty_by_total <= 0:
                    await _publish_skip(
                        task,
                        "option settings: total-limit too small for even one contract",
                    )
                    return

            if qty_by_config is not None and qty_by_total is not None:
                computed_qty = min(qty_by_config, qty_by_total)
            elif qty_by_config is not None:
                computed_qty = qty_by_config
            elif qty_by_total is not None:
                computed_qty = qty_by_total
            else:
                # Orphan option task or legacy page without local option controls.
                computed_qty = inst.quantity or 1

        else:
            computed_qty = inst.quantity or 1

        # Persist the resolved execution quantity back onto instruction so
        # API task payloads can render QTY/TOTAL consistently in the frontend.
        inst.quantity = computed_qty

        # ---- Signal price + quote → LIMIT submit price ----
        signal_price = (
            inst.price
            if inst.price is not None
            else (inst.price_range[0] if inst.price_range else None)
        )
        if signal_price is None:
            await _publish_skip(task, "no price available for submission")
            return

        symbol = getattr(inst, "symbol", "") or getattr(inst, "ticker", "")
        last_done: float | None = None
        try:
            quotes = await asyncio.to_thread(client.get_quote, [symbol])
            last_done = _last_done_from_quotes(quotes, symbol)
        except Exception as exc:  # noqa: BLE001 — quote failure is non-fatal
            logger.warning(
                "Trader: get_quote failed for %s (%s); falling back to LIMIT @ signal",
                symbol,
                exc,
            )

        order_type, submit_price, rationale = _decide_order_type_and_context(
            side=inst.instruction_type,
            signal_price=signal_price,
            last_done=last_done,
        )
        task.submit_order_type = order_type
        task.submit_order_context = rationale
        task.submit_quote_last_done = last_done

        # ---- Submit ----
        task.mark_submitting()
        await bus.publish(Event(Topics.TASK_STATUS_CHANGED, TaskPayload(task)))
        started = time.perf_counter()
        try:
            order_id = _submit(
                client,
                inst,
                quantity=computed_qty,
                price=submit_price,
                order_type=order_type,
            )
        except Exception as exc:
            elapsed = (time.perf_counter() - started) * 1000
            task.stage_timings["submit"] = elapsed
            task.mark_submit_failed(_format_broker_error(exc))
            logger.error(
                "Trader: order submission failed for task %s: %s",
                task.id,
                exc,
                exc_info=True,
            )
            await bus.publish(Event(Topics.TASK_SUBMIT_FAILED, TaskPayload(task)))
            return

        elapsed_ms = (time.perf_counter() - started) * 1000
        order_id_str = normalize_broker_order_id(order_id)
        if not order_id_str:
            task.stage_timings["submit"] = elapsed_ms
            task.mark_submit_failed("broker returned empty order_id")
            logger.error("Trader: broker returned empty order_id for task %s", task.id)
            await bus.publish(Event(Topics.TASK_SUBMIT_FAILED, TaskPayload(task)))
            return
        task.mark_submitted(order_id=order_id_str, timing_ms=elapsed_ms)
        logger.info(
            "Trader: submitted order %s for task %s in %.1f ms (type=%s, qty=%d)",
            order_id_str,
            task.id,
            elapsed_ms,
            order_type,
            computed_qty,
        )
        # Persist the order_id ↔ task_id binding before letting the loop run
        # other coroutines, so PushListener.replay_for_order (and any later
        # live push) can resolve the task by order_id from a fresh DB session.
        if session_factory is not None:
            async with session_scope(session_factory) as session:
                await save_task(session, task)
        # Drain any pushes that arrived while _submit was blocking the loop.
        # They were buffered by order_id in PushListener; replay processes
        # them in arrival order against the now-committed task row.
        if push_listener is not None:
            await push_listener.replay_for_order(order_id_str)
        await bus.publish(Event(Topics.TASK_ORDER_SUBMITTED, TaskPayload(task)))

    return bus.subscribe(Topics.TASK_INSTRUCTION_READY, _handle_instruction_ready)


def _submit(
    client: BrokerClient,
    inst: Instruction,
    *,
    quantity: int,
    price: float | None,
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
