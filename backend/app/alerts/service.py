"""CRUD wrapper that pre-validates with the broker and notifies the
running AlertEngine after every change. Emits ALERT_CHANGED on the bus.
"""
from __future__ import annotations

from typing import Protocol

from app.alerts.repo import AlertRepo
from app.alerts.schemas import AlertCreate, AlertOut, AlertUpdate
from app.core.event_bus import Event, EventBus
from app.core.events import Topics


class SymbolUnknown(ValueError):
    """Raised when broker.get_quote returns no entry for the symbol."""


class Engine(Protocol):
    async def on_alert_changed(self, action: str, alert: AlertOut) -> None: ...


class QuoteBroker(Protocol):
    def get_quote(self, symbols: list[str]) -> dict[str, dict[str, object]]: ...


class AlertsService:
    def __init__(
        self,
        *,
        repo: AlertRepo,
        engine: Engine,
        broker: QuoteBroker,
        event_bus: EventBus | None = None,
    ) -> None:
        self._repo = repo
        self._engine = engine
        self._broker = broker
        self._bus = event_bus

    async def create(self, req: AlertCreate) -> AlertOut:
        try:
            quote = self._broker.get_quote([req.symbol])
        except Exception as e:
            raise SymbolUnknown(f"broker rejected symbol: {e}") from e
        if not quote or req.symbol not in quote:
            raise SymbolUnknown(f"unknown symbol: {req.symbol}")
        out = await self._repo.create(req)
        await self._engine.on_alert_changed("created", out)
        await self._publish("created", out)
        return out

    async def update(self, alert_id: int, req: AlertUpdate) -> AlertOut:
        before = await self._repo.get(alert_id)
        if before is None:
            raise KeyError(alert_id)
        after = await self._repo.update(alert_id, req)
        toggled = req.enabled is not None and before.enabled != after.enabled
        action = "toggled" if toggled else "updated"
        await self._engine.on_alert_changed(action, after)
        await self._publish(action, after)
        return after

    async def delete(self, alert_id: int) -> None:
        existing = await self._repo.get(alert_id)
        if existing is None:
            return
        await self._repo.delete(alert_id)
        await self._engine.on_alert_changed("deleted", existing)
        await self._publish("deleted", existing)

    async def _publish(self, action: str, alert: AlertOut) -> None:
        if self._bus is None:
            return
        await self._bus.publish(Event(Topics.ALERT_CHANGED, {
            "action": action, "alert": alert.model_dump(mode="json"),
        }))
