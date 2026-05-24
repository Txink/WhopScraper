"""§11+ acceptance: create alert → fire quote → triggered event observable
via WS + /api/alerts/events; one_shot disables after first hit.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest


@pytest.mark.asyncio
async def test_acceptance_alert_fires_and_disables(client, fake_broker) -> None:
    r = await client.post("/api/alerts", json={
        "ticker": "AAPL", "symbol": "AAPL.US",
        "condition_type": "price", "operator": ">=", "threshold": 200.0,
        "repeat_mode": "one_shot",
    })
    assert r.status_code == 201
    alert_id = r.json()["id"]

    # 2. Broker is subscribed to AAPL.US (this depends on fake_broker's API)
    assert "AAPL.US" in fake_broker.subscribed

    # 3. Fire a quote above threshold
    fake_broker.fire_quote("AAPL.US", {
        "last_done": 200.15, "open": 198.0, "prev_close": 198.5,
        "volume": 1_000_000, "timestamp": datetime.now(timezone.utc),
    })
    await asyncio.sleep(0.2)

    # 4. /api/alerts/events shows it
    r = await client.get("/api/alerts/events?ticker=AAPL")
    events = r.json()["events"]
    assert len(events) >= 1
    assert events[0]["alert_id"] == alert_id

    # 5. one_shot disabled
    r = await client.get("/api/alerts?ticker=AAPL")
    a = next(a for a in r.json()["alerts"] if a["id"] == alert_id)
    assert a["enabled"] is False
    assert a["trigger_count"] == 1


@pytest.mark.asyncio
async def test_acceptance_alert_recurring_throttled(client, fake_broker) -> None:
    r = await client.post("/api/alerts", json={
        "ticker": "AAPL", "symbol": "AAPL.US",
        "condition_type": "price", "operator": ">=", "threshold": 200.0,
        "repeat_mode": "recurring", "cooldown_seconds": 60,
    })
    assert r.status_code == 201

    quote = {
        "last_done": 200.15, "open": 198.0, "prev_close": 198.5,
        "volume": 1_000_000, "timestamp": datetime.now(timezone.utc),
    }
    fake_broker.fire_quote("AAPL.US", quote)
    await asyncio.sleep(0.1)
    fake_broker.fire_quote("AAPL.US", quote)
    await asyncio.sleep(0.1)

    r = await client.get("/api/alerts/events?ticker=AAPL")
    assert len(r.json()["events"]) == 1
