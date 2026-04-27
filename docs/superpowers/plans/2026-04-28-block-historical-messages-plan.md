# Block Historical Messages — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the per-page `block_non_today_messages` toggle with a tighter `block_historical_messages` toggle that SKIPs ordering when `message.posted_at < listener.started_at`. Applies to both stock and option pages.

**Architecture:** The listener computes a per-message `is_historical` boolean at capture time (frozen against later listener restarts) and passes it via `MessagePayload`. The parser/service handler propagates the flag onto a new `Task.is_historical` column. The trader checks `setting AND task.is_historical → SKIPPED` at the same gate position the old non-today check occupied. The old field/gate/UI section is deleted entirely — no backward-compat fallback.

**Tech Stack:** Python 3.11 + FastAPI + SQLAlchemy 2 + Alembic + pytest + Playwright; React + TypeScript + Vitest.

**Spec:** `docs/superpowers/specs/2026-04-28-block-historical-messages-design.md`

---

## File Map

**Backend — modify:**

- `backend/app/core/events.py` — `MessagePayload` adds `is_historical: bool = False`
- `backend/app/domain/task.py` — `Task` adds `is_historical: bool = False`; `new_from_message` accepts the flag
- `backend/app/storage/schema.py` — `TaskRow` adds `is_historical` column
- `backend/app/storage/repo.py` — `_task_to_row` / `_rows_to_task` / `save_task` round-trip the column; `_TASK_UPDATE_COLS` extended
- `backend/app/whop/listener.py` — `_scan_once` computes `is_historical` per message
- `backend/app/parser/service.py` — `_handle_message_received` passes `payload.is_historical` into `Task.new_from_message`
- `backend/app/whop/page_settings.py` — delete `block_non_today_messages`, add `block_historical_messages`
- `backend/app/api/schemas.py` — same field swap on `WhopPageSettingsOut` / `WhopPageSettingsPatch`
- `backend/app/api/http.py` — same field swap on read + patch handlers
- `backend/app/broker/trader.py:223` — replace gate ① b body

**Backend — create:**

- `backend/alembic/versions/<auto-rev>_add_tasks_is_historical.py` — adds `tasks.is_historical` column

**Backend — tests modify:**

- `backend/tests/whop/test_page_settings.py`
- `backend/tests/whop/test_listener.py`
- `backend/tests/parser/test_service.py`
- `backend/tests/storage/test_repo.py` and `test_schema.py` and `test_migrations.py`
- `backend/tests/api/test_whop_settings.py`
- `backend/tests/broker/test_trader.py`
- `backend/tests/broker/test_trader_lot_lookup.py`
- `backend/tests/broker/test_trader_deviation.py`

**Frontend — modify:**

- `frontend/src/components/Dashboard/PageSettingsModal.tsx`
- `frontend/src/components/Dashboard/PageSettingsModal.test.tsx`
- `frontend/src/stores/pageTabs.test.ts` — fixture key swap only
- `frontend/src/components/Dashboard/PageInfoBar.test.tsx` — fixture key swap only
- `frontend/src/components/Dashboard/PageTabs.test.tsx` — fixture key swap only
- `frontend/src/components/Dashboard/PageActionBar.test.tsx` — fixture key swap only
- `frontend/src/api/domain-types.ts` — auto-regenerated from openapi (no hand-edit)

**Docs:**

- `CHANGELOG.md` — `Unreleased` section gets `Removed` + `Changed` entries

---

## Pre-flight

- [ ] **P1: Confirm working tree is clean except for the spec docs already committed**

```bash
git status
```

Expected: `frontend/src/components/Card/Card.css` and `frontend/src/components/Card/OrderSubmit.tsx` may show as modified (pre-existing branch state); the new spec files are committed. Do NOT touch the Card files in this plan.

- [ ] **P2: Run baseline backend tests so failures introduced by us are isolated**

```bash
cd backend && .venv/bin/pytest -q 2>&1 | tail -20
```

Expected: pass count; treat any pre-existing failures as out-of-scope (note them and move on).

- [ ] **P3: Run baseline frontend tests**

```bash
cd frontend && npm test -- --run 2>&1 | tail -20
```

Expected: pass count; same caveat as P2.

---

## Task 1: `MessagePayload.is_historical`

**Files:**
- Modify: `backend/app/core/events.py`
- Test: `backend/tests/core/` (file may not exist; if missing, add inline assertion in `backend/tests/whop/test_listener.py` in Task 5 instead and skip steps 1–4 here, jumping straight to step 5)

- [ ] **Step 1: Write a failing import-time test for the new field**

Create or extend `backend/tests/core/test_events.py`:

```python
"""MessagePayload should carry an is_historical flag (default False)."""

from datetime import UTC, datetime

from app.core.events import MessagePayload
from app.domain.message import Message


def _msg() -> Message:
    return Message(
        id="m1",
        content="x",
        raw_content="x",
        author=None,
        posted_at=datetime.now(UTC),
        received_at=datetime.now(UTC),
        source="stock",
        url=None,
        quoted=None,
        history_hint=[],
    )


def test_message_payload_default_is_historical_false():
    p = MessagePayload(message=_msg())
    assert p.is_historical is False


def test_message_payload_accepts_is_historical_true():
    p = MessagePayload(message=_msg(), is_historical=True)
    assert p.is_historical is True
```

- [ ] **Step 2: Run it and confirm it fails**

```bash
cd backend && .venv/bin/pytest tests/core/test_events.py -v
```

Expected: `TypeError: ... unexpected keyword argument 'is_historical'` or `AttributeError`.

- [ ] **Step 3: Add the field to `MessagePayload`**

Edit `backend/app/core/events.py`. Replace:

```python
@dataclass(frozen=True)
class MessagePayload:
    """Payload for ``message.received`` events."""

    message: Message
```

