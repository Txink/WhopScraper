"""Schema-level smoke tests for the alerts + manual-orders migration."""
from __future__ import annotations

import pytest
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import AsyncEngine

from app.storage import schema  # noqa: F401 — register ORM


@pytest.mark.asyncio
async def test_tasks_has_source_and_last_replaced_at(engine: AsyncEngine) -> None:
    async with engine.connect() as conn:
        cols = await conn.run_sync(lambda c: {c["name"] for c in inspect(c).get_columns("tasks")})
    assert "source" in cols
    assert "last_replaced_at" in cols


@pytest.mark.asyncio
async def test_alerts_table_columns(engine: AsyncEngine) -> None:
    async with engine.connect() as conn:
        cols = await conn.run_sync(lambda c: {c["name"] for c in inspect(c).get_columns("alerts")})
    expected = {
        "id", "ticker", "symbol", "condition_type", "operator", "threshold",
        "pct_change_baseline", "volume_window", "repeat_mode", "cooldown_seconds",
        "enabled", "note", "created_at", "last_triggered_at", "trigger_count",
    }
    assert expected <= cols


@pytest.mark.asyncio
async def test_alert_events_table_columns(engine: AsyncEngine) -> None:
    async with engine.connect() as conn:
        cols = await conn.run_sync(lambda c: {c["name"] for c in inspect(c).get_columns("alert_events")})
    expected = {
        "id", "alert_id", "triggered_at", "ticker", "symbol",
        "snapshot_price", "snapshot_pct", "snapshot_volume", "message",
    }
    assert expected <= cols
