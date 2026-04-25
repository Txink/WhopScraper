"""End-to-end acceptance: spec §11 verification.

Covers:
  §11.1  Whop msg → SQLite full-cycle pipeline (MESSAGE_RECEIVED → parser → DB)
  §11.3  WebSocket broadcast + cursor replay (?since=)
  §11.4  Browser refresh recovers via GET /api/tasks
  §11.6  python -m app.main single command: app starts and exposes mode info
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

from fastapi.testclient import TestClient

from app.core.config import Settings, get_settings
from app.core.event_bus import Event
from app.core.events import MessagePayload, Topics
from app.domain.message import Message
from app.main import create_app
from tests.broker._fakes import FakeBrokerClient

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _settings_for_test(token: str = "acceptance-token") -> Settings:
    return Settings(
        app_token=token,
        database_url="sqlite+aiosqlite:///:memory:",
    )


def _stock_msg(id_: str, content: str = "TSLL 26.5 加一半") -> Message:
    return Message(
        id=id_,
        content=content,
        raw_content=content,
        author="big-elephant",
        posted_at=datetime(2026, 4, 25, 10, 42, tzinfo=UTC),
        received_at=datetime(2026, 4, 25, 10, 42, 1, tzinfo=UTC),
        source="stock",
    )


# ---------------------------------------------------------------------------
# §11.1  Whop msg → SQLite full-cycle pipeline
# ---------------------------------------------------------------------------


def test_acceptance_e2e_full_cycle() -> None:
    """Spec §11.1: MESSAGE_RECEIVED → parser service → task persisted to SQLite.

    Publishes a MESSAGE_RECEIVED event (simulating a Whop message arriving),
    waits for the full async pipeline to drain, then confirms the task is
    visible via GET /api/tasks — proving the full DB round-trip works.
    """
    settings = _settings_for_test()
    broker = FakeBrokerClient(dry_run=True)
    app = create_app(settings=settings, broker_override=broker, skip_whop=True)
    app.dependency_overrides[get_settings] = lambda: settings

    with TestClient(app) as client:
        state = app.state.app_state
        msg = _stock_msg("acc-001")

        async def _flow() -> None:
            await state.bus.publish(Event(Topics.MESSAGE_RECEIVED, MessagePayload(message=msg)))
            # Parser service → TASK_CREATED → storage (chain of async tasks)
            # Two wait_idle passes drain the two-hop chain.
            await state.bus.wait_idle(timeout=2)
            await state.bus.wait_idle(timeout=2)

        assert client.portal is not None
        client.portal.call(_flow)

        r = client.get("/api/tasks", params={"token": "acceptance-token"})
        assert r.status_code == 200
        data = r.json()
        assert any(t["id"] == "acc-001" for t in data["tasks"]), (
            f"task not found in DB; response={data}"
        )


# ---------------------------------------------------------------------------
# §11.3  WebSocket broadcast + cursor replay
# ---------------------------------------------------------------------------


def test_acceptance_websocket_broadcast_and_replay() -> None:
    """Spec §11.3: WS receives broadcast; reconnect with ?since= replays missed events."""
    from app.domain.task import Task

    settings = _settings_for_test()
    broker = FakeBrokerClient(dry_run=True)
    app = create_app(settings=settings, broker_override=broker, skip_whop=True)
    app.dependency_overrides[get_settings] = lambda: settings

    from app.core.events import TaskPayload

    def _make_task_payload(idx: int) -> TaskPayload:
        msg = _stock_msg(f"ws-{idx}")
        t = Task.new_from_message(msg)
        t.mark_parsing()
        return TaskPayload(task=t)

    with TestClient(app) as client:
        state = app.state.app_state

        # ── Connect first WS client, publish 3 events, collect them ─────────
        with client.websocket_connect("/ws?token=acceptance-token") as ws:

            async def _publish_three() -> None:
                for i in range(3):
                    await state.bus.publish(Event(Topics.TASK_CREATED, _make_task_payload(i)))
                await state.bus.wait_idle(timeout=2)

            assert client.portal is not None
            client.portal.call(_publish_three)

            received = [json.loads(ws.receive_text()) for _ in range(3)]

        event_ids = [m["event_id"] for m in received]
        # event_ids must be strictly monotonically increasing
        assert event_ids == sorted(event_ids), f"event_ids not monotonic: {event_ids}"
        assert len(set(event_ids)) == 3, f"duplicate event_ids: {event_ids}"

        # ── Reconnect with ?since=first_event_id → replay events 1 and 2 ────
        since = event_ids[0]
        with client.websocket_connect(f"/ws?token=acceptance-token&since={since}") as ws2:
            replayed = [json.loads(ws2.receive_text()) for _ in range(2)]

        assert [m["event_id"] for m in replayed] == event_ids[1:], (
            f"replayed event_ids mismatch; expected {event_ids[1:]}, "
            f"got {[m['event_id'] for m in replayed]}"
        )


# ---------------------------------------------------------------------------
# §11.6  Single-command startup exposes mode info
# ---------------------------------------------------------------------------


def test_acceptance_health_endpoint_exposes_mode() -> None:
    """Spec §11.6: app starts and /api/health reports broker mode and dry_run."""
    settings = _settings_for_test()
    broker = FakeBrokerClient(is_paper=True, dry_run=True)
    app = create_app(settings=settings, broker_override=broker, skip_whop=True)
    app.dependency_overrides[get_settings] = lambda: settings

    with TestClient(app) as client:
        r = client.get("/api/health", params={"token": "acceptance-token"})
        assert r.status_code == 200
        h = r.json()
        assert h["mode"] == "paper"
        assert h["dry_run"] is True


# ---------------------------------------------------------------------------
# §11.4  Browser refresh recovers via /api/tasks
# ---------------------------------------------------------------------------


def test_acceptance_browser_refresh_recovers_via_initial_list() -> None:
    """Spec §11.4: after publishing tasks, a fresh GET /api/tasks restores full state.

    Simulates a browser refresh: the frontend re-fetches /api/tasks and
    renders all prior tasks without needing WebSocket history.
    """
    settings = _settings_for_test()
    broker = FakeBrokerClient(dry_run=True)
    app = create_app(settings=settings, broker_override=broker, skip_whop=True)
    app.dependency_overrides[get_settings] = lambda: settings

    with TestClient(app) as client:
        state = app.state.app_state

        async def _publish_five() -> None:
            for i in range(5):
                msg = _stock_msg(f"refresh-{i}")
                await state.bus.publish(Event(Topics.MESSAGE_RECEIVED, MessagePayload(message=msg)))
            # Double wait_idle to drain the two-hop pipeline
            await state.bus.wait_idle(timeout=2)
            await state.bus.wait_idle(timeout=2)

        assert client.portal is not None
        client.portal.call(_publish_five)

        # "Browser refresh" — fetch /api/tasks
        r = client.get("/api/tasks", params={"token": "acceptance-token", "limit": "100"})
        assert r.status_code == 200
        ids = {t["id"] for t in r.json()["tasks"]}
        missing = [f"refresh-{i}" for i in range(5) if f"refresh-{i}" not in ids]
        assert not missing, f"tasks missing after refresh: {missing}; got {ids}"


# ---------------------------------------------------------------------------
# Per-page settings → trader behavior chain (Task O)
# ---------------------------------------------------------------------------


def test_acceptance_per_page_settings_drive_trader(monkeypatch) -> None:
    """End-to-end: add page → PATCH settings → publish message → trader uses
    new tickers + tolerance.

    Verifies the full per-page settings chain:
      add_page → update_settings → MESSAGE_RECEIVED →
        ParserService picks up watched tickers from page settings →
        Trader picks up trade_quantity + tolerance from page settings →
        order submitted with computed qty (700 * 0.5 = 350) + MARKET order_type.
    """

    # Patch the registry's listener-launcher so add_page doesn't try to spawn
    # real Playwright. The listener instance is irrelevant — the test only needs
    # the entry to be present in the url-index.
    async def _noop_start(self, entry, *, skip_initial=True):  # noqa: ANN001
        self._listeners[entry.id] = None

    from app.whop.registry import WhopRegistry

    monkeypatch.setattr(WhopRegistry, "_start_listener", _noop_start)

    settings = _settings_for_test()
    fake_broker = FakeBrokerClient()
    # auto_trade defaults true via Settings(); FakeBrokerClient.is_paper=True.
    app = create_app(settings=settings, broker_override=fake_broker, skip_whop=True)
    app.dependency_overrides[get_settings] = lambda: settings

    with TestClient(app) as client:
        state = app.state.app_state
        registry = state.whop_registry

        async def _flow() -> None:
            # 1. Add stock page + configure tickers via update_settings
            entry = await registry.add_page(
                url="https://whop.com/acc/app/",
                source="stock",
                name="acc",
            )
            await registry.update_settings(
                entry.id,
                {
                    "tickers": {"TSLL": {"trade_quantity": 700}},
                    "price_deviation_tolerance": 0.5,
                },
            )

            # 2. Inject a stock signal that resolves to 半仓 of TSLL
            msg = Message(
                id="acc-1",
                content="tsll 在16.02附近开个底仓 常规仓的一半",
                raw_content="tsll 在16.02附近开个底仓 常规仓的一半",
                author=None,
                posted_at=datetime.now(UTC),
                received_at=datetime.now(UTC),
                source="stock",
                url="https://whop.com/acc/app/",
            )
            await state.bus.publish(Event(Topics.MESSAGE_RECEIVED, MessagePayload(message=msg)))
            # Drain parser → trader chain (two hops).
            await state.bus.wait_idle(timeout=2)
            await state.bus.wait_idle(timeout=2)

        assert client.portal is not None
        client.portal.call(_flow)

        # Trader should have submitted exactly one stock order with computed qty.
        stock_orders = [o for o in fake_broker.submitted_orders if o["kind"] == "stock"]
        assert len(stock_orders) == 1, (
            f"expected 1 stock order, got {len(stock_orders)}: {fake_broker.submitted_orders}"
        )
        order = stock_orders[0]
        assert order["symbol"] == "TSLL.US"
        # 700 (trade_quantity) * 0.5 (常规仓的一半) = 350
        assert order["quantity"] == 350
        # First-pass policy: market_price = signal_price → deviation = 0 → MARKET
        assert order["order_type"] == "MARKET"


def test_acceptance_unknown_ticker_skipped(monkeypatch) -> None:
    """End-to-end: ticker not in page whitelist → SKIPPED, no broker call.

    Page is added with default settings (tickers={} = explicit empty whitelist).
    Trader sees ticker missing from whitelist and skips without submitting.
    """

    async def _noop_start(self, entry, *, skip_initial=True):  # noqa: ANN001
        self._listeners[entry.id] = None

    from app.whop.registry import WhopRegistry

    monkeypatch.setattr(WhopRegistry, "_start_listener", _noop_start)

    settings = _settings_for_test()
    fake_broker = FakeBrokerClient()
    app = create_app(settings=settings, broker_override=fake_broker, skip_whop=True)
    app.dependency_overrides[get_settings] = lambda: settings

    with TestClient(app) as client:
        state = app.state.app_state
        registry = state.whop_registry

        async def _flow() -> None:
            await registry.add_page(
                url="https://whop.com/skip/app/",
                source="stock",
                name="skip",
            )
            # Default stock settings ship with tickers={} → explicit empty whitelist.

            msg = Message(
                id="skip-1",
                content="tsll 在16.02附近开个底仓",
                raw_content="tsll 在16.02附近开个底仓",
                author=None,
                posted_at=datetime.now(UTC),
                received_at=datetime.now(UTC),
                source="stock",
                url="https://whop.com/skip/app/",
            )
            await state.bus.publish(Event(Topics.MESSAGE_RECEIVED, MessagePayload(message=msg)))
            await state.bus.wait_idle(timeout=2)
            await state.bus.wait_idle(timeout=2)

        assert client.portal is not None
        client.portal.call(_flow)

        # No stock order submitted (whitelist empty → ticker SKIPPED).
        stock_orders = [o for o in fake_broker.submitted_orders if o["kind"] == "stock"]
        assert len(stock_orders) == 0, (
            f"expected 0 stock orders, got {fake_broker.submitted_orders}"
        )