With:

```python
@dataclass(frozen=True)
class MessagePayload:
    """Payload for ``message.received`` events.

    ``is_historical`` is set by the listener when ``message.posted_at <
    listener.started_at`` (i.e., the message existed in the channel
    before this listener session began). The trader uses it together
    with the per-page ``block_historical_messages`` setting to decide
    whether to SKIP ordering.
    """

    message: Message
    is_historical: bool = False
```

- [ ] **Step 4: Run the test, confirm it passes**

```bash
cd backend && .venv/bin/pytest tests/core/test_events.py -v
```

Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/core/events.py backend/tests/core/test_events.py
git commit -m "feat(events): MessagePayload carries is_historical flag"
```

---

## Task 2: `Task.is_historical`

**Files:**
- Modify: `backend/app/domain/task.py:27-51`
- Test: `backend/tests/domain/test_task.py` (if absent, create it)

- [ ] **Step 1: Write a failing test**

Create `backend/tests/domain/test_task.py` (or extend it if present):

```python
"""Task carries an is_historical flag, settable at construction."""

from datetime import UTC, datetime

from app.domain.message import Message
from app.domain.task import Task


def _msg() -> Message:
    return Message(
        id="m1",
        content="x",
        raw_content="x",
        author=None,
        posted_at=datetime.now(UTC),
        received_at=datetime.now(UTC),
        source="stock",
        url=None,
        quoted=None,
        history_hint=[],
    )


def test_task_default_is_historical_false():
    t = Task.new_from_message(_msg())
    assert t.is_historical is False


def test_task_new_from_message_accepts_is_historical_true():
    t = Task.new_from_message(_msg(), is_historical=True)
    assert t.is_historical is True
```

- [ ] **Step 2: Run it and confirm it fails**

```bash
cd backend && .venv/bin/pytest tests/domain/test_task.py -v
```

Expected: `TypeError: new_from_message() got an unexpected keyword argument 'is_historical'`.

- [ ] **Step 3: Add the field + extend `new_from_message`**

Edit `backend/app/domain/task.py`. In the `Task` dataclass body, after `reject_reason: str | None = None`, add:

```python
    is_historical: bool = False
```

Replace the `new_from_message` classmethod with:

```python
    @classmethod
    def new_from_message(cls, msg: Message, *, is_historical: bool = False) -> Task:
        now = datetime.now(UTC)
        return cls(
            id=msg.id,
            type="unknown",
            status=Status.RECEIVED,
            message=msg,
            created_at=now,
            updated_at=now,
            is_historical=is_historical,
        )
```

- [ ] **Step 4: Run the test, confirm it passes**

```bash
cd backend && .venv/bin/pytest tests/domain/test_task.py -v
```

Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/domain/task.py backend/tests/domain/test_task.py
git commit -m "feat(domain): Task carries is_historical flag"
```

---

## Task 3: `TaskRow.is_historical` column + repo round-trip

**Files:**
- Modify: `backend/app/storage/schema.py:33-61`
- Modify: `backend/app/storage/repo.py:134-164` (`_task_to_row`), `:236-263` (`_rows_to_task`), `:278-290` (`_TASK_UPDATE_COLS`), `:329-358` (`save_task`)
- Test: `backend/tests/storage/test_repo.py`

- [ ] **Step 1: Write a failing round-trip test**

Append to `backend/tests/storage/test_repo.py`:

```python
import pytest

from app.domain.task import Task
from app.storage.repo import save_task


@pytest.mark.asyncio
async def test_save_task_round_trips_is_historical(session_factory):
    """is_historical persists through save_task → reload."""
    from app.storage.db import session_scope
    from app.storage.repo import load_task

    msg = _make_message_fixture(id="hist-1")  # use whatever fixture pattern this test file already has
    task = Task.new_from_message(msg, is_historical=True)

    async with session_scope(session_factory) as session:
        await save_task(session, task)
        await session.commit()

    async with session_scope(session_factory) as session:
        loaded = await load_task(session, "hist-1")

    assert loaded is not None
    assert loaded.is_historical is True


@pytest.mark.asyncio
async def test_save_task_default_is_historical_false(session_factory):
    from app.storage.db import session_scope
    from app.storage.repo import load_task

    msg = _make_message_fixture(id="live-1")
    task = Task.new_from_message(msg)  # default False

    async with session_scope(session_factory) as session:
        await save_task(session, task)
        await session.commit()

    async with session_scope(session_factory) as session:
        loaded = await load_task(session, "live-1")

    assert loaded is not None
    assert loaded.is_historical is False
```

> Open `backend/tests/storage/test_repo.py` first to find the existing `_make_message_fixture` (or equivalent) helper and `session_factory` fixture name; replace `_make_message_fixture` and `session_factory` above with the actual symbols if they differ. If `load_task` lives under a different name (e.g. `get_task`), update accordingly.

- [ ] **Step 2: Run it and confirm it fails**

```bash
cd backend && .venv/bin/pytest tests/storage/test_repo.py::test_save_task_round_trips_is_historical -v
```

Expected: failure citing missing column on `TaskRow` or attribute error on `Task`.

- [ ] **Step 3: Add the column to `TaskRow`**

Edit `backend/app/storage/schema.py`. Inside `class TaskRow(Base):`, after the `updated_at` column, add:

```python
    is_historical: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=sa.text("0")
    )
```

If `Boolean` is not yet imported at the top of the file, add it to the SQLAlchemy import line. If `sa` is not aliased, replace `sa.text("0")` with `text("0")` and add `from sqlalchemy import text` (or whichever alias the file uses — match local convention).

- [ ] **Step 4: Wire `_task_to_row`**

Edit `backend/app/storage/repo.py`. In `_task_to_row` (line 134), at the bottom of the `return TaskRow(...)` call, add a comma after `updated_at=task.updated_at,` and append:

