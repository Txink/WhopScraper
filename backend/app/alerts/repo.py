"""Async SQLAlchemy CRUD for alerts + alert_events.

`record_trigger` is a single-transaction operation: write the event,
update last_triggered_at + trigger_count, and (for one_shot) set
enabled=false. This guarantees the disable+event observation atomicity
needed by `AlertEngine._fire`.
"""
from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.alerts.schemas import AlertCreate, AlertEventOut, AlertOut, AlertUpdate
from app.storage.schema import AlertEventRow, AlertRow

SessionFactory = Callable[[], AsyncSession]


class AlertRepo:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._sessions = session_factory

    async def create(self, req: AlertCreate) -> AlertOut:
        async with self._sessions() as session:
            row = AlertRow(
                ticker=req.ticker, symbol=req.symbol,
                condition_type=req.condition_type, operator=req.operator,
                threshold=req.threshold,
                pct_change_baseline=req.pct_change_baseline,
                volume_window=req.volume_window,
                repeat_mode=req.repeat_mode,
                cooldown_seconds=req.cooldown_seconds,
                enabled=True,
                note=req.note,
                created_at=datetime.now(UTC),
                last_triggered_at=None,
                trigger_count=0,
            )
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return _to_out(row)

    async def update(self, alert_id: int, req: AlertUpdate) -> AlertOut:
        async with self._sessions() as session:
            row = (await session.execute(
                select(AlertRow).where(AlertRow.id == alert_id)
            )).scalar_one()
            for k, v in req.model_dump(exclude_unset=True).items():
                setattr(row, k, v)
            await session.commit()
            await session.refresh(row)
            return _to_out(row)

    async def delete(self, alert_id: int) -> None:
        async with self._sessions() as session:
            row = (await session.execute(
                select(AlertRow).where(AlertRow.id == alert_id)
            )).scalar_one_or_none()
            if row is None:
                return
            await session.delete(row)
            await session.commit()

    async def list_by_ticker(
        self, ticker: str, *, include_disabled: bool = True
    ) -> list[AlertOut]:
        async with self._sessions() as session:
            stmt = select(AlertRow).where(AlertRow.ticker == ticker)
            if not include_disabled:
                stmt = stmt.where(AlertRow.enabled.is_(True))
            stmt = stmt.order_by(AlertRow.id)
            return [_to_out(r) for r in (await session.execute(stmt)).scalars()]

    async def list_enabled(self) -> list[AlertOut]:
        async with self._sessions() as session:
            stmt = select(AlertRow).where(AlertRow.enabled.is_(True))
            return [_to_out(r) for r in (await session.execute(stmt)).scalars()]

    async def get(self, alert_id: int) -> AlertOut | None:
        async with self._sessions() as session:
            row = (await session.execute(
                select(AlertRow).where(AlertRow.id == alert_id)
            )).scalar_one_or_none()
            return _to_out(row) if row else None

    async def record_trigger(
        self,
        *,
        alert_id: int,
        triggered_at: datetime,
        snapshot_price: float,
        snapshot_pct: float | None,
        snapshot_volume: float | None,
        message: str,
    ) -> AlertEventOut:
        async with self._sessions() as session:
            row = (await session.execute(
                select(AlertRow).where(AlertRow.id == alert_id)
            )).scalar_one()
            event = AlertEventRow(
                alert_id=row.id, triggered_at=triggered_at,
                ticker=row.ticker, symbol=row.symbol,
                snapshot_price=snapshot_price,
                snapshot_pct=snapshot_pct, snapshot_volume=snapshot_volume,
                message=message,
            )
            session.add(event)
            row.last_triggered_at = triggered_at
            row.trigger_count += 1
            if row.repeat_mode == "one_shot":
                row.enabled = False
            await session.commit()
            await session.refresh(event)
            return AlertEventOut(
                id=event.id, alert_id=event.alert_id,
                triggered_at=event.triggered_at, ticker=event.ticker,
                symbol=event.symbol, snapshot_price=event.snapshot_price,
                snapshot_pct=event.snapshot_pct, snapshot_volume=event.snapshot_volume,
                message=event.message,
            )

    async def list_events(
        self, *, ticker: str | None = None, limit: int = 50
    ) -> list[AlertEventOut]:
        async with self._sessions() as session:
            stmt = select(AlertEventRow).order_by(AlertEventRow.triggered_at.desc()).limit(limit)
            if ticker is not None:
                stmt = stmt.where(AlertEventRow.ticker == ticker)
            return [
                AlertEventOut(
                    id=r.id, alert_id=r.alert_id, triggered_at=r.triggered_at,
                    ticker=r.ticker, symbol=r.symbol,
                    snapshot_price=r.snapshot_price,
                    snapshot_pct=r.snapshot_pct,
                    snapshot_volume=r.snapshot_volume, message=r.message,
                )
                for r in (await session.execute(stmt)).scalars()
            ]


def _to_out(row: AlertRow) -> AlertOut:
    return AlertOut(
        id=row.id, ticker=row.ticker, symbol=row.symbol,
        condition_type=row.condition_type, operator=row.operator,  # type: ignore[arg-type]
        threshold=row.threshold,
        pct_change_baseline=row.pct_change_baseline,  # type: ignore[arg-type]
        volume_window=row.volume_window,  # type: ignore[arg-type]
        repeat_mode=row.repeat_mode,  # type: ignore[arg-type]
        cooldown_seconds=row.cooldown_seconds, enabled=row.enabled,
        note=row.note, created_at=row.created_at,
        last_triggered_at=row.last_triggered_at,
        trigger_count=row.trigger_count,
    )
