"""AlertsService — CRUD wrapper that pre-validates symbol + notifies engine."""
from __future__ import annotations

import pytest

from app.alerts.schemas import AlertCreate, AlertUpdate
from app.alerts.service import AlertsService, SymbolUnknown


class FakeEngine:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int]] = []

    async def on_alert_changed(self, action, alert):
        self.calls.append((action, alert.id))


class GoodBroker:
    def get_quote(self, symbols): return {s: {"last_done": 100.0} for s in symbols}


class BadBroker:
    def get_quote(self, symbols): return {}


@pytest.mark.asyncio
async def test_create_validates_symbol(repo):
    svc = AlertsService(repo=repo, engine=FakeEngine(), broker=BadBroker())
    with pytest.raises(SymbolUnknown):
        await svc.create(AlertCreate(
            ticker="ZZZZ", symbol="ZZZZ.US", condition_type="price",
            operator=">=", threshold=1.0,
        ))


@pytest.mark.asyncio
async def test_create_notifies_engine(repo):
    eng = FakeEngine()
    svc = AlertsService(repo=repo, engine=eng, broker=GoodBroker())
    out = await svc.create(AlertCreate(
        ticker="AAPL", symbol="AAPL.US", condition_type="price",
        operator=">=", threshold=200.0,
    ))
    assert ("created", out.id) in eng.calls


@pytest.mark.asyncio
async def test_update_notifies_engine(repo):
    eng = FakeEngine()
    svc = AlertsService(repo=repo, engine=eng, broker=GoodBroker())
    a = await svc.create(AlertCreate(
        ticker="AAPL", symbol="AAPL.US", condition_type="price",
        operator=">=", threshold=200.0,
    ))
    await svc.update(a.id, AlertUpdate(threshold=205.0))
    assert ("updated", a.id) in eng.calls


@pytest.mark.asyncio
async def test_delete_notifies_engine(repo):
    eng = FakeEngine()
    svc = AlertsService(repo=repo, engine=eng, broker=GoodBroker())
    a = await svc.create(AlertCreate(
        ticker="AAPL", symbol="AAPL.US", condition_type="price",
        operator=">=", threshold=200.0,
    ))
    await svc.delete(a.id)
    assert ("deleted", a.id) in eng.calls
