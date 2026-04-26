# Confirm / Skip Buttons + Parser Parameter Validation — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add web-styled confirm/skip icon buttons to task cards (compact + expanded forms) for manual order confirmation when `auto_trade` is OFF; gate `INSTRUCTION_READY` on parser-stage parameter completeness so incomplete instructions are SKIPPED with a clear reason instead of falling through to the trader.

**Architecture:** Two coupled but independently-shippable changes. (1) Backend: extend the task state machine to allow `PARSING → SKIPPED`, add a `validate_for_submission` gate at the end of `parser/service.py`, and add a new `POST /api/tasks/{id}/skip` endpoint for manual cancellation. (2) Frontend: introduce `<ConfirmActions>` component (two 26 px square SVG icon buttons), wire it into `CardCompact` (replaces the status pill cell when `autoTrade=false && status=INSTRUCTION_READY && instruction!=null`) and `CardExpanded` (replaces the existing single-button `manual-confirm-row`). Cancel transitions the task to `SKIPPED` with `reject_reason="用户手动取消"`.

**Tech Stack:** Python (backend, pytest, FastAPI, SQLAlchemy async, asyncio EventBus), TypeScript + React + Vitest + Testing Library (frontend), CSS variables for tokens.

**Spec:** `docs/superpowers/specs/2026-04-26-confirm-skip-buttons-design.md`

---

## File Structure

### Backend

| File | Responsibility | Change kind |
|------|----------------|-------------|
| `backend/app/domain/status.py` | State-machine transition table | Modify (add `PARSING→SKIPPED`) |
| `backend/app/parser/validation.py` | Pure function: required-field check on `Instruction` | **Create** |
| `backend/app/parser/service.py` | Run `validate_for_submission` after parse; emit `STATUS_CHANGED + SKIPPED` on failure | Modify |
| `backend/app/api/http.py` | `POST /api/tasks/{id}/skip` endpoint | Modify (add route) |
| `backend/tests/domain/test_status.py` | State-machine cases | Modify (extend parametrize) |
| `backend/tests/parser/test_validation.py` | Pure-function tests | **Create** |
| `backend/tests/parser/test_service.py` | Service end-to-end behavior | Modify (add validation case) |
| `backend/tests/parser/test_snapshot_regression.py` | Snapshot tests over real corpus | Possibly update if snapshots break |
| `backend/tests/api/test_http.py` | HTTP contract | Modify (add 3 skip tests) |

### Frontend

| File | Responsibility | Change kind |
|------|----------------|-------------|
| `frontend/src/components/Card/ConfirmActions.tsx` | Self-contained confirm + skip icon-button group; manages loading + error state | **Create** |
| `frontend/src/components/Card/ConfirmActions.test.tsx` | Component tests | **Create** |
| `frontend/src/components/Card/Card.tsx` | Forward `autoTrade` to compact form | Modify |
| `frontend/src/components/Card/CardCompact.tsx` | Conditionally render `ConfirmActions` in column 7 | Modify |
| `frontend/src/components/Card/CardCompact.test.tsx` | Coverage for new column-7 conditional | Modify |
| `frontend/src/components/Card/CardExpanded.tsx` | Replace inline confirm-only row with `ConfirmActions` | Modify (delete state + handler, swap row) |
| `frontend/src/components/Card/CardExpanded.test.tsx` | Update existing manual-confirm test | Modify |
| `frontend/src/components/Card/Card.css` | New `.confirm-actions / .ca-btn / .ca-spinner / .ca-err / .confirm-actions-row / .confirm-hint`; remove old `.manual-confirm-*` | Modify |
| `frontend/src/api/http.ts` | Add `skipTask(id)` method | Modify |
| `frontend/src/api/http.test.ts` | Coverage for `skipTask` | Modify |
| `.gitignore` | Add `.superpowers/` (brainstorm artifacts) | Modify |

### Commit grouping

1. **chore(domain): allow PARSING → SKIPPED transition** — Task 1
2. **feat(parser): validate required fields before INSTRUCTION_READY** — Task 2 (depends on 1)
3. **feat(api): POST /api/tasks/{id}/skip — manual cancel pre-submit** — Task 3 (independent of 2)
4. **feat(card): confirm/skip icon buttons with web style** — Task 4 (depends on 3)

---

## Task 1: Allow `PARSING → SKIPPED` state-machine transition

**Files:**
- Modify: `backend/app/domain/status.py:39`
- Modify: `backend/tests/domain/test_status.py:18-39` (parametrize block)

- [ ] **Step 1.1: Add the failing parametrize cases**

Edit `backend/tests/domain/test_status.py`. Find the existing `@pytest.mark.parametrize` block at lines 17–40 and add two new entries:

```python
        (Status.PARSING, Status.SKIPPED, True),
        # Negative: SKIPPED is terminal, can't go back
        (Status.SKIPPED, Status.PARSING, False),
```

Insert the positive case among the other `True` rows (e.g. right after `(Status.PARSING, Status.INSTRUCTION_READY, True),`), and the negative one in the negative-rules group.

- [ ] **Step 1.2: Run the test — confirm new positive case fails**

Run: `cd backend && uv run pytest tests/domain/test_status.py -v`
Expected: the `(Status.PARSING, Status.SKIPPED, True)` parametrize case fails with `assert False is True`.

- [ ] **Step 1.3: Add SKIPPED to the allowed PARSING transitions**

Edit `backend/app/domain/status.py:39` (inside `_ALLOWED`):

```python
    Status.PARSING: frozenset({Status.PARSE_ERROR, Status.INSTRUCTION_READY, Status.SKIPPED}),
```

- [ ] **Step 1.4: Run the full domain test file — all green**

Run: `cd backend && uv run pytest tests/domain/test_status.py -v`
Expected: all parametrize cases pass.

- [ ] **Step 1.5: Commit**

