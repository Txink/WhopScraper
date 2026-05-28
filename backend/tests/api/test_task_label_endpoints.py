"""Tests for PUT/DELETE /api/tasks/{id}/label endpoints (Plan Task 4).

Behaviors tested:
1. PUT with {"verdict": "correct"} → 200, label.verdict == "correct", corrected_payload is None
2. PUT with {"verdict": "corrected", "corrected_payload": {...}} → 200, payload fields correct
3. PUT with {"verdict": "corrected"} (no payload) → 400
4. PUT unknown task → 404
5. After setting label, DELETE → 200, label is None
6. After setting label, GET /api/tasks list → t1 entry has label.verdict == "correct"
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
import pytest_asyncio
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.http import build_http_router
from app.broker.runtime_settings import LongPortRuntimeStore
from app.core.config import Settings, get_settings
from app.core.event_bus import EventBus
from app.domain.message import Message
from app.domain.status import Status
from app.domain.task import Task
from app.storage import repo
from app.storage.listeners import register_storage_listeners
from tests.broker._fakes import FakeBrokerClient

_TOKEN = "test-token-label-XYZ"


# ---------------------------------------------------------------------------
# Helpers (mirrored from test_http.py)
# ---------------------------------------------------------------------------


def _now(offset_secs: int = 0) -> datetime:
    base = datetime.combine(date.today(), datetime.min.time(), tzinfo=UTC)
    return base + timedelta(hours=10, seconds=offset_secs)


def _msg(id_: str, *, offset_secs: int = 0) -> Message:
    ts = _now(offset_secs)
    return Message(
        id=id_,
        content="TSLL 26.5 buy",
        raw_content="TSLL 26.5 buy",
        author="trader",
        source="stock",  # type: ignore[arg-type]
        posted_at=ts,
        received_at=ts,
    )


def _task(id_: str, status: Status = Status.PARSE_ERROR, *, offset_secs: int = 0) -> Task:
    ts = _now(offset_secs)
    return Task(
        id=id_,
        type="stock",
        status=status,
        message=_msg(id_, offset_secs=offset_secs),
        order_id=None,
        created_at=ts,
        updated_at=ts,
    )


# ---------------------------------------------------------------------------
# App fixture (mirrored from test_http.py)
# ---------------------------------------------------------------------------


@pytest.fixture
def make_app(
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> tuple[FastAPI, FakeBrokerClient]:
    broker: FakeBrokerClient = FakeBrokerClient()
    settings = Settings(app_token=_TOKEN)
    bus = EventBus()
    runtime_store = LongPortRuntimeStore(settings_file=tmp_path / "longport_settings.json")

    app = FastAPI()
    app.include_router(
        build_http_router(
            session_factory=session_factory,
            broker=broker,
            settings=settings,
            bus=bus,
            longport_runtime=runtime_store,
        )
    )
    app.dependency_overrides[get_settings] = lambda: settings
    register_storage_listeners(bus, session_factory)
    return app, broker


@pytest.fixture
def client_and_broker(
    make_app: tuple[FastAPI, FakeBrokerClient],
) -> tuple[TestClient, FakeBrokerClient]:
    app, broker = make_app
    return TestClient(app, raise_server_exceptions=True), broker


# ---------------------------------------------------------------------------
# Fixture: one task t1 persisted in DB
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def task_t1(session_factory: async_sessionmaker[AsyncSession]) -> Task:
    task = _task("t1", Status.PARSE_ERROR, offset_secs=0)
    async with session_factory() as session:
        await repo.save_task(session, task)
    return task


# ---------------------------------------------------------------------------
# 1. PUT /api/tasks/t1/label with {"verdict": "correct"} → 200
# ---------------------------------------------------------------------------


def test_set_label_correct(
    client_and_broker: tuple[TestClient, FakeBrokerClient],
    task_t1: Task,
) -> None:
    client, _ = client_and_broker
    resp = client.put(
        "/api/tasks/t1/label",
        params={"token": _TOKEN},
        json={"verdict": "correct"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["label"]["verdict"] == "correct"
    assert body["label"]["corrected_payload"] is None


# ---------------------------------------------------------------------------
# 2. PUT with "corrected" + full corrected_payload → 200, payload fields
# ---------------------------------------------------------------------------


def test_set_label_corrected_with_payload(
    client_and_broker: tuple[TestClient, FakeBrokerClient],
    task_t1: Task,
) -> None:
    client, _ = client_and_broker
    resp = client.put(
        "/api/tasks/t1/label",
        params={"token": _TOKEN},
        json={
            "verdict": "corrected",
            "corrected_payload": {
                "type": "stock",
                "action": "BUY",
                "ticker": "AAPL",
                "price": 188.0,
                "quantity": 50,
            },
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["label"]["verdict"] == "corrected"
    payload = body["label"]["corrected_payload"]
    assert payload["ticker"] == "AAPL"
    assert payload["action"] == "BUY"
    assert payload["quantity"] == 50


# ---------------------------------------------------------------------------
# 3. PUT with "corrected" but no corrected_payload → 400
# ---------------------------------------------------------------------------


def test_set_label_corrected_without_payload_returns_400(
    client_and_broker: tuple[TestClient, FakeBrokerClient],
    task_t1: Task,
) -> None:
    client, _ = client_and_broker
    resp = client.put(
        "/api/tasks/t1/label",
        params={"token": _TOKEN},
        json={"verdict": "corrected"},
    )
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# 4. PUT unknown task → 404
# ---------------------------------------------------------------------------


def test_set_label_unknown_task_returns_404(
    client_and_broker: tuple[TestClient, FakeBrokerClient],
) -> None:
    client, _ = client_and_broker
    resp = client.put(
        "/api/tasks/nope/label",
        params={"token": _TOKEN},
        json={"verdict": "correct"},
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# 5. DELETE after setting label → 200, label is None
# ---------------------------------------------------------------------------


def test_clear_label_returns_null_label(
    client_and_broker: tuple[TestClient, FakeBrokerClient],
    task_t1: Task,
) -> None:
    client, _ = client_and_broker
    # First set a label
    set_resp = client.put(
        "/api/tasks/t1/label",
        params={"token": _TOKEN},
        json={"verdict": "correct"},
    )
    assert set_resp.status_code == 200
    assert set_resp.json()["label"]["verdict"] == "correct"

    # Now clear it
    del_resp = client.delete(
        "/api/tasks/t1/label",
        params={"token": _TOKEN},
    )
    assert del_resp.status_code == 200
    assert del_resp.json()["label"] is None


# ---------------------------------------------------------------------------
# 6. After setting label, GET /api/tasks → t1 has label.verdict == "correct"
# ---------------------------------------------------------------------------


def test_list_tasks_includes_label(
    client_and_broker: tuple[TestClient, FakeBrokerClient],
    task_t1: Task,
) -> None:
    client, _ = client_and_broker
    # Set label
    set_resp = client.put(
        "/api/tasks/t1/label",
        params={"token": _TOKEN},
        json={"verdict": "correct"},
    )
    assert set_resp.status_code == 200

    # List tasks
    list_resp = client.get("/api/tasks", params={"token": _TOKEN})
    assert list_resp.status_code == 200
    tasks = list_resp.json()["tasks"]
    t1 = next((t for t in tasks if t["id"] == "t1"), None)
    assert t1 is not None
    assert t1["label"]["verdict"] == "correct"
