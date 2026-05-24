# Task 13: Acceptance Tests (e2e)

Two new end-to-end integration tests sitting alongside `backend/tests/integration/test_acceptance.py`. Each exercises the full pipeline against an in-process app with a `FakeBrokerClient`.

**Files:**
- Create: `backend/tests/integration/test_acceptance_manual_order.py`
- Create: `backend/tests/integration/test_acceptance_alerts.py`

## Steps

- [ ] **Step 1: Manual order e2e**

```python
"""§11+ acceptance: submit → store → push → status flow for manual orders.

Mirrors the existing test_acceptance.py harness: spins up a real
FastAPI app with FakeBroker, hits /api/orders/* via httpx client, and
asserts state visible via /api/tasks + /api/orders + a WS subscription.
"""
from __future__ import annotations

import asyncio
import json

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_acceptance_manual_order_end_to_end(client: AsyncClient, fake_broker) -> None:
    # 1. Submit
    r = await client.post("/api/orders", json={
        "symbol": "AAPL.US", "side": "BUY", "qty": 200,
        "order_type": "LIMIT", "price": 199.0,
    })
    assert r.status_code == 201
    order_id = r.json()["order_id"]
    task_id = r.json()["task_id"]
    assert task_id.startswith("man_")

    # 2. Task row exists with source=manual
    r = await client.get(f"/api/tasks/{task_id}")
    assert r.status_code == 200
    assert r.json()["source"] == "manual"

    # 3. Replace price → broker.replace called + last_replaced_at set
    r = await client.patch(f"/api/orders/{order_id}", json={"price": 199.5})
    assert r.status_code == 204
    assert fake_broker.replaced[-1]["price"] == 199.5

    # 4. /api/orders lists the order
    r = await client.get(f"/api/orders?ticker=AAPL")
    assert r.status_code == 200
    order_ids = {o["order_id"] for o in r.json()["orders"]}
    assert order_id in order_ids

    # 5. Cancel
    r = await client.delete(f"/api/orders/{order_id}")
    assert r.status_code == 204
    assert fake_broker.cancelled[-1] == order_id


@pytest.mark.asyncio
async def test_acceptance_manual_order_503_under_noop(noop_client: AsyncClient) -> None:
    r = await noop_client.post("/api/orders", json={
        "symbol": "AAPL.US", "side": "BUY", "qty": 200,
        "order_type": "LIMIT", "price": 199.0,
    })
    assert r.status_code == 503
```

- [ ] **Step 2: Alerts e2e**

```python
"""§11+ acceptance: create alert → fire quote → triggered event observable
via WS + /api/alerts/events; one_shot disables after first hit.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_acceptance_alert_fires_and_disables(client: AsyncClient, fake_broker) -> None:
    # 1. Create
    r = await client.post("/api/alerts", json={
        "ticker": "AAPL", "symbol": "AAPL.US",
        "condition_type": "price", "operator": ">=", "threshold": 200.0,
        "repeat_mode": "one_shot",
    })
    assert r.status_code == 201
    alert_id = r.json()["id"]

    # 2. Broker is subscribed to AAPL.US
    assert "AAPL.US" in fake_broker.subscribed

    # 3. Fire a quote above threshold
    fake_broker.fire_quote("AAPL.US", {
        "last_done": 200.15, "open": 198.0, "prev_close": 198.5,
        "volume": 1_000_000, "timestamp": datetime.now(timezone.utc),
    })
    await asyncio.sleep(0.1)

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
async def test_acceptance_alert_recurring_throttled(client: AsyncClient, fake_broker) -> None:
    # 1. Create recurring with 60s cooldown
    r = await client.post("/api/alerts", json={
        "ticker": "AAPL", "symbol": "AAPL.US",
        "condition_type": "price", "operator": ">=", "threshold": 200.0,
        "repeat_mode": "recurring", "cooldown_seconds": 60,
    })
    assert r.status_code == 201

    # 2. Fire twice in rapid succession
    quote = {
        "last_done": 200.15, "open": 198.0, "prev_close": 198.5,
        "volume": 1_000_000, "timestamp": datetime.now(timezone.utc),
    }
    fake_broker.fire_quote("AAPL.US", quote)
    fake_broker.fire_quote("AAPL.US", quote)
    await asyncio.sleep(0.1)

    # 3. Only one event recorded
    r = await client.get("/api/alerts/events?ticker=AAPL")
    assert len(r.json()["events"]) == 1
```

- [ ] **Step 3: Fixture additions**

Ensure `backend/tests/integration/conftest.py` provides `fake_broker` whose mock `subscribe_quotes`, `set_on_quote`, `fire_quote` work the same as the engine unit-test FakeBroker, plus order methods returning sequential `ord-N` ids and tracking `submitted/replaced/cancelled` lists. Mirror the helper from `tests/alerts/test_engine.py` so the patterns match.

- [ ] **Step 4: Run all acceptance**

```bash
cd backend
uv run pytest tests/integration -v
```

Expected: existing 6 acceptance tests still pass + 4 new ones (`*_manual_order_end_to_end`, `*_503_under_noop`, `*_alert_fires_and_disables`, `*_alert_recurring_throttled`).

- [ ] **Step 5: Run the full backend + frontend test suites**

```bash
cd backend && uv run pytest -q
cd frontend && npm test -- --run
```

Both should be green.

- [ ] **Step 6: Run lint + typecheck**

```bash
cd backend && uv run mypy app && uv run ruff check . && uv run ruff format --check .
cd frontend && npm run typecheck
```

- [ ] **Step 7: Update README**

Append to the §7 REST API table in `README.md`:

```markdown
### 手动下单 + 告警

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | /api/orders | 手动下单 |
| PATCH | /api/orders/{id} | 改单 (LongPort replace_order) |
| DELETE | /api/orders/{id} | 撤单 |
| GET | /api/orders?ticker= | 当日订单（含 LongPort app 端下单） |
| GET | /api/alerts?ticker= | 列出告警 |
| POST | /api/alerts | 创建告警 |
| PATCH | /api/alerts/{id} | 修改 / 启用切换 |
| DELETE | /api/alerts/{id} | 删除 |
| GET | /api/alerts/events?ticker=&limit= | 触发历史 |

WS 事件新增：`order.changed`、`alert.triggered`、`alert.changed`
```

- [ ] **Step 8: Commit**

```bash
git add backend/tests/integration/test_acceptance_manual_order.py \
        backend/tests/integration/test_acceptance_alerts.py \
        backend/tests/integration/conftest.py README.md
git commit -m "$(cat <<'EOF'
test(acceptance): manual order + alerts e2e

Two §11+ acceptance suites covering the full request-to-WS pipeline.
README §7 REST table updated.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Done criteria

After Task 13, the following must hold:

- Submit / replace / cancel orders from the UI works end-to-end against LongPort paper account
- Alerts can be created in the detail page; the engine subscribes to LongPort quotes and fires
- Triggered alerts appear in the top-bar bell badge + toast; one-shot disables itself
- All 8 backend events (existing 6 + ORDER_CHANGED, ALERT_TRIGGERED, ALERT_CHANGED) flow through WS ring buffer and replay via `?since=`
- mypy strict + ruff + ts strict + vitest + pytest all green
- README §7 reflects new endpoints