```bash
git add backend/app/domain/status.py backend/tests/domain/test_status.py
git commit -m "$(cat <<'EOF'
chore(domain): allow PARSING → SKIPPED transition

Required by parser-stage parameter completeness validation, which lands
in a follow-up commit. SKIPPED remains terminal; only the inbound edge
from PARSING is added.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Parser parameter completeness validation

**Files:**
- Create: `backend/app/parser/validation.py`
- Create: `backend/tests/parser/test_validation.py`
- Modify: `backend/app/parser/service.py:120-128`
- Modify: `backend/tests/parser/test_service.py` (append new test)
- Possibly modify: `backend/tests/parser/test_snapshot_regression.py`

### 2A — Pure validation function (TDD)

- [ ] **Step 2A.1: Write the failing tests for `validate_for_submission`**

Create `backend/tests/parser/test_validation.py`:

```python
"""Tests for app.parser.validation.validate_for_submission."""
from __future__ import annotations

from datetime import date

import pytest

from app.domain.instruction import (
    InstructionType,
    OptionInstruction,
    StockInstruction,
)
from app.parser.validation import validate_for_submission


def _stock(**overrides) -> StockInstruction:
    base = dict(
        instruction_type=InstructionType.BUY,
        price=26.5,
        price_range=None,
        quantity=100,
        position_size=None,
        stop_loss_price=None,
        take_profit_price=None,
        context_source=None,
        parser_notes=[],
        ticker="TSLL",
        symbol="TSLL.US",
        sell_quantity=None,
    )
    base.update(overrides)
    return StockInstruction(**base)


def _option(**overrides) -> OptionInstruction:
    base = dict(
        instruction_type=InstructionType.BUY,
        price=2.15,
        price_range=None,
        quantity=2,
        position_size=None,
        stop_loss_price=None,
        take_profit_price=None,
        context_source=None,
        parser_notes=[],
        ticker="NVDA",
        option_type="CALL",
        strike=135.0,
        expiry=date(2026, 4, 26),
        symbol="NVDA260426C135000.US",
    )
    base.update(overrides)
    return OptionInstruction(**base)


# ---------- happy paths ----------

def test_stock_complete_returns_none():
    assert validate_for_submission(_stock()) is None


def test_option_complete_returns_none():
    assert validate_for_submission(_option()) is None


def test_stock_with_price_range_only_returns_none():
    assert validate_for_submission(_stock(price=None, price_range=(26.0, 27.0))) is None


# ---------- stock missing fields ----------

def test_stock_missing_quantity():
    reason = validate_for_submission(_stock(quantity=None))
    assert reason is not None
    assert "数量" in reason


def test_stock_zero_quantity():
    reason = validate_for_submission(_stock(quantity=0))
    assert reason is not None
    assert "数量" in reason


def test_stock_close_instruction_type_rejected():
    reason = validate_for_submission(_stock(instruction_type=InstructionType.CLOSE))
    assert reason is not None
    assert "BUY" in reason and "SELL" in reason


def test_stock_modify_instruction_type_rejected():
    reason = validate_for_submission(_stock(instruction_type=InstructionType.MODIFY))
    assert reason is not None
    assert "BUY" in reason and "SELL" in reason


# ---------- option missing fields ----------

def test_option_missing_quantity():
    reason = validate_for_submission(_option(quantity=None))
    assert reason is not None
    assert "数量" in reason


def test_option_zero_strike():
    reason = validate_for_submission(_option(strike=0))
    assert reason is not None
    assert "行权价" in reason


def test_option_no_expiry_falsy():
    # Construct an OptionInstruction with a falsy expiry (sentinel: 1970-01-01
    # is truthy; mock by direct attribute assignment after construction).
    inst = _option()
    inst.expiry = None  # type: ignore[assignment]
    reason = validate_for_submission(inst)
    assert reason is not None
    assert "到期日" in reason


def test_option_invalid_type_rejected():
    inst = _option()
    inst.option_type = "UNKNOWN"  # type: ignore[assignment]
    reason = validate_for_submission(inst)
    assert reason is not None
    assert "CALL/PUT" in reason


# ---------- error string format ----------

def test_reason_starts_with_zh_prefix():
    reason = validate_for_submission(_stock(quantity=None))
    assert reason is not None
    assert reason.startswith("参数不齐: ")


def test_reason_lists_multiple_missing_fields():
    inst = _stock(quantity=None, instruction_type=InstructionType.CLOSE)
    reason = validate_for_submission(inst)
    assert reason is not None
    assert "数量" in reason
    assert "BUY" in reason and "SELL" in reason
    # Two missing → the joiner should appear
    assert "、" in reason
```

> Note: `StockInstruction.__post_init__` requires `ticker`, and `Instruction.__post_init__` requires `price` or `price_range`. Tests that would violate those constructor invariants (e.g. ticker="") cannot be constructed in the normal way; we don't test those branches at the validation layer because the dataclass already rejects them at construction. The validation function still defends against them (cheap belt-and-braces) but we don't exercise dead paths here.

- [ ] **Step 2A.2: Run — confirm import error**

Run: `cd backend && uv run pytest tests/parser/test_validation.py -v`
Expected: `ImportError: cannot import name 'validate_for_submission' from 'app.parser.validation'` (or `ModuleNotFoundError` since the file doesn't exist yet).

- [ ] **Step 2A.3: Implement `validate_for_submission`**

Create `backend/app/parser/validation.py`:

```python
"""End-of-parse validation: does the produced Instruction carry every field
the trader needs to submit an order?

The parser may successfully extract *some* of an instruction (ticker + price
but no quantity, for example). Without this gate, such half-instructions
would be promoted to INSTRUCTION_READY and fall through to the trader's ad
hoc guards. With this gate, they are SKIPPED at parse time with a precise
Chinese reason — independent of auto_trade.
"""
from __future__ import annotations

from app.domain.instruction import (
    Instruction,
    InstructionType,
    OptionInstruction,
    StockInstruction,
)


