"""AlertEngine — continuously evaluates enabled alerts against LongPort
quote pushes; fires via EventBus + AlertRepo.record_trigger.

Threading model: broker pushes arrive on an SDK background thread. The
engine's ``_on_quote`` callback marshals into the asyncio event loop
via ``loop.call_soon_threadsafe(asyncio.create_task, ...)``.
"""
from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any, Protocol

from app.alerts.conditions import (
    VolumeWindowState,
    evaluate_pct_change,
    evaluate_price,
    evaluate_volume,
    format_message,
)
from app.alerts.repo import AlertRepo
from app.alerts.schemas import AlertOut
from app.core.event_bus import Event, EventBus
from app.core.events import Topics

logger = logging.getLogger(__name__)


class QuoteBroker(Protocol):
    def subscribe_quotes(self, symbols: list[str]) -> None: ...
    def unsubscribe_quotes(self, symbols: list[str]) -> None: ...
    def set_on_quote(self, cb: Any) -> None: ...
    def is_noop(self) -> bool: ...


class AlertEngine:
    def __init__(
        self,
        *,
        repo: AlertRepo,
        broker: QuoteBroker,
        event_bus: EventBus,
    ) -> None:
        self._repo = repo
        self._broker = broker
        self._bus = event_bus
        self._alerts_by_symbol: dict[str, dict[int, AlertOut]] = defaultdict(dict)
        self._volume_state: dict[tuple[str, str], VolumeWindowState] = {}
        self._loop: asyncio.AbstractEventLoop | None = None

    async def start(self) -> None:
        self._loop = asyncio.get_running_loop()
        if self._broker.is_noop():
            logger.info("AlertEngine: broker is NoopBroker — skipping quote subscription")
            return
        self._broker.set_on_quote(self._on_quote_threadsafe)
        enabled = await self._repo.list_enabled()
        for a in enabled:
            self._alerts_by_symbol[a.symbol][a.id] = a
        symbols = list(self._alerts_by_symbol.keys())
        if symbols:
            self._broker.subscribe_quotes(symbols)
        logger.info("AlertEngine started: %d alerts, %d symbols", len(enabled), len(symbols))

    async def stop(self) -> None:
        for sym in list(self._alerts_by_symbol.keys()):
            self._broker.unsubscribe_quotes([sym])
        self._alerts_by_symbol.clear()
        self._volume_state.clear()

    async def on_alert_changed(self, action: str, alert: AlertOut) -> None:
        """Invoked by AlertsService after every CRUD operation."""
        sym = alert.symbol
        had_symbol = bool(self._alerts_by_symbol.get(sym))
        if action == "deleted":
            self._alerts_by_symbol[sym].pop(alert.id, None)
        elif action in ("created", "updated", "toggled"):
            if alert.enabled:
                self._alerts_by_symbol[sym][alert.id] = alert
            else:
                self._alerts_by_symbol[sym].pop(alert.id, None)
        now_has = bool(self._alerts_by_symbol.get(sym))
        if not had_symbol and now_has:
            if not self._broker.is_noop():
                self._broker.subscribe_quotes([sym])
        elif had_symbol and not now_has:
            if not self._broker.is_noop():
                self._broker.unsubscribe_quotes([sym])
            for key in list(self._volume_state.keys()):
                if key[0] == sym:
                    self._volume_state.pop(key, None)

    def _on_quote_threadsafe(self, symbol: str, payload: dict[str, Any]) -> None:
        loop = self._loop
        if loop is None:
            return
        loop.call_soon_threadsafe(asyncio.create_task, self._evaluate_quote(symbol, payload))

    async def _evaluate_quote(self, symbol: str, quote: dict[str, Any]) -> None:
        alerts = list(self._alerts_by_symbol.get(symbol, {}).values())
        if not alerts:
            return
        last_done = float(quote.get("last_done") or 0.0)
        if last_done <= 0:
            return
        open_ = float(quote.get("open") or 0.0)
        prev_close = float(quote.get("prev_close") or 0.0)
        ts: datetime = quote.get("timestamp") or datetime.now(UTC)
        cumulative_volume = float(quote.get("volume") or 0.0)

        for alert in alerts:
            try:
                hit = self._evaluate_one(
                    alert, last_done=last_done, open_=open_,
                    prev_close=prev_close, cumulative_volume=cumulative_volume, ts=ts,
                )
            except Exception:
                logger.exception("alert evaluation error id=%s", alert.id)
                continue
            if not hit:
                continue
            fresh = await self._repo.get(alert.id)
            if fresh is None or not fresh.enabled:
                continue
            if fresh.last_triggered_at is not None:
                age = (ts - fresh.last_triggered_at).total_seconds()
                if age < fresh.cooldown_seconds:
                    continue
            await self._fire(
                fresh, last_done=last_done, open_=open_,
                prev_close=prev_close,
                volume_state=self._volume_state.get((symbol, fresh.volume_window or "")),
                ts=ts,
            )

    def _evaluate_one(
        self,
        alert: AlertOut,
        *,
        last_done: float,
        open_: float,
        prev_close: float,
        cumulative_volume: float,
        ts: datetime,
    ) -> bool:
        if alert.condition_type == "price":
            return evaluate_price(
                last_done=last_done, operator=alert.operator, threshold=alert.threshold,
            )
        if alert.condition_type == "pct_change":
            return evaluate_pct_change(
                last_done=last_done, baseline_open=open_,
                baseline_prev_close=prev_close,
                baseline=alert.pct_change_baseline or "today_open",
                operator=alert.operator, threshold=alert.threshold,
            )
        window_seconds = 60 if alert.volume_window == "1min" else 300
        key = (alert.symbol, alert.volume_window or "")
        state = self._volume_state.get(key)
        if state is None:
            state = VolumeWindowState(window_seconds=window_seconds)
            self._volume_state[key] = state
        state.observe(ts, cumulative_volume)
        return evaluate_volume(state, operator=alert.operator, threshold=alert.threshold)

    async def _fire(
        self,
        alert: AlertOut,
        *,
        last_done: float,
        open_: float,
        prev_close: float,
        volume_state: VolumeWindowState | None,
        ts: datetime,
    ) -> None:
        pct = None
        if alert.condition_type == "pct_change":
            baseline = alert.pct_change_baseline or "today_open"
            ref = open_ if baseline == "today_open" else prev_close
            if ref > 0:
                pct = (last_done - ref) / ref * 100.0
        vol = volume_state.window_volume() if volume_state else None
        message = format_message(
            ticker=alert.ticker, condition_type=alert.condition_type,
            operator=alert.operator, threshold=alert.threshold,
            snapshot_price=last_done, snapshot_pct=pct, snapshot_volume=vol,
        )
        try:
            event = await self._repo.record_trigger(
                alert_id=alert.id, triggered_at=ts,
                snapshot_price=last_done, snapshot_pct=pct, snapshot_volume=vol,
                message=message,
            )
        except Exception:
            logger.exception("record_trigger failed alert_id=%s", alert.id)
            return
        if alert.repeat_mode == "one_shot":
            await self.on_alert_changed("toggled", alert.model_copy(update={"enabled": False}))
        await self._bus.publish(Event(Topics.ALERT_TRIGGERED, {
            "event": event.model_dump(mode="json"),
            "alert": alert.model_dump(mode="json"),
        }))
