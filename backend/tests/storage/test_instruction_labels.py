from __future__ import annotations

from datetime import UTC, datetime

from app.domain.message import Message
from app.domain.status import Status
from app.domain.task import Task
from app.storage import repo
from app.storage.db import session_scope
from app.storage.schema import InstructionLabelRow


def test_instruction_labels_table_registered() -> None:
    assert InstructionLabelRow.__tablename__ == "instruction_labels"
    cols = set(InstructionLabelRow.__table__.columns.keys())
    assert cols == {"task_id", "verdict", "corrected_payload", "updated_at"}


def _make_task(task_id: str = "t-label-1") -> Task:
    now = datetime(2026, 5, 29, 12, 0, tzinfo=UTC)
    msg = Message(
        id=task_id, content="buy AAPL", raw_content="buy AAPL",
        author="trader", posted_at=now, received_at=now,
        source="stock", quoted=None,
    )
    return Task(
        id=task_id, type="stock", status=Status.PARSE_ERROR,
        message=msg, instruction=None, created_at=now, updated_at=now,
    )


async def test_set_and_load_label_correct(session_factory) -> None:
    async with session_scope(session_factory) as s:
        await repo.save_task(s, _make_task())
        await repo.set_label(s, "t-label-1", "correct", None)

    async with session_scope(session_factory) as s:
        task = await repo.load_task(s, "t-label-1")
    assert task is not None
    assert task.label is not None
    assert task.label.verdict == "correct"
    assert task.label.corrected_payload is None


async def test_set_label_corrected_then_overwrite(session_factory) -> None:
    payload = {"type": "stock", "action": "BUY", "ticker": "AAPL",
               "price": 188.0, "quantity": 50}
    async with session_scope(session_factory) as s:
        await repo.save_task(s, _make_task())
        await repo.set_label(s, "t-label-1", "corrected", payload)
        await repo.set_label(s, "t-label-1", "correct", None)  # overwrite

    async with session_scope(session_factory) as s:
        task = await repo.load_task(s, "t-label-1")
    assert task.label.verdict == "correct"
    assert task.label.corrected_payload is None


async def test_clear_label(session_factory) -> None:
    async with session_scope(session_factory) as s:
        await repo.save_task(s, _make_task())
        await repo.set_label(s, "t-label-1", "correct", None)
        await repo.clear_label(s, "t-label-1")

    async with session_scope(session_factory) as s:
        task = await repo.load_task(s, "t-label-1")
    assert task.label is None


async def test_list_tasks_populates_labels(session_factory) -> None:
    async with session_scope(session_factory) as s:
        await repo.save_task(s, _make_task("t-a"))
        await repo.save_task(s, _make_task("t-b"))
        await repo.set_label(s, "t-a", "correct", None)

    async with session_scope(session_factory) as s:
        tasks = await repo.list_tasks(s, limit=10)
    by_id = {t.id: t for t in tasks}
    assert by_id["t-a"].label is not None and by_id["t-a"].label.verdict == "correct"
    assert by_id["t-b"].label is None