```python
        is_historical=task.is_historical,
```

- [ ] **Step 5: Wire `save_task` UPSERT**

In `backend/app/storage/repo.py`, locate `task_values = { ... }` (line 329-343) and add inside the dict:

```python
        "is_historical": task.is_historical,
```

In `_TASK_UPDATE_COLS` (line 278-290), add a new entry:

```python
    "is_historical",
```

(Place it between `"reject_reason"` and `"stage_timings_json"` — alphabetic order isn't enforced, just keep the tuple readable.)

- [ ] **Step 6: Wire `_rows_to_task`**

In `backend/app/storage/repo.py`, locate `_rows_to_task` (line 236). In the `Task(...)` constructor at the end, after `reject_reason=task_row.reject_reason,` add:

```python
        is_historical=task_row.is_historical,
```

- [ ] **Step 7: Re-run the round-trip tests, confirm they pass**

```bash
cd backend && .venv/bin/pytest tests/storage/test_repo.py -v -k is_historical
```

Expected: 2 passed.

- [ ] **Step 8: Run the full storage suite to catch any regression in existing tests**

```bash
cd backend && .venv/bin/pytest tests/storage/ -q
```

Expected: all pass. (If `test_schema.py` enumerates TaskRow columns explicitly, update it to include `is_historical` so it stops failing.)

- [ ] **Step 9: Commit**

```bash
git add backend/app/storage/schema.py backend/app/storage/repo.py backend/tests/storage/
git commit -m "feat(storage): persist Task.is_historical column"
```

---

## Task 4: Alembic migration

**Files:**
- Create: `backend/alembic/versions/<auto-revid>_add_tasks_is_historical.py`
- Test: `backend/tests/storage/test_migrations.py` (if it exists, ensure it loads cleanly; otherwise nothing to add)

- [ ] **Step 1: Generate a new revision**

```bash
cd backend && .venv/bin/alembic revision -m "add tasks.is_historical"
```

Expected: prints something like `Generating /Users/.../backend/alembic/versions/<rev>_add_tasks_is_historical.py ... done`.

- [ ] **Step 2: Edit the generated file**

Open the new file under `backend/alembic/versions/`. Replace the `upgrade()` and `downgrade()` bodies:

```python
def upgrade() -> None:
    with op.batch_alter_table("tasks") as b:
        b.add_column(
            sa.Column(
                "is_historical",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("0"),
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("tasks") as b:
        b.drop_column("is_historical")
```

Verify the auto-generated `down_revision` points to `947fff1b2fcd` (the messages.url migration). If it doesn't, set it explicitly.

- [ ] **Step 3: Apply the migration to a fresh DB and confirm it runs**

```bash
cd backend && .venv/bin/alembic upgrade head
```

Expected: prints `Running upgrade 947fff1b2fcd -> <newrev>, add tasks.is_historical`.

- [ ] **Step 4: Reverse and re-apply to confirm idempotence**

```bash
cd backend && .venv/bin/alembic downgrade -1 && .venv/bin/alembic upgrade head
```

Expected: both succeed; column drop and re-add work cleanly.

- [ ] **Step 5: Run the storage migrations test, if present**

```bash
cd backend && .venv/bin/pytest tests/storage/test_migrations.py -v
```

Expected: pass. If the test enumerates known revisions, update it.

- [ ] **Step 6: Commit**

```bash
git add backend/alembic/versions/
git commit -m "feat(alembic): add tasks.is_historical column"
```

---

## Task 5: `WhopListener._scan_once` computes `is_historical`

**Files:**
- Modify: `backend/app/whop/listener.py:235-262`
- Test: `backend/tests/whop/test_listener.py`

- [ ] **Step 1: Write a failing test**

Append to `backend/tests/whop/test_listener.py`. Use the existing `_FakeBrowser` and HTML helpers (look at the top of the file). The test should drive the listener with messages whose `posted_at` straddles the listener's `started_at` and assert `is_historical` on the published payload.

```python
import dataclasses
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from app.core.event_bus import Event, EventBus
from app.core.events import MessagePayload, Topics
from app.domain.message import Message
from app.whop.listener import WhopListener


def _make_msg(mid: str, posted_at: datetime) -> Message:
    return Message(
        id=mid,
        content=f"hello {mid}",
        raw_content=f"hello {mid}",
        author=None,
        posted_at=posted_at,
        received_at=datetime.now(UTC),
        source="stock",
        url=None,
        quoted=None,
        history_hint=[],
    )


@pytest.mark.asyncio
async def test_scan_once_marks_messages_as_historical_when_posted_before_started_at(monkeypatch):
    """Messages whose posted_at < listener.started_at must be tagged is_historical=True."""
    started_at = datetime(2026, 4, 28, 12, 0, 0, tzinfo=UTC)
    old_msg = _make_msg("old-1", started_at - timedelta(hours=1))
    new_msg = _make_msg("new-1", started_at + timedelta(seconds=30))

    captured: list[MessagePayload] = []

    async def _capture(event: Event) -> None:
        captured.append(event.payload)

    bus = EventBus()
    bus.subscribe(Topics.MESSAGE_RECEIVED, _capture)

    listener = WhopListener(
        bus=bus,
        url="https://whop.example/c/test",
        source="stock",
        poll_interval=10.0,
        skip_initial=False,
        dedupe_processed_messages=False,
    )
    listener._browser = _FakeBrowser(["<html></html>"])
    listener._started_at = started_at

    # Patch extract_messages to return our two fixed messages
    monkeypatch.setattr(
        "app.whop.listener.extract_messages",
        lambda html, source, received_at=None: [old_msg, new_msg],
    )

    await listener._scan_once()

    assert len(captured) == 2
    by_id = {p.message.id: p for p in captured}
    assert by_id["old-1"].is_historical is True
    assert by_id["new-1"].is_historical is False


@pytest.mark.asyncio
async def test_scan_once_treats_missing_posted_at_as_not_historical(monkeypatch):
    started_at = datetime(2026, 4, 28, 12, 0, 0, tzinfo=UTC)
    msg = _make_msg("nopost-1", datetime.now(UTC))
    msg = dataclasses.replace(msg, posted_at=None)  # type: ignore[arg-type]

    captured: list[MessagePayload] = []
    bus = EventBus()
    bus.subscribe(Topics.MESSAGE_RECEIVED, lambda e: captured.append(e.payload))

    listener = WhopListener(
        bus=bus, url="x", source="stock", poll_interval=10.0,
        skip_initial=False, dedupe_processed_messages=False,
    )
    listener._browser = _FakeBrowser(["<html></html>"])
    listener._started_at = started_at

    monkeypatch.setattr(
        "app.whop.listener.extract_messages",
        lambda html, source, received_at=None: [msg],
    )

    await listener._scan_once()
    assert captured[0].is_historical is False
```

> If `Message.posted_at` is annotated as non-nullable and `dataclasses.replace` rejects `None`, drop the second test — or instead test only the strict-less-than boundary (posted_at == started_at → False).

- [ ] **Step 2: Run the test, confirm it fails**

```bash
cd backend && .venv/bin/pytest tests/whop/test_listener.py -v -k is_historical
```

Expected: `is_historical` attribute on payload is `False` for both messages (current behavior — payload doesn't compute it yet) → first test fails.

- [ ] **Step 3: Patch `_scan_once`**

Edit `backend/app/whop/listener.py:235-262`. Replace the `for msg in messages:` loop body with:

```python
        for msg in messages:
            if msg.id in self._seen:
                continue
            self._seen.add(msg.id)
            tagged = dataclasses.replace(msg, url=self._url)
            is_historical = (
                tagged.posted_at is not None
                and self._started_at is not None
                and tagged.posted_at.astimezone(UTC) < self._started_at
            )
            await self._bus.publish(
                Event(
                    Topics.MESSAGE_RECEIVED,
                    MessagePayload(message=tagged, is_historical=is_historical),
                )
            )
            new_count += 1
```

`UTC` and `datetime` are already imported at the top of the file (line 15).

- [ ] **Step 4: Run the tests, confirm they pass**

```bash
cd backend && .venv/bin/pytest tests/whop/test_listener.py -v
```

Expected: all pass (the new ones plus the pre-existing dedupe/publish suite).

- [ ] **Step 5: Commit**

```bash
git add backend/app/whop/listener.py backend/tests/whop/test_listener.py
git commit -m "feat(listener): tag messages with is_historical in _scan_once"
```

---

## Task 6: Parser/service propagates `is_historical` onto `Task`

**Files:**
- Modify: `backend/app/parser/service.py:66-130` (specifically line 73)
- Test: `backend/tests/parser/test_service.py`

- [ ] **Step 1: Write a failing test**

Open `backend/tests/parser/test_service.py` and locate the existing fixture pattern (it constructs an EventBus, registers the handler, publishes a `MessagePayload`). Add:

```python
import pytest

from app.core.event_bus import Event, EventBus
from app.core.events import MessagePayload, TaskPayload, Topics
from app.parser.service import register_parser_listener  # adapt name if different


@pytest.mark.asyncio
async def test_handler_propagates_is_historical_true_to_task(
    bus_with_parser,  # use this fixture name if it exists; otherwise inline the wiring
):
    """When MessagePayload.is_historical=True, the resulting Task must carry it."""
    captured: list[TaskPayload] = []
    bus_with_parser.bus.subscribe(
        Topics.TASK_CREATED, lambda e: captured.append(e.payload)
    )

    msg = make_test_message(id="hist-msg-1")  # use existing fixture helper
    await bus_with_parser.bus.publish(
        Event(Topics.MESSAGE_RECEIVED, MessagePayload(message=msg, is_historical=True))
    )

    assert any(p.task.id == "hist-msg-1" and p.task.is_historical for p in captured)


@pytest.mark.asyncio
async def test_handler_default_is_historical_false_on_task(bus_with_parser):
    captured: list[TaskPayload] = []
    bus_with_parser.bus.subscribe(
        Topics.TASK_CREATED, lambda e: captured.append(e.payload)
    )

    msg = make_test_message(id="live-msg-1")
    await bus_with_parser.bus.publish(
        Event(Topics.MESSAGE_RECEIVED, MessagePayload(message=msg))  # default
    )

    assert any(p.task.id == "live-msg-1" and not p.task.is_historical for p in captured)
```

> If the file uses different fixture / helper names (likely — check the file before writing), adapt the symbols accordingly. The behavioral assertion is the part that matters: `task.is_historical == payload.is_historical`.

- [ ] **Step 2: Run the test, confirm it fails**

```bash
cd backend && .venv/bin/pytest tests/parser/test_service.py -v -k is_historical
```

Expected: assertion fails because `task.is_historical` is always `False` (handler doesn't read the payload flag yet).

- [ ] **Step 3: Patch the handler**

Edit `backend/app/parser/service.py:73`. Replace:

```python
        msg = payload.message
        task = Task.new_from_message(msg)
```

With:

```python
        msg = payload.message
        task = Task.new_from_message(msg, is_historical=payload.is_historical)
```

- [ ] **Step 4: Run the tests, confirm they pass**

```bash
cd backend && .venv/bin/pytest tests/parser/test_service.py -v
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add backend/app/parser/service.py backend/tests/parser/test_service.py
git commit -m "feat(parser): propagate MessagePayload.is_historical onto Task"
```

---

## Task 7: `PageSettings` — delete old field, add new

**Files:**
- Modify: `backend/app/whop/page_settings.py:20-135`
- Test: `backend/tests/whop/test_page_settings.py`

- [ ] **Step 1: Write failing tests for the new field**

Edit `backend/tests/whop/test_page_settings.py`. Delete every test case that mentions `block_non_today_messages` (those will be replaced). Add new cases:

```python
def test_default_stock_settings_block_historical_false():
    s = default_settings_for("stock")
    assert s.block_historical_messages is False


def test_default_option_settings_block_historical_false():
    s = default_settings_for("option")
    assert s.block_historical_messages is False


def test_to_dict_writes_block_historical_key():
    s = PageSettings(
        dedupe_processed_messages=True,
        price_deviation_tolerance=1.0,
        block_historical_messages=True,
        launch_headless=False,
        tickers={},
    )
    d = page_settings_to_dict(s)
    assert d["block_historical_messages"] is True
    assert "block_non_today_messages" not in d


def test_from_dict_reads_block_historical_key():
    d = {
        "dedupe_processed_messages": True,
        "price_deviation_tolerance": 1.0,
        "block_historical_messages": True,
        "launch_headless": False,
    }
    s = page_settings_from_dict(d, source="stock")
    assert s.block_historical_messages is True


def test_from_dict_missing_key_defaults_to_false():
    d = {
        "dedupe_processed_messages": True,
        "price_deviation_tolerance": 1.0,
        "launch_headless": False,
    }
    s = page_settings_from_dict(d, source="stock")
    assert s.block_historical_messages is False


def test_from_dict_ignores_legacy_block_non_today_key():
    """Legacy key in saved JSON must not silently activate the new field."""
    d = {
        "dedupe_processed_messages": True,
        "price_deviation_tolerance": 1.0,
        "block_non_today_messages": True,  # legacy
        "launch_headless": False,
    }
    s = page_settings_from_dict(d, source="stock")
    assert s.block_historical_messages is False
```

- [ ] **Step 2: Run the tests, confirm failures**

```bash
cd backend && .venv/bin/pytest tests/whop/test_page_settings.py -v
```

Expected: failures because `PageSettings` still has `block_non_today_messages`, not `block_historical_messages`.

- [ ] **Step 3: Edit `backend/app/whop/page_settings.py`**

Replace line 24 (`block_non_today_messages: bool = False  # ...`) with:

```python
    block_historical_messages: bool = False  # 拦截下单历史消息（posted_at < listener.started_at），仅解析不下单
```

In `DEFAULT_STOCK_SETTINGS` (line 34-40), replace `block_non_today_messages=False,` with:

```python
    block_historical_messages=False,
```

In `DEFAULT_OPTION_SETTINGS` (line 42-52), replace `block_non_today_messages=False,` with:

```python
    block_historical_messages=False,
```

In `default_settings_for` (line 55-76), replace both `block_non_today_messages=DEFAULT_*_SETTINGS.block_non_today_messages,` lines with:

```python
        block_historical_messages=DEFAULT_STOCK_SETTINGS.block_historical_messages,
```

(and the option counterpart with `DEFAULT_OPTION_SETTINGS`).

In `page_settings_to_dict` (line 79-92), replace `"block_non_today_messages": s.block_non_today_messages,` with:

```python
        "block_historical_messages": s.block_historical_messages,
```

In `page_settings_from_dict` (line 95-135), delete the `block = bool(d.get("block_non_today_messages", base.block_non_today_messages))` line. Replace with:

```python
    block_historical = bool(d.get("block_historical_messages", base.block_historical_messages))
```

In the final `return PageSettings(...)` block, replace `block_non_today_messages=block,` with:

```python
        block_historical_messages=block_historical,
```

- [ ] **Step 4: Run the tests, confirm they pass**

```bash
cd backend && .venv/bin/pytest tests/whop/test_page_settings.py -v
```

Expected: all new cases pass; no leftover `block_non_today_messages` references.

- [ ] **Step 5: Commit**

```bash
git add backend/app/whop/page_settings.py backend/tests/whop/test_page_settings.py
git commit -m "feat(page_settings): replace block_non_today_messages with block_historical_messages"
```

---

## Task 8: API schemas + http handler swap

**Files:**
- Modify: `backend/app/api/schemas.py:236-259` (`WhopPageSettingsOut`, `WhopPageSettingsPatch`), `:449` (`whop_page_to_out`)
- Modify: `backend/app/api/http.py:526` (read), `:551-552` (patch assembly)
- Test: `backend/tests/api/test_whop_settings.py`

- [ ] **Step 1: Update API tests**

Open `backend/tests/api/test_whop_settings.py`. Find every assertion of the form:

```python
assert s["block_non_today_messages"] is False
```

Replace with:

```python
assert s["block_historical_messages"] is False
```

Find any PATCH body that sets `block_non_today_messages` and rename the key to `block_historical_messages`. Add a new test asserting the new field round-trips:

```python
@pytest.mark.asyncio
async def test_patch_block_historical_messages(client, page_id):
    r = await client.patch(
        f"/api/whop/pages/{page_id}/settings",
        json={"block_historical_messages": True},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["settings"]["block_historical_messages"] is True

    g = await client.get(f"/api/whop/pages/{page_id}")
    assert g.json()["settings"]["block_historical_messages"] is True
```

> Adapt fixture names (`client`, `page_id`) to match this file's existing pattern.

- [ ] **Step 2: Run, confirm failures**

```bash
cd backend && .venv/bin/pytest tests/api/test_whop_settings.py -v
```

Expected: 422 / KeyError because schemas still have the old field.

- [ ] **Step 3: Update `backend/app/api/schemas.py`**

In `WhopPageSettingsOut` (line 236-245), replace `block_non_today_messages: bool` with:

```python
    block_historical_messages: bool
```

In `WhopPageSettingsPatch` (line 248-259), replace `block_non_today_messages: bool | None = None` with:

```python
    block_historical_messages: bool | None = None
```

At line 449 (inside `whop_page_to_out`), replace `block_non_today_messages=entry.settings.block_non_today_messages,` with:

```python
        block_historical_messages=entry.settings.block_historical_messages,
```

- [ ] **Step 4: Update `backend/app/api/http.py`**

At line 526 (read path inside `WhopPageSettingsOut(...)`), replace:

```python
                block_non_today_messages=s.block_non_today_messages,
```

with:

```python
                block_historical_messages=s.block_historical_messages,
```

At lines 551-552 (PATCH body assembly), replace:

```python
            if body.block_non_today_messages is not None:
                patch_dict["block_non_today_messages"] = body.block_non_today_messages
```

with:

```python
            if body.block_historical_messages is not None:
                patch_dict["block_historical_messages"] = body.block_historical_messages
```

- [ ] **Step 5: Run the API tests, confirm they pass**

```bash
cd backend && .venv/bin/pytest tests/api/test_whop_settings.py -v
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/schemas.py backend/app/api/http.py backend/tests/api/test_whop_settings.py
git commit -m "feat(api): replace block_non_today_messages with block_historical_messages"
```

---

## Task 9: Trader gate replacement + test rewrite

**Files:**
- Modify: `backend/app/broker/trader.py:217-233`
- Test: `backend/tests/broker/test_trader_deviation.py:306-358` (rewrite the three non-today cases)
- Test: `backend/tests/broker/test_trader.py` (PageSettings constructions referencing old field — update)
- Test: `backend/tests/broker/test_trader_lot_lookup.py` (same — update)

- [ ] **Step 1: Sweep broker tests for old PageSettings keyword**

```bash
grep -rn "block_non_today_messages" backend/tests/broker/
```

Expected: a handful of `PageSettings(... block_non_today_messages=False, ...)` constructions in `test_trader.py` and `test_trader_lot_lookup.py`, plus the three SKIPPED-flow cases at `test_trader_deviation.py:306-358`.

- [ ] **Step 2: Bulk-replace `block_non_today_messages=` keyword in non-deviation tests**

In `backend/tests/broker/test_trader.py` (line 403) and `backend/tests/broker/test_trader_lot_lookup.py` (line 77), replace:

```python
block_non_today_messages=False,
```

with:

```python
block_historical_messages=False,
```

(Use `Edit replace_all=true` if a file has multiple instances; verify with grep after.)

- [ ] **Step 3: Rewrite `test_trader_deviation.py:306-358` cases**

Open `backend/tests/broker/test_trader_deviation.py`. Locate the three "non-today → SKIPPED" tests around lines 306-358 (look for the case strings such as `"""When block_non_today_messages=True, a message posted yesterday → SKIPPED."""`).

Delete all three. Insert four replacement cases (covering both stock and option shapes):

```python
@pytest.mark.asyncio
async def test_block_historical_skips_stock_when_marker_true(...):
    """is_historical=True + block_historical_messages=True → SKIPPED with reason '历史消息'."""
    page_settings = PageSettings(
        dedupe_processed_messages=True,
        price_deviation_tolerance=1.0,
        block_historical_messages=True,
        launch_headless=False,
        tickers={"AAPL": TickerConfig(trade_quantity=10)},
    )
    task = make_stock_task(ticker="AAPL", is_historical=True)  # adapt to file's helper
    # ... wire trader, run, assert ...
    assert task.status is Status.SKIPPED
    assert "历史消息" in (task.reject_reason or "")


@pytest.mark.asyncio
async def test_block_historical_skips_option_when_marker_true(...):
    """Same as above but with an OptionInstruction."""
    page_settings = PageSettings(
        dedupe_processed_messages=True,
        price_deviation_tolerance=5.0,
        block_historical_messages=True,
        launch_headless=False,
        tickers=None,
    )
    task = make_option_task(is_historical=True)
    # ... wire trader, run, assert ...
    assert task.status is Status.SKIPPED
    assert "历史消息" in (task.reject_reason or "")


@pytest.mark.asyncio
async def test_block_historical_setting_off_proceeds_even_with_marker_true(...):
    """is_historical=True + setting=False → passes ① b, hits whitelist / completeness."""
    page_settings = PageSettings(
        dedupe_processed_messages=True,
        price_deviation_tolerance=1.0,
        block_historical_messages=False,  # explicit
        launch_headless=False,
        tickers={"AAPL": TickerConfig(trade_quantity=10)},
    )
    task = make_stock_task(ticker="AAPL", is_historical=True)
    # ... assert task progresses past the gate (not SKIPPED for "历史消息") ...


@pytest.mark.asyncio
async def test_block_historical_marker_false_proceeds_even_with_setting_on(...):
    """is_historical=False + setting=True → not blocked by ① b."""
    page_settings = PageSettings(
        dedupe_processed_messages=True,
        price_deviation_tolerance=1.0,
        block_historical_messages=True,
        launch_headless=False,
        tickers={"AAPL": TickerConfig(trade_quantity=10)},
    )
    task = make_stock_task(ticker="AAPL", is_historical=False)
    # ... assert task progresses past the gate ...
```

> Use the existing trader-test helper conventions in this file (whatever pattern it uses to build a Task + run trader + assert outcomes). The four assertions above are the contracts that must hold.

- [ ] **Step 4: Run the broker test suite to confirm failures**

```bash
cd backend && .venv/bin/pytest tests/broker/ -v -k "historical or block_non_today"
```

Expected: the new 4 tests fail (gate still uses old field name); the renamed `block_historical_messages=False` constructions in test_trader.py / test_trader_lot_lookup.py may now error on PageSettings init (because it's already renamed in Task 7 — they should pass actually, but if they error, that confirms the wiring).

- [ ] **Step 5: Replace the trader gate body**

Edit `backend/app/broker/trader.py:217-233`. Delete the entire `# ① b. Non-today-message check` block:

```python
        # ① b. Non-today-message check (per-page setting).
        # Use UTC dates on both sides so the displayed reason matches the
        # UI: posted_at is stored as Whop's wall-clock with a Z suffix and
        # the frontend strips T/Z without timezone conversion (see
        # frontend cardHelpers.fmtTime). Comparing in any other frame
        # produces a date that disagrees with what the user sees on the card.
        if page_settings is not None and page_settings.block_non_today_messages:
            from datetime import UTC, datetime

            posted_date = task.message.posted_at.astimezone(UTC).date()
            today_date = datetime.now(UTC).date()
            if posted_date != today_date:
                await _publish_skip(
                    task,
                    f"非当天消息（posted={posted_date}, today={today_date}）",
                )
                return
```

Replace with:

```python
        # ① b. Historical-message check (per-page setting).
        # The listener tagged this task at capture time when message.posted_at
        # was earlier than the listener's started_at. Setting + marker → SKIP.
        if (
            page_settings is not None
            and page_settings.block_historical_messages
            and task.is_historical
        ):
            await _publish_skip(
                task,
                f"历史消息（posted={task.message.posted_at}）",
            )
            return
```

- [ ] **Step 6: Run the broker tests, confirm all pass**

```bash
cd backend && .venv/bin/pytest tests/broker/ -v
```

Expected: all pass.

- [ ] **Step 7: Run the full backend suite once to catch any straggler**

```bash
cd backend && .venv/bin/pytest -q
```

Expected: all pass. If anything still references `block_non_today_messages`, grep and fix:

```bash
grep -rn "block_non_today" backend/app/ backend/tests/ backend/alembic/
```

Expected: zero hits.

- [ ] **Step 8: Commit**

```bash
git add backend/app/broker/trader.py backend/tests/broker/
git commit -m "feat(trader): replace non-today gate with historical-marker gate"
```

---

## Task 10: Frontend modal + test fixture sweep

**Files:**
- Modify: `frontend/src/components/Dashboard/PageSettingsModal.tsx:13-89`
- Modify: `frontend/src/components/Dashboard/PageSettingsModal.test.tsx:12, 28, 75-83`
- Modify (fixture key only): `frontend/src/stores/pageTabs.test.ts:11`
- Modify (fixture key only): `frontend/src/components/Dashboard/PageInfoBar.test.tsx:8`
- Modify (fixture key only): `frontend/src/components/Dashboard/PageTabs.test.tsx:9`
- Modify (fixture key only): `frontend/src/components/Dashboard/PageActionBar.test.tsx:9`

- [ ] **Step 1: Regenerate `domain-types.ts` from the updated openapi**

```bash
cd backend && .venv/bin/python -m app.api.openapi_dump > /tmp/openapi.json 2>/dev/null \
  || .venv/bin/python -c "from app.api.http import app; import json; print(json.dumps(app.openapi()))" > /tmp/openapi.json
cd ../frontend && npm run gen-types 2>&1 | tail -5
```

> Adapt to whatever script the project uses for openapi → TS generation. If `npm run gen-types` doesn't exist, `grep "openapi" frontend/package.json` to find the right script. If the project commits `domain-types.ts` by hand, instead manually search-and-replace `block_non_today_messages` → `block_historical_messages` in `frontend/src/api/domain-types.ts` (one line).

- [ ] **Step 2: Update fixture files (non-test-logic changes)**

In each of these files, replace the literal `block_non_today_messages: false` with `block_historical_messages: false`:

- `frontend/src/stores/pageTabs.test.ts:11`
- `frontend/src/components/Dashboard/PageInfoBar.test.tsx:8`
- `frontend/src/components/Dashboard/PageTabs.test.tsx:9`
- `frontend/src/components/Dashboard/PageActionBar.test.tsx:9`

(Use `Edit` per file. These are pure fixture key swaps with no behavioral change.)

- [ ] **Step 3: Write failing modal-test cases**

Edit `frontend/src/components/Dashboard/PageSettingsModal.test.tsx`. At lines 12 and 28, replace `block_non_today_messages: false` with `block_historical_messages: false`. Replace the test at lines 75-83 with:

```typescript
it("toggling block_historical_messages saves it", async () => {
  const updateSpy = vi.spyOn(httpModule.api, "updateWhopPageSettings").mockResolvedValue(undefined);
  render(<PageSettingsModal page={stockPage} onClose={() => {}} />);

  const checkbox = screen.getByLabelText(/禁止下单历史消息/);
  fireEvent.click(checkbox);
  fireEvent.click(screen.getByText("保存"));

  await waitFor(() => expect(updateSpy).toHaveBeenCalled());
  const arg = updateSpy.mock.calls[0][1] as Record<string, unknown>;
  expect(arg.block_historical_messages).toBe(true);
  expect("block_non_today_messages" in arg).toBe(false);
});
```

- [ ] **Step 4: Run, confirm failure**

```bash
cd frontend && npm test -- --run PageSettingsModal 2>&1 | tail -30
```

Expected: failure citing missing label `禁止下单历史消息` (the modal still renders the old label).

- [ ] **Step 5: Patch `PageSettingsModal.tsx`**

Edit `frontend/src/components/Dashboard/PageSettingsModal.tsx`.

Line 15 — replace:

```typescript
  const [blockNonToday, setBlockNonToday] = useState(page.settings.block_non_today_messages);
```

with:

```typescript
  const [blockHistorical, setBlockHistorical] = useState(page.settings.block_historical_messages);
```

Line 87 — in `handleSave`, replace:

```typescript
        block_non_today_messages: blockNonToday,
```

with:

```typescript
        block_historical_messages: blockHistorical,
```

Lines 146-158 — replace the entire `<section>`:

```tsx
          <section>
            <label>
              <input
                type="checkbox"
                checked={blockNonToday}
                onChange={e => setBlockNonToday(e.target.checked)}
              />
              <span>禁止下单非当天消息（仅解析指令，不发送订单）</span>
            </label>
            <p className="hint small">
              当消息的发布日期与服务器今日不同时，trader 跳过下单（任务标记 SKIPPED）。
            </p>
          </section>
```

with:

```tsx
          <section>
            <label>
              <input
                type="checkbox"
                checked={blockHistorical}
                onChange={e => setBlockHistorical(e.target.checked)}
              />
              <span>禁止下单历史消息（消息发布时间早于本次监听启动时间）</span>
            </label>
            <p className="hint small">
              消息 posted_at &lt; listener.started_at → 任务标记 SKIPPED（仅解析入库，不发送订单）。比"按当天/非当天"更细：当天但启动前发布的消息也会被拦。
            </p>
          </section>
```

The section stays in the common settings area (above the `page.source === "option"` block), so it renders for both stock and option pages.

- [ ] **Step 6: Run modal tests, confirm pass**

```bash
cd frontend && npm test -- --run PageSettingsModal 2>&1 | tail -20
```

Expected: pass.

- [ ] **Step 7: Run the full frontend suite**

```bash
cd frontend && npm test -- --run 2>&1 | tail -20
```

Expected: pass. If `domain-types.ts` regen left anything inconsistent, fix and re-run. If anything still references `block_non_today_messages`:

```bash
grep -rn "block_non_today" frontend/src/
```

Expected: zero hits.

- [ ] **Step 8: Smoke-test the UI**

```bash
cd backend && .venv/bin/uvicorn app.api.http:app --reload --port 8000 &
cd ../frontend && npm run dev &
```

Open `http://localhost:5173` (or whatever port the project uses), navigate to a Whop page, open the ⚙ Settings modal. Verify:
- The "禁止下单历史消息" section renders for both stock and option pages.
- Toggling and saving persists (close and reopen the modal — the checkbox state is restored).
- No console errors.

Stop the servers with `kill %1 %2` (or your preferred method).

- [ ] **Step 9: Commit**

```bash
git add frontend/src/
git commit -m "feat(ui): replace block_non_today_messages with block_historical_messages"
```

---

## Task 11: CHANGELOG + final verification

**Files:**
- Modify: `CHANGELOG.md` (append to `## Unreleased`)

- [ ] **Step 1: Edit `CHANGELOG.md`**

Under `## Unreleased`, add (or extend) `### Removed` and `### Changed` sections with:

```markdown
### Removed
- **BREAKING**: per-page 设置 `block_non_today_messages`（字段、API、UI、测试、`whop_pages.json` key）整体删除。已勾选该开关的用户升级后会丢失设置，需要在新 UI 上重新勾选 `禁止下单历史消息`。

### Changed
- **BREAKING**: 替换"非当天消息拦截"为更细的"历史消息拦截"——消息 `posted_at < listener.started_at` 即被 trader SKIPPED。新增 `Task.is_historical` 列（alembic migration 加列，默认 0）。同时支持股票和期权页面。
```

- [ ] **Step 2: Run the entire test matrix one last time**

```bash
cd backend && .venv/bin/pytest -q && cd ../frontend && npm test -- --run 2>&1 | tail -10
```

Expected: backend all pass; frontend all pass.

- [ ] **Step 3: Final grep sweep — there should be zero references to the old field anywhere**

```bash
grep -rn "block_non_today" backend/ frontend/ docs/superpowers/plans/ docs/superpowers/specs/ CHANGELOG.md
```

Expected:
- backend / frontend → zero hits
- docs/superpowers/specs/ → only mentions inside the design doc that explain the rationale (those are intentional history)
- CHANGELOG.md → the BREAKING entry just added

If unexpected hits surface in `backend/` or `frontend/`, fix them.

- [ ] **Step 4: Confirm Alembic migration head matches**

```bash
cd backend && .venv/bin/alembic current && .venv/bin/alembic heads
```

Expected: both report the new revision id added in Task 4.

- [ ] **Step 5: Commit**

```bash
git add CHANGELOG.md
git commit -m "docs(changelog): block_non_today_messages → block_historical_messages BREAKING"
```

- [ ] **Step 6: Push branch and report**

```bash
git push -u origin refactor-v2
```

Report to user: branch updated; PR can be opened. Summarize commits with `git log --oneline -12`.

---

## Self-Review Checklist (for the implementer)

Before declaring done:

- [ ] Spec §2 (User-Visible Change) — modal section deleted + new section added ✅ Task 10
- [ ] Spec §3 (Architecture) — listener tags, handler propagates, trader gates ✅ Tasks 5/6/9
- [ ] Spec §4.1 (page_settings.py) — old field deleted, new field added, no fallback ✅ Task 7
- [ ] Spec §4.2 (listener) — `_scan_once` computes is_historical ✅ Task 5
- [ ] Spec §4.3 (events / handler / domain) — MessagePayload + Task field + handler ✅ Tasks 1/2/6
- [ ] Spec §4.4 (storage) — TaskRow column + repo round-trip + Alembic ✅ Tasks 3/4
- [ ] Spec §4.5 (trader) — gate ① b replaced ✅ Task 9
- [ ] Spec §4.6 (frontend) — modal + state + patch body, common section (not option-only) ✅ Task 10
- [ ] Spec §4.7 (tests) — all bullets covered: page_settings, listener, handler, repo, trader (stock+option), API, modal ✅ all tasks
- [ ] Spec §5 (migration) — Alembic + zero-touch JSON + CHANGELOG ✅ Tasks 4/7/11
- [ ] No `block_non_today_messages` left anywhere except the spec doc ✅ Task 11 step 3
