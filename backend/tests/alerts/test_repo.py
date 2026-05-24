"""AlertRepo CRUD against in-memory SQLite."""
from __future__ import annotations

from datetime import UTC, datetime

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
    now = datetime.now(UTC)
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
    now = datetime.now(UTC)
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
