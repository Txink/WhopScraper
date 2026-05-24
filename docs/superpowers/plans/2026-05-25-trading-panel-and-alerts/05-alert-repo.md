# Task 5: Alert Repo (SQLAlchemy CRUD)

**Files:**
- Create: `backend/app/alerts/repo.py`, `backend/app/alerts/schemas.py`
- Test: `backend/tests/alerts/test_repo.py`

## Steps

- [ ] **Step 1: Define schemas**

`backend/app/alerts/schemas.py`:

```python
"""Pydantic schemas for /api/alerts/* and internal repo I/O."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

ConditionType = Literal["price", "pct_change", "volume"]
Operator = Literal[">=", "<="]
Baseline = Literal["today_open", "prev_close"]
VolumeWindow = Literal["1min", "5min"]
RepeatMode = Literal["one_shot", "recurring"]


class AlertCreate(BaseModel):
    ticker: str = Field(min_length=1)
    symbol: str = Field(min_length=1)
    condition_type: ConditionType
    operator: Operator
    threshold: float
    pct_change_baseline: Baseline | None = None
    volume_window: VolumeWindow | None = None
    repeat_mode: RepeatMode = "one_shot"
    cooldown_seconds: int = Field(default=300, ge=0)
    note: str | None = None


class AlertUpdate(BaseModel):
    operator: Operator | None = None
    threshold: float | None = None
    pct_change_baseline: Baseline | None = None
    volume_window: VolumeWindow | None = None
    repeat_mode: RepeatMode | None = None
    cooldown_seconds: int | None = Field(default=None, ge=0)
    enabled: bool | None = None
    note: str | None = None


class AlertOut(BaseModel):
    id: int
    ticker: str
    symbol: str
    condition_type: ConditionType
    operator: Operator
    threshold: float
    pct_change_baseline: Baseline | None
    volume_window: VolumeWindow | None
    repeat_mode: RepeatMode
    cooldown_seconds: int
    enabled: bool
    note: str | None
    created_at: datetime
    last_triggered_at: datetime | None
    trigger_count: int


class AlertEventOut(BaseModel):
    id: int
    alert_id: int
    triggered_at: datetime
    ticker: str
    symbol: str
    snapshot_price: float
    snapshot_pct: float | None
    snapshot_volume: float | None
    message: str


class AlertListOut(BaseModel):
    alerts: list[AlertOut]


class AlertEventListOut(BaseModel):
    events: list[AlertEventOut]
```

- [ ] **Step 2: Write failing tests**

`backend/tests/alerts/test_repo.py`:

```python
"""AlertRepo CRUD against in-memory SQLite."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.alerts.repo import AlertRepo
from app.alerts.schemas import AlertCreate, AlertUpdate


@pytest.mark.asyncio
async def test_create_and_get(repo: AlertRepo) -> None:
    out = await repo.create(AlertCreate(
        ticker="AAPL", symbol="AAPL.US", condition_type="price",
        operator=">=", threshold=200.0,
    ))
    assert out.id > 0
    assert out.enabled is True
    again = await repo.list_by_ticker("AAPL")
    assert [a.id for a in again] == [out.id]


@pytest.mark.asyncio
async def test_update_enabled_toggle(repo: AlertRepo) -> None:
    a = await repo.create(AlertCreate(
        ticker="AAPL", symbol="AAPL.US", condition_type="price",
        operator=">=", threshold=200.0,
    ))
    updated = await repo.update(a.id, AlertUpdate(enabled=False))
    assert updated.enabled is False


@pytest.mark.asyncio
async def test_delete(repo: AlertRepo) -> None:
    a = await repo.create(AlertCreate(
        ticker="AAPL", symbol="AAPL.US", condition_type="price",
        operator=">=", threshold=200.0,
    ))
    await repo.delete(a.id)
    assert await repo.list_by_ticker("AAPL") == []


@pytest.mark.asyncio
async def test_list_enabled_filters_disabled(repo: AlertRepo) -> None:
    a = await repo.create(AlertCreate(
        ticker="AAPL", symbol="AAPL.US", condition_type="price",
        operator=">=", threshold=200.0,
    ))
    b = await repo.create(AlertCreate(
        ticker="NVDA", symbol="NVDA.US", condition_type="price",
        operator=">=", threshold=500.0,
    ))
    await repo.update(b.id, AlertUpdate(enabled=False))
    rows = await repo.list_enabled()
    assert [r.id for r in rows] == [a.id]


@pytest.mark.asyncio
async def test_record_trigger_one_shot_disables(repo: AlertRepo) -> None:
    a = await repo.create(AlertCreate(
        ticker="AAPL", symbol="AAPL.US", condition_type="price",
        operator=">=", threshold=200.0, repeat_mode="one_shot",
    ))
    now = datetime.now(timezone.utc)
    event = await repo.record_trigger(
        alert_id=a.id, triggered_at=now,
        snapshot_price=200.15, snapshot_pct=None, snapshot_volume=None,
        message="AAPL 触发 价格 ≥ $200.00",
    )
    assert event.id > 0
    again = (await repo.list_by_ticker("AAPL"))[0]
    assert again.enabled is False
    assert again.trigger_count == 1


@pytest.mark.asyncio
async def test_record_trigger_recurring_stays_enabled(repo: AlertRepo) -> None:
    a = await repo.create(AlertCreate(
        ticker="AAPL", symbol="AAPL.US", condition_type="price",
        operator=">=", threshold=200.0, repeat_mode="recurring",
    ))
    now = datetime.now(timezone.utc)
    await repo.record_trigger(
        alert_id=a.id, triggered_at=now,
        snapshot_price=200.15, snapshot_pct=None, snapshot_volume=None,
        message="x",
    )
    await repo.record_trigger(
        alert_id=a.id, triggered_at=now,
        snapshot_price=200.20, snapshot_pct=None, snapshot_volume=None,
        message="x",
    )
    again = (await repo.list_by_ticker("AAPL"))[0]
    assert again.enabled is True
    assert again.trigger_count == 2
```

- [ ] **Step 3: Run — verify failures**

```bash
cd backend && uv run pytest tests/alerts/test_repo.py -v
```

Expected: ImportError.

- [ ] **Step 4: Implement repo**

`backend/app/alerts/repo.py`:

```python
"""Async SQLAlchemy CRUD for alerts + alert_events.

`record_trigger` is a single-transaction operation: write the event,
update last_triggered_at + trigger_count, and (for one_shot) set
enabled=false. This guarantees the disable+event observation atomicity
needed by `AlertEngine._fire`.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable

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
                created_at=datetime.now(timezone.utc),
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
```

- [ ] **Step 5: Add `repo` fixture**

In `backend/tests/alerts/conftest.py`:

```python
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.alerts.repo import AlertRepo
from app.storage.db import Base


@pytest_asyncio.fixture
async def repo() -> AlertRepo:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield AlertRepo(factory)
    await engine.dispose()
```

- [ ] **Step 6: Run + verify**

```bash
cd backend && uv run pytest tests/alerts/test_repo.py -v
uv run mypy app/alerts
```

Expected: 6 pass; mypy clean.

- [ ] **Step 7: Commit**

```bash
git add backend/app/alerts/repo.py backend/app/alerts/schemas.py \
        backend/tests/alerts/test_repo.py backend/tests/alerts/conftest.py
git commit -m "$(cat <<'EOF'
feat(alerts): repo CRUD + schemas

AlertRepo wraps sync of alerts/alert_events tables. record_trigger is
single-transaction: writes the event, bumps trigger_count, sets
enabled=false for one_shot alerts.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```