def validate_for_submission(inst: Instruction) -> str | None:
    """Return a Chinese reason string when *inst* is missing fields required
    for submission, or ``None`` when complete.
    """
    missing: list[str] = []

    # Common required fields
    if inst.instruction_type not in (InstructionType.BUY, InstructionType.SELL):
        missing.append(f"方向(BUY/SELL,当前: {inst.instruction_type})")
    if inst.quantity is None or inst.quantity <= 0:
        missing.append("数量")
    if inst.price is None and not inst.price_range:
        missing.append("价格")

    if isinstance(inst, StockInstruction):
        if not inst.ticker:
            missing.append("股票名")
    elif isinstance(inst, OptionInstruction):
        if not inst.ticker:
            missing.append("股票")
        if not inst.strike or inst.strike <= 0:
            missing.append("行权价")
        if inst.option_type not in ("CALL", "PUT"):
            missing.append("CALL/PUT")
        if not inst.expiry:
            missing.append("到期日")

    if missing:
        return "参数不齐: " + "、".join(missing)
    return None
```

- [ ] **Step 2A.4: Run validation tests — all green**

Run: `cd backend && uv run pytest tests/parser/test_validation.py -v`
Expected: all 13 cases pass.

### 2B — Wire validation into the parser service

- [ ] **Step 2B.1: Write the failing service-level test**

Append to `backend/tests/parser/test_service.py`:

```python
# ---------------------------------------------------------------------------
# Test 6: stock parsed but missing quantity → SKIPPED, no INSTRUCTION_READY
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stock_missing_quantity_emits_skipped(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A stock signal that yields a parseable instruction but lacks
    quantity must terminate at SKIPPED with reject_reason citing the
    missing field, and TASK_INSTRUCTION_READY must NOT be published."""
    bus = EventBus()
    register_parser_service(bus, session_factory, registry=_fake_registry({"TSLL"}))

    # No position_size, no quantity hints — parser will produce inst with quantity=None
    msg = _stock_msg("s-noqty", "TSLL 26.5 买")
    observed = await _run(bus, msg)

    topics = [e.topic for e in observed]
    assert Topics.TASK_INSTRUCTION_READY not in topics, (
        f"expected SKIPPED before INSTRUCTION_READY; got: {topics}"
    )

    status_changed = [e for e in observed if e.topic == Topics.TASK_STATUS_CHANGED]
    assert len(status_changed) >= 1, f"missing TASK_STATUS_CHANGED; got: {topics}"
    payload = status_changed[-1].payload
    assert isinstance(payload, TaskPayload)
    task = payload.task
    assert task.status == Status.SKIPPED
    assert task.reject_reason is not None
    assert "参数不齐" in task.reject_reason
    assert "数量" in task.reject_reason
    # Instruction should still be attached so the UI can render partial info
    assert task.instruction is not None
```

Also extend the `_run` helper's subscribe loop to include `TASK_STATUS_CHANGED` so the test can observe it. Edit lines 86–92:

```python
    for topic in (
        Topics.TASK_CREATED,
        Topics.TASK_INSTRUCTION_READY,
        Topics.TASK_PARSE_FAILED,
        Topics.TASK_STATUS_CHANGED,
    ):
        bus.subscribe(topic, _capture)
```

- [ ] **Step 2B.2: Run — confirm failure**

Run: `cd backend && uv run pytest tests/parser/test_service.py::test_stock_missing_quantity_emits_skipped -v`
Expected: the test fails because the service currently publishes `TASK_INSTRUCTION_READY` for incomplete instructions (or because it cannot parse the message — see note below).

> If the parser fails to parse `"TSLL 26.5 买"` at all (instead of producing a quantity-less instruction), adjust the test message to one the stock_parser is known to handle to the *ticker + price + side* level but not quantity (e.g. one without `加一半 / 加半仓 / 一半仓位` keywords). Run the parser standalone via `uv run python -c "from app.parser.stock_parser import parse; print(parse('<msg>'))"` to find a phrasing that produces `quantity=None`. Document the chosen string in the test comment.

- [ ] **Step 2B.3: Implement the validation gate in `parser/service.py`**

Edit `backend/app/parser/service.py`. Add import near the top:

```python
from app.parser.validation import validate_for_submission
```

(Place it next to the existing `from app.parser import option_parser, stock_parser` line.)

Then replace the block at lines 122-128:

```python
        if resolved is not None:
            task.attach_instruction(resolved)
            await bus.publish(Event(Topics.TASK_INSTRUCTION_READY, TaskPayload(task)))
        else:
            task.mark_parse_failed("无法解析为交易指令")
            await bus.publish(Event(Topics.TASK_PARSE_FAILED, TaskPayload(task)))
```

with:

```python
        if resolved is None:
            task.mark_parse_failed("无法解析为交易指令")
            await bus.publish(Event(Topics.TASK_PARSE_FAILED, TaskPayload(task)))
            return

        reason = validate_for_submission(resolved)
        if reason is not None:
            # Attach the partial instruction so the UI can show what we got.
            # Manual assignment (not attach_instruction) avoids the implicit
            # PARSING → INSTRUCTION_READY transition we're trying to skip.
            task.instruction = resolved
            if isinstance(resolved, OptionInstruction):
                task.type = "option"
            elif isinstance(resolved, StockInstruction):
                task.type = "stock"
            task.mark_skipped(reason)
            await bus.publish(Event(Topics.TASK_STATUS_CHANGED, TaskPayload(task)))
            return

        task.attach_instruction(resolved)
        await bus.publish(Event(Topics.TASK_INSTRUCTION_READY, TaskPayload(task)))
```

Also add the imports referenced by the new isinstance checks. Near the existing `from app.domain.instruction import Instruction` line, expand to:

```python
from app.domain.instruction import Instruction, OptionInstruction, StockInstruction
```

- [ ] **Step 2B.4: Run the new test — should pass**

Run: `cd backend && uv run pytest tests/parser/test_service.py::test_stock_missing_quantity_emits_skipped -v`
Expected: PASS.

- [ ] **Step 2B.5: Run all parser tests**

Run: `cd backend && uv run pytest tests/parser -v`
Expected: all green. If `test_snapshot_regression.py` fails, inspect which messages are now `SKIPPED` instead of `INSTRUCTION_READY`. The snapshot tests likely store full task summaries with status; update the affected snapshot expectations to reflect the new `SKIPPED + reject_reason` outcome — that *is* the new correct behavior.

- [ ] **Step 2B.6: Run the full backend suite**

Run: `cd backend && uv run pytest -q`
Expected: all green. If `tests/integration/test_acceptance.py` or `tests/broker/test_trader.py` fixtures construct end-to-end scenarios with incomplete instructions, they may need similar fixture updates — adjust them to use complete instructions, since the parser-stage gate now blocks incomplete ones from reaching the trader.

- [ ] **Step 2B.7: Commit**

```bash
git add backend/app/parser/validation.py backend/app/parser/service.py \
        backend/tests/parser/test_validation.py backend/tests/parser/test_service.py \
        backend/tests/parser/test_snapshot_regression.py 2>/dev/null
git status --short  # verify only intended files
git commit -m "$(cat <<'EOF'
feat(parser): validate required fields before INSTRUCTION_READY

Parser now runs validate_for_submission as the final gate of the parse
stage. Stock requires ticker / BUY-or-SELL / quantity / price; option
additionally requires strike / CALL-or-PUT / expiry. Incomplete
instructions terminate at SKIPPED with a Chinese reason citing the
missing fields, and the trader never sees them. Independent of
auto_trade.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: `POST /api/tasks/{id}/skip` endpoint

**Files:**
- Modify: `backend/app/api/http.py:344` (insert after `confirm_task_endpoint`)
- Modify: `backend/tests/api/test_http.py` (append 3 tests)

- [ ] **Step 3.1: Write the failing endpoint tests**

Append to `backend/tests/api/test_http.py`:

```python
# ---------------------------------------------------------------------------
# Skip endpoint — POST /api/tasks/{id}/skip
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def ready_task_for_skip(
    session_factory: async_sessionmaker[AsyncSession],
) -> Task:
    task = _task("skp1", Status.INSTRUCTION_READY, offset_secs=0)
    task.instruction = _stock_instruction()
    async with session_factory() as session:
        await repo.save_task(session, task)
    return task


def test_skip_marks_task_skipped(
    client_and_broker: tuple[TestClient, FakeBrokerClient],
    ready_task_for_skip: Task,
) -> None:
    client, _ = client_and_broker
    resp = client.post("/api/tasks/skp1/skip", params={"token": _TOKEN})
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "SKIPPED"
    assert data["reject_reason"] == "用户手动取消"


def test_skip_404_when_task_missing(
    client_and_broker: tuple[TestClient, FakeBrokerClient],
) -> None:
    client, _ = client_and_broker
    resp = client.post("/api/tasks/no-such-id/skip", params={"token": _TOKEN})
    assert resp.status_code == 404


@pytest_asyncio.fixture
async def pending_task_no_skip(
    session_factory: async_sessionmaker[AsyncSession],
) -> Task:
    task = _task("skp2", Status.PENDING, order_id="ORD-PSKP", offset_secs=0)
    async with session_factory() as session:
        await repo.save_task(session, task)
    return task


def test_skip_400_when_status_not_instruction_ready(
    client_and_broker: tuple[TestClient, FakeBrokerClient],
    pending_task_no_skip: Task,
) -> None:
    client, _ = client_and_broker
    resp = client.post("/api/tasks/skp2/skip", params={"token": _TOKEN})
    assert resp.status_code == 400
    assert "INSTRUCTION_READY" in resp.json()["detail"]
```

- [ ] **Step 3.2: Run — confirm 404 (route does not exist yet)**

Run: `cd backend && uv run pytest tests/api/test_http.py::test_skip_marks_task_skipped tests/api/test_http.py::test_skip_404_when_task_missing tests/api/test_http.py::test_skip_400_when_status_not_instruction_ready -v`
Expected: all three fail. The "missing task" case may coincidentally pass (FastAPI returns 404 for unknown routes too) — focus on the success and 400 cases failing.

- [ ] **Step 3.3: Implement the endpoint**

Edit `backend/app/api/http.py`. Immediately after the existing `confirm_task_endpoint` function (after line 344), add:

```python
    @router.post("/api/tasks/{task_id}/skip", response_model=TaskOut)
    async def skip_task_endpoint(task_id: str) -> TaskOut:
        """Mark an INSTRUCTION_READY task as SKIPPED on user request."""
        async with session_scope(session_factory) as session:
            task = await repo.load_task(session, task_id)
        if task is None:
            raise HTTPException(404, detail="task not found")
        if task.status != Status.INSTRUCTION_READY:
            raise HTTPException(
                400,
                detail=f"task status must be INSTRUCTION_READY for skip, got: {task.status}",
            )
        task.mark_skipped("用户手动取消")
        await bus.publish(Event(Topics.TASK_STATUS_CHANGED, TaskPayload(task)))
        await bus.wait_idle(timeout=3.0)
        async with session_scope(session_factory) as session:
            refreshed = await repo.load_task(session, task_id)
        if refreshed is None:
            raise HTTPException(500, detail="task missing after skip")
        return task_to_out(refreshed)
```

(Imports `Event`, `Topics`, `TaskPayload`, `Status`, `HTTPException`, `TaskOut`, `repo`, `session_scope`, `task_to_out` are already present in this module — same pattern as `confirm_task_endpoint`.)

- [ ] **Step 3.4: Run the three skip tests — all pass**

Run: `cd backend && uv run pytest tests/api/test_http.py -k skip -v`
Expected: all three pass.

- [ ] **Step 3.5: Run the full backend suite**

Run: `cd backend && uv run pytest -q`
Expected: all green.

- [ ] **Step 3.6: Regenerate the OpenAPI dump (frontend type generation depends on it)**

Run:
```bash
cd backend && uv run python ../scripts/dump_openapi.py > ../frontend/openapi.json
cd ../frontend && npm run gen:types
```

Expected: `frontend/openapi.json` is updated to include the new `/api/tasks/{task_id}/skip` route; `frontend/src/api/types.ts` regenerates without TypeScript errors.

> If the project does not auto-regenerate types in CI, this step keeps the typed `request<Task>(...)` call in `api.skipTask` honest. If `npm run gen:types` doesn't exist, inspect `frontend/package.json` scripts — the equivalent may be invoked differently.

- [ ] **Step 3.7: Commit**

```bash
git add backend/app/api/http.py backend/tests/api/test_http.py \
        frontend/openapi.json frontend/src/api/types.ts
git commit -m "$(cat <<'EOF'
feat(api): POST /api/tasks/{id}/skip — manual cancel pre-submit

New endpoint transitions an INSTRUCTION_READY task to SKIPPED with
reject_reason="用户手动取消". Only valid from INSTRUCTION_READY
(returns 400 otherwise, 404 if task missing). Existing /cancel
endpoint (broker order cancellation) is unchanged.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Frontend — `<ConfirmActions>` component, wire into Card

### 4A — `api.skipTask` (TDD)

**Files:**
- Modify: `frontend/src/api/http.ts:108-110` (add method after `confirmTask`)
- Modify: `frontend/src/api/http.test.ts` (append test)

- [ ] **Step 4A.1: Write the failing test**

Append to `frontend/src/api/http.test.ts` (inside the `describe("http", () => {` block, before the closing `});`):

```typescript
  it("uses POST method for skipTask", async () => {
    (global.fetch as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: true,
      json: async () => ({
        id: "msg-1",
        status: "SKIPPED",
        type: "stock",
        message: {},
        instruction: null,
        order_id: null,
        push_events: [],
        stage_timings: {},
        created_at: "",
        updated_at: "",
        reject_reason: "用户手动取消",
      }),
    });
    await api.skipTask("msg-1");
    const call = (global.fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    const [url, init] = call;
    expect(url).toContain("/api/tasks/msg-1/skip");
    expect(init.method).toBe("POST");
  });
```

- [ ] **Step 4A.2: Run — confirm failure**

Run: `cd frontend && npm test -- --run http.test`
Expected: TypeScript compile error or runtime "api.skipTask is not a function".

- [ ] **Step 4A.3: Add `skipTask` to the api object**

Edit `frontend/src/api/http.ts`. After the existing `confirmTask` (lines 108-110), add:

```typescript
  async skipTask(id: string): Promise<Task> {
    return request<Task>(`/api/tasks/${encodeURIComponent(id)}/skip`, { method: "POST" });
  },
```

- [ ] **Step 4A.4: Run http tests — all pass**

Run: `cd frontend && npm test -- --run http.test`
Expected: all pass.

### 4B — `<ConfirmActions>` component (TDD)

**Files:**
- Create: `frontend/src/components/Card/ConfirmActions.tsx`
- Create: `frontend/src/components/Card/ConfirmActions.test.tsx`

- [ ] **Step 4B.1: Write the failing tests**

Create `frontend/src/components/Card/ConfirmActions.test.tsx`:

```typescript
import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { ConfirmActions } from "./ConfirmActions";
import * as httpModule from "../../api/http";
import { useTasksStore } from "../../stores/tasks";

const fakeTaskOut = {
  id: "task-1",
  type: "stock" as const,
  status: "SKIPPED",
  order_id: null,
  stage_timings: {},
  created_at: "2026-04-26T10:00:00Z",
  updated_at: "2026-04-26T10:00:01Z",
  reject_reason: "用户手动取消",
  message: {} as never,
  instruction: null,
  push_events: [],
};

describe("ConfirmActions", () => {
  beforeEach(() => {
    useTasksStore.setState({ tasks: [], pushEventsByTask: {} });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders two icon buttons (confirm + cancel)", () => {
    render(<ConfirmActions taskId="task-1" variant="compact" />);
    expect(screen.getByRole("button", { name: "确认下单" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "取消" })).toBeInTheDocument();
  });

  it("clicking confirm calls api.confirmTask with taskId", async () => {
    const spy = vi.spyOn(httpModule.api, "confirmTask").mockResolvedValue(fakeTaskOut as never);
    render(<ConfirmActions taskId="task-1" variant="compact" />);
    fireEvent.click(screen.getByRole("button", { name: "确认下单" }));
    await waitFor(() => expect(spy).toHaveBeenCalledWith("task-1"));
  });

  it("clicking cancel calls api.skipTask with taskId", async () => {
    const spy = vi.spyOn(httpModule.api, "skipTask").mockResolvedValue(fakeTaskOut as never);
    render(<ConfirmActions taskId="task-1" variant="compact" />);
    fireEvent.click(screen.getByRole("button", { name: "取消" }));
    await waitFor(() => expect(spy).toHaveBeenCalledWith("task-1"));
  });

  it("disables both buttons while a request is in-flight", async () => {
    let resolve!: (v: typeof fakeTaskOut) => void;
    vi.spyOn(httpModule.api, "confirmTask").mockImplementation(
      () => new Promise((r) => { resolve = r as never; }),
    );
    render(<ConfirmActions taskId="task-1" variant="compact" />);
    const confirmBtn = screen.getByRole("button", { name: "确认下单" });
    const cancelBtn = screen.getByRole("button", { name: "取消" });
    fireEvent.click(confirmBtn);
    await waitFor(() => {
      expect(confirmBtn).toBeDisabled();
      expect(cancelBtn).toBeDisabled();
    });
    resolve(fakeTaskOut);
    await waitFor(() => expect(confirmBtn).not.toBeDisabled());
  });

  it("shows error indicator when api call fails", async () => {
    vi.spyOn(httpModule.api, "skipTask").mockRejectedValue(
      new httpModule.HttpError(400, { detail: "wrong status" }, "HTTP 400"),
    );
    const { container } = render(<ConfirmActions taskId="task-1" variant="compact" />);
    fireEvent.click(screen.getByRole("button", { name: "取消" }));
    await waitFor(() => {
      const err = container.querySelector(".ca-err");
      expect(err).toBeInTheDocument();
      expect(err?.getAttribute("title")).toContain("wrong status");
    });
  });

  it("stops click propagation so wrapper handlers do not fire", () => {
    const wrapperClick = vi.fn();
    vi.spyOn(httpModule.api, "skipTask").mockResolvedValue(fakeTaskOut as never);
    render(
      <div onClick={wrapperClick}>
        <ConfirmActions taskId="task-1" variant="compact" />
      </div>,
    );
    fireEvent.click(screen.getByRole("button", { name: "取消" }));
    expect(wrapperClick).not.toHaveBeenCalled();
  });

  it("upserts the returned task into the store on success", async () => {
    vi.spyOn(httpModule.api, "skipTask").mockResolvedValue(fakeTaskOut as never);
    render(<ConfirmActions taskId="task-1" variant="compact" />);
    fireEvent.click(screen.getByRole("button", { name: "取消" }));
    await waitFor(() => {
      const stored = useTasksStore.getState().tasks.find((t) => t.id === "task-1");
      expect(stored).toBeDefined();
      expect(stored?.status).toBe("SKIPPED");
    });
  });
});
```

> Note: the tasks store uses `tasks: TaskSummary[]` (array, sorted by `created_at` desc) keyed nowhere — find by `.find(t => t.id === ...)`. Verified against `frontend/src/stores/tasks.ts` at plan-write time.

- [ ] **Step 4B.2: Run — confirm failure**

Run: `cd frontend && npm test -- --run ConfirmActions`
Expected: tests fail because `ConfirmActions.tsx` does not exist.

- [ ] **Step 4B.3: Implement `<ConfirmActions>`**

Create `frontend/src/components/Card/ConfirmActions.tsx`:

```tsx
import { useState } from "react";
import type { SyntheticEvent } from "react";
import { api, HttpError } from "../../api/http";
import { useTasksStore } from "../../stores/tasks";

export interface ConfirmActionsProps {
  taskId: string;
  variant: "compact" | "expanded";
}

export function ConfirmActions({ taskId, variant }: ConfirmActionsProps) {
  const [busy, setBusy] = useState<"confirm" | "skip" | null>(null);
  const [error, setError] = useState<string | null>(null);

  const run = async (kind: "confirm" | "skip") => {
    setBusy(kind);
    setError(null);
    try {
      const updated = kind === "confirm"
        ? await api.confirmTask(taskId)
        : await api.skipTask(taskId);
      useTasksStore.getState().upsertTask(updated);
    } catch (e) {
      const msg = e instanceof HttpError
        ? (typeof e.body === "object" && e.body && "detail" in e.body
            ? String((e.body as { detail: unknown }).detail)
            : e.message)
        : (e instanceof Error ? e.message : String(e));
      setError(msg);
    } finally {
      setBusy(null);
    }
  };

  const stop = (e: SyntheticEvent) => e.stopPropagation();

  return (
    <span
      className={`confirm-actions ${variant}`}
      onClick={stop}
      onKeyDown={stop}
    >
      <button
        type="button"
        className="ca-btn ca-confirm"
        title="确认下单"
        aria-label="确认下单"
        disabled={busy !== null}
        onClick={() => run("confirm")}
      >
        {busy === "confirm" ? <span className="ca-spinner" /> : (
          <svg viewBox="0 0 16 16" fill="none" stroke="currentColor"
               strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round">
            <polyline points="3 8 7 12 13 4" />
          </svg>
        )}
      </button>
      <button
        type="button"
        className="ca-btn ca-cancel"
        title="取消"
        aria-label="取消"
        disabled={busy !== null}
        onClick={() => run("skip")}
      >
        {busy === "skip" ? <span className="ca-spinner" /> : (
          <svg viewBox="0 0 16 16" fill="none" stroke="currentColor"
               strokeWidth="2.4" strokeLinecap="round">
            <line x1="4" y1="4" x2="12" y2="12" />
            <line x1="12" y1="4" x2="4" y2="12" />
          </svg>
        )}
      </button>
      {error && <span className="ca-err" title={error}>!</span>}
    </span>
  );
}
```

- [ ] **Step 4B.4: Run — all ConfirmActions tests pass**

Run: `cd frontend && npm test -- --run ConfirmActions`
Expected: all tests pass.

### 4C — Wire `<ConfirmActions>` into `CardCompact`

**Files:**
- Modify: `frontend/src/components/Card/CardCompact.tsx`
- Modify: `frontend/src/components/Card/CardCompact.test.tsx`
- Modify: `frontend/src/components/Card/Card.tsx`

- [ ] **Step 4C.1: Add a failing test that requires `autoTrade` prop on `CardCompact`**

Append to `frontend/src/components/Card/CardCompact.test.tsx` (inside the `describe` block, before closing `});`):

```typescript
  const readyTask: TaskSummary = {
    ...stockTask,
    status: "INSTRUCTION_READY",
    order_id: null,
    reject_reason: "auto_trade disabled in config; awaiting manual confirmation",
  };

  it("renders ConfirmActions instead of status pill when autoTrade=false and INSTRUCTION_READY", () => {
    const { container } = render(
      <CardCompact task={readyTask} autoTrade={false} onExpand={vi.fn()} />
    );
    expect(container.querySelector(".confirm-actions.compact")).toBeInTheDocument();
    expect(container.querySelector(".card-status")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "确认下单" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "取消" })).toBeInTheDocument();
  });

  it("renders status pill when autoTrade=true even if INSTRUCTION_READY", () => {
    const { container } = render(
      <CardCompact task={readyTask} autoTrade={true} onExpand={vi.fn()} />
    );
    expect(container.querySelector(".confirm-actions")).not.toBeInTheDocument();
    expect(container.querySelector(".card-status")).toBeInTheDocument();
  });

  it("renders status pill when status is not INSTRUCTION_READY (autoTrade=false)", () => {
    const { container } = render(
      <CardCompact task={stockTask} autoTrade={false} onExpand={vi.fn()} />
    );
    expect(container.querySelector(".confirm-actions")).not.toBeInTheDocument();
    expect(container.querySelector(".card-status")).toBeInTheDocument();
  });

  it("clicking confirm/cancel buttons does not bubble to expand", () => {
    const onExpand = vi.fn();
    vi.spyOn(httpModule.api, "skipTask").mockResolvedValue(stockTask as never);
    render(<CardCompact task={readyTask} autoTrade={false} onExpand={onExpand} />);
    fireEvent.click(screen.getByRole("button", { name: "取消" }));
    expect(onExpand).not.toHaveBeenCalled();
  });
```

Also add the imports the new tests need at the top of `CardCompact.test.tsx`:

```typescript
import { fireEvent } from "@testing-library/react";
import * as httpModule from "../../api/http";
```

(Adjust to merge with the existing `import { render, screen } from "@testing-library/react";` — final form: `import { render, screen, fireEvent } from "@testing-library/react";`.)

You will also need to update **every existing call site** of `<CardCompact>` in this test file to pass `autoTrade={true}` (or `false`) — TypeScript will fail the build otherwise. Find each `render(<CardCompact task={...} onExpand={...} />)` and add `autoTrade={true}`.

- [ ] **Step 4C.2: Run — confirm TS errors / failures**

Run: `cd frontend && npm test -- --run CardCompact`
Expected: TypeScript errors in test file (existing renders missing `autoTrade`), or runtime test failures for the new cases.

- [ ] **Step 4C.3: Update `<CardCompact>` to accept `autoTrade` and switch column 7**

Edit `frontend/src/components/Card/CardCompact.tsx`. Update imports:

```tsx
import { ConfirmActions } from "./ConfirmActions";
```

Update the props interface and signature:

```tsx
export interface CardCompactProps {
  task: TaskSummary;
  autoTrade: boolean;
  onExpand: () => void;
}

export function CardCompact({ task, autoTrade, onExpand }: CardCompactProps) {
```

Add the manual-confirm decision near the top of the function body:

```tsx
  const showConfirmActions =
    !autoTrade && status === "INSTRUCTION_READY" && instruction != null;
```

Replace the existing `<StatusPill status={status} />` (currently around line 89) with:

```tsx
  {showConfirmActions
    ? <ConfirmActions taskId={task.id} variant="compact" />
    : <StatusPill status={status} />
  }
```

The grid template (`grid-template-columns: 44px ... 104px 20px`) does not change — `<ConfirmActions>` is sized to fit 104px (24+24+4 gap = 52px, comfortably inside; the `.confirm-actions.compact { justify-content: center }` rule centers it).

- [ ] **Step 4C.4: Update `<Card>` to forward `autoTrade` to `<CardCompact>`**

Edit `frontend/src/components/Card/Card.tsx:26`:

```tsx
  return <CardCompact task={task} autoTrade={autoTrade} onExpand={() => setExpanded(true)} />;
```

- [ ] **Step 4C.5: Run all CardCompact tests**

Run: `cd frontend && npm test -- --run CardCompact`
Expected: all green.

### 4D — Replace `manual-confirm-row` in `CardExpanded`

**Files:**
- Modify: `frontend/src/components/Card/CardExpanded.tsx:1-3, 22-23, 61-78, 159-171`
- Modify: `frontend/src/components/Card/CardExpanded.test.tsx:173-182`

- [ ] **Step 4D.1: Update the existing CardExpanded manual-confirm test**

Edit `frontend/src/components/Card/CardExpanded.test.tsx:173-182`. Replace the existing `it("shows manual confirm button when autoTrade off and instruction ready", ...)` with two updated tests:

```typescript
  it("shows ConfirmActions when autoTrade off and instruction ready", () => {
    const readyTask: TaskSummary = {
      ...task,
      status: "INSTRUCTION_READY",
      order_id: null,
      reject_reason: "awaiting manual confirmation",
    };
    const { container } = render(
      <CardExpanded task={readyTask} pushEvents={[]} autoTrade={false} onCollapse={vi.fn()} />
    );
    expect(container.querySelector(".confirm-actions.expanded")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "确认下单" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "取消" })).toBeInTheDocument();
  });

  it("hides ConfirmActions when autoTrade is on", () => {
    const readyTask: TaskSummary = {
      ...task,
      status: "INSTRUCTION_READY",
      order_id: null,
    };
    const { container } = render(
      <CardExpanded task={readyTask} pushEvents={[]} autoTrade={true} onCollapse={vi.fn()} />
    );
    expect(container.querySelector(".confirm-actions")).not.toBeInTheDocument();
  });
```

- [ ] **Step 4D.2: Run — confirm failure**

Run: `cd frontend && npm test -- --run CardExpanded`
Expected: tests fail because the old `.manual-confirm-btn` is still what gets rendered, not `.confirm-actions`.

- [ ] **Step 4D.3: Strip the old confirm code and wire in `<ConfirmActions>`**

Edit `frontend/src/components/Card/CardExpanded.tsx`:

1. Remove the unused imports at the top: drop `useState`, `api`, `HttpError`, `useTasksStore`. Keep them only if other code in the file uses them; if not, remove. Updated import header:

```tsx
import type { TaskSummary, PushEvent } from "../../api/domain-types";
import { TypeBadge } from "../common/TypeBadge";
import { StatusPill } from "../common/StatusPill";
import { OrderSubmit } from "./OrderSubmit";
import { PushChain } from "./PushChain";
import { PushDetail } from "./PushDetail";
import { ConfirmActions } from "./ConfirmActions";
import { formatTitle, fmtElapsed, elapsedMs } from "./cardHelpers";
import "./Card.css";

import { useState } from "react";
```

(Keep `useState` only if `pushExpanded` still uses it — it does, line 21.)

2. Delete the `confirming/confirmError` state (lines 22-23) and the `handleConfirm` function (lines 61-78).

3. Replace the `manual-confirm-row` block (lines 159-171):

```tsx
{canManualConfirm && (
  <div className="confirm-actions-row">
    <ConfirmActions taskId={task.id} variant="expanded" />
    <span className="confirm-hint">auto_trade 已关闭 · 待人工确认</span>
  </div>
)}
```

`canManualConfirm` (line 42) keeps its current definition: `autoTrade === false && status === "INSTRUCTION_READY" && hasInstruction`.

- [ ] **Step 4D.4: Run all CardExpanded tests**

Run: `cd frontend && npm test -- --run CardExpanded`
Expected: all green. The two new tests pass; the `it("renders inline parse info on 解析指令 stage")` test still passes because the parse-inline block above the confirm row is untouched.

### 4E — CSS

**File:** `frontend/src/components/Card/Card.css`

- [ ] **Step 4E.1: Remove the old `.manual-confirm-*` rules**

Edit `frontend/src/components/Card/Card.css:327-351`. Delete all of:

```css
.manual-confirm-row { ... }
.manual-confirm-btn { ... }
.manual-confirm-btn:disabled { ... }
.manual-confirm-err { ... }
```

- [ ] **Step 4E.2: Add the new rules**

Append to `frontend/src/components/Card/Card.css`:

```css
/* ===== Confirm / Skip icon buttons (auto_trade=off manual gate) ===== */
.confirm-actions {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}
.confirm-actions.compact {
  justify-content: center;
}

.ca-btn {
  width: 24px;
  height: 24px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border: 1px solid var(--line-strong);
  border-radius: 4px;
  background: var(--bg-1);
  cursor: pointer;
  padding: 0;
  transition: border-color 120ms, background 120ms, color 120ms;
}
.ca-btn svg { width: 12px; height: 12px; }
.ca-btn:disabled { opacity: 0.5; cursor: default; }

.ca-confirm { color: var(--ok); }
.ca-confirm:hover:not(:disabled) {
  border-color: var(--ok);
  background: rgba(61, 214, 140, 0.10);
}
.ca-cancel { color: var(--err); }
.ca-cancel:hover:not(:disabled) {
  border-color: var(--err);
  background: rgba(239, 91, 91, 0.08);
}

.ca-spinner {
  width: 10px;
  height: 10px;
  border: 1.5px solid currentColor;
  border-top-color: transparent;
  border-radius: 50%;
  animation: ca-spin 0.7s linear infinite;
}
@keyframes ca-spin { to { transform: rotate(360deg); } }

.ca-err {
  color: var(--err);
  font-family: var(--font-mono);
  font-size: 11px;
  cursor: help;
  margin-left: 2px;
}

.confirm-actions-row {
  margin-top: 8px;
  display: flex;
  align-items: center;
  gap: 12px;
}
.confirm-hint {
  color: var(--fg-3);
  font-size: 11px;
}
```

### 4F — `.gitignore` and verification

- [ ] **Step 4F.1: Add `.superpowers/` to `.gitignore`**

Edit `.gitignore` (project root). Add a new line:

```
.superpowers/
```

(Adds the brainstorm-companion artifact directory to git ignore. `.claude/` is already user-level and may already be ignored — leave it alone unless verification shows otherwise.)

- [ ] **Step 4F.2: Run all frontend tests**

Run: `cd frontend && npm test -- --run`
Expected: all green.

- [ ] **Step 4F.3: Type-check + build**

Run: `cd frontend && npm run build`
Expected: TypeScript compiles without errors; Vite produces a clean bundle.

- [ ] **Step 4F.4: Run the full backend suite once more (sanity)**

Run: `cd backend && uv run pytest -q`
Expected: all green.

- [ ] **Step 4F.5: Manual smoke test**

Run: `make dev` from project root.

Manual checks (only mark complete if observed in the running app):

1. Open the dashboard. Confirm the topbar shows `auto_trade: OFF` (toggle if needed via the existing topbar control).
2. Trigger a complete stock signal (paste through the test input or live page) like `TSLL 26.5 加一半` against a watched ticker. Expect:
   - Compact card row: column 7 shows two icon buttons (✓ green outline / ✗ red outline) instead of a status pill.
   - Click ✓ → spinner appears → buttons disappear → status pill shows `PENDING` (or `FILLED`).
3. Trigger another complete signal. Click ✗ → status becomes `SKIPPED`, details column shows `用户手动取消`.
4. Trigger a stock signal *missing quantity* (e.g. `TSLL 26.5 买` with no position-size keyword). Expect:
   - Card lands directly in `SKIPPED` with `参数不齐: 数量` in details.
   - No confirm/cancel buttons appear.
5. Repeat (2)-(4) for an option signal (e.g. complete: `NVDA 135C 本周 2.15 买 一张`; missing strike: edit to omit `135C`).
6. Toggle `auto_trade` to ON, paste a complete signal — confirm buttons do NOT appear (status pill shows `PENDING` directly).

Note: if the input is hard to control (live whop feed), use the existing test fixtures or the parser CLI (`uv run python -c "..."`) to drive the message bus, or temporarily insert tasks via DB.

- [ ] **Step 4F.6: Commit**

```bash
git add frontend/src/api/http.ts frontend/src/api/http.test.ts \
        frontend/src/components/Card/ConfirmActions.tsx \
        frontend/src/components/Card/ConfirmActions.test.tsx \
        frontend/src/components/Card/Card.tsx \
        frontend/src/components/Card/CardCompact.tsx \
        frontend/src/components/Card/CardCompact.test.tsx \
        frontend/src/components/Card/CardExpanded.tsx \
        frontend/src/components/Card/CardExpanded.test.tsx \
        frontend/src/components/Card/Card.css \
        .gitignore
git commit -m "$(cat <<'EOF'
feat(card): confirm/skip icon buttons with web style

ConfirmActions component renders two 26px square SVG icon buttons
(green check / red X). Wired into CardCompact (replaces status pill
in column 7 when auto_trade=off and INSTRUCTION_READY) and
CardExpanded (replaces the old single-button manual-confirm row).
Self-contained loading + error state; clicks stop propagation so the
compact row's expand handler does not fire.

Adds api.skipTask hitting POST /api/tasks/{id}/skip; removes legacy
.manual-confirm-* CSS; ignores .superpowers/ brainstorm artifacts.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Final verification

- [ ] **Step F.1: Confirm 4 commits exist on the branch**

Run: `git log --oneline refactor-v2 -10`
Expected: top 4 commits are
```
chore(domain): allow PARSING → SKIPPED transition
feat(parser): validate required fields before INSTRUCTION_READY
feat(api): POST /api/tasks/{id}/skip — manual cancel pre-submit
feat(card): confirm/skip icon buttons with web style
```
(in chronological order — `git log` shows newest first, so reversed in the listing.)

- [ ] **Step F.2: Confirm full test sweep**

Run:
```bash
cd backend && uv run pytest -q
cd ../frontend && npm test -- --run && npm run build
```
Expected: both green; build artifact produced.

- [ ] **Step F.3: Diff review**

Run: `git diff main..HEAD -- backend/app frontend/src/components/Card frontend/src/api`
Expected: all changes match the spec sections 5 and 6. No stray formatting changes.
