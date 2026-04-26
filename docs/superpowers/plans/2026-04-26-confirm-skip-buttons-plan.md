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
| `backend/app/domain/status.py` | State-machine transition table | Modify (add `PARSING→SKIPPED`) — done |
| `backend/app/broker/validation.py` | Pure function: required-field check on `Instruction` (parser-output level) | **Create** |
| `backend/app/broker/trader.py` | Run `validate_for_submission` as the FIRST step of `_handle_instruction_ready`, before the auto_trade decision | Modify |
| `backend/app/api/http.py` | `POST /api/tasks/{id}/skip` endpoint | Modify (add route) |
| `backend/tests/domain/test_status.py` | State-machine cases | Modify (extend parametrize) — done |
| `backend/tests/broker/test_validation.py` | Pure-function tests | **Create** |
| `backend/tests/broker/test_trader.py` | Trader end-to-end behavior | Modify (add 3 cases) |
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

1. **chore(domain): allow PARSING → SKIPPED transition** — Task 1 ✅ done (`30007c8`)
2. **feat(broker): validate required fields before order submission** — Task 2 (validation in trader, before auto_trade)
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

## Task 2: Order-submission parameter completeness validation (in trader)

> **Design note (2026-04-26 revision):** This validation runs as the FIRST step of `trader._handle_instruction_ready`, **before the auto_trade gate**. It checks parser-level fields only — `quantity` is intentionally excluded for option (parser never produces it; page_settings is authoritative) and relaxed to `quantity OR position_size` for stock. See spec §5.2-§5.3.

**Files:**
- Create: `backend/app/broker/validation.py`
- Create: `backend/tests/broker/test_validation.py`
- Modify: `backend/app/broker/trader.py` (insert validation gate at top of `_handle_instruction_ready`)
- Modify: `backend/tests/broker/test_trader.py` (append 3 cases)

### 2A — Pure validation function (TDD)

- [ ] **Step 2A.1: Write the failing tests for `validate_for_submission`**

Create `backend/tests/broker/test_validation.py`:

```python
"""Tests for app.broker.validation.validate_for_submission."""
from __future__ import annotations

from datetime import date

from app.domain.instruction import (
    InstructionType,
    OptionInstruction,
    StockInstruction,
)
from app.broker.validation import validate_for_submission


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

def test_stock_complete_with_quantity_returns_none():
    assert validate_for_submission(_stock()) is None


def test_stock_complete_with_position_size_returns_none():
    """Stock without numeric quantity but with position_size keyword is OK —
    trader resolves the concrete qty from page_settings later."""
    inst = _stock(quantity=None, position_size="常规仓的一半")
    assert validate_for_submission(inst) is None


def test_option_complete_returns_none():
    assert validate_for_submission(_option()) is None


def test_option_complete_without_quantity_returns_none():
    """Option qty is always derived from page_settings; parser-stage qty=None
    is the normal case and must NOT be flagged."""
    assert validate_for_submission(_option(quantity=None)) is None


def test_stock_with_price_range_only_returns_none():
    assert validate_for_submission(_stock(price=None, price_range=(26.0, 27.0))) is None


# ---------- stock missing fields ----------

def test_stock_missing_quantity_and_position_size():
    """Neither quantity nor position_size — parser produced no qty intent
    at all, which fails the gate."""
    reason = validate_for_submission(_stock(quantity=None, position_size=None))
    assert reason is not None
    assert "数量" in reason


def test_stock_zero_quantity_and_no_position_size():
    reason = validate_for_submission(_stock(quantity=0, position_size=None))
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

def test_option_zero_strike():
    reason = validate_for_submission(_option(strike=0))
    assert reason is not None
    assert "行权价" in reason


def test_option_no_expiry_falsy():
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


def test_option_close_instruction_type_rejected():
    reason = validate_for_submission(_option(instruction_type=InstructionType.CLOSE))
    assert reason is not None
    assert "BUY" in reason and "SELL" in reason


# ---------- error string format ----------

def test_reason_starts_with_zh_prefix():
    reason = validate_for_submission(_stock(quantity=None, position_size=None))
    assert reason is not None
    assert reason.startswith("参数不齐: ")


def test_reason_lists_multiple_missing_fields():
    inst = _stock(
        quantity=None,
        position_size=None,
        instruction_type=InstructionType.CLOSE,
    )
    reason = validate_for_submission(inst)
    assert reason is not None
    assert "数量" in reason
    assert "BUY" in reason and "SELL" in reason
    assert "、" in reason
```

> Note: `StockInstruction.__post_init__` requires `ticker`, and `Instruction.__post_init__` requires `price` or `price_range`. Tests that would violate those constructor invariants cannot be constructed normally; the validation function still defends against them (cheap belt-and-braces) but we don't exercise dead paths here.

- [ ] **Step 2A.2: Run — confirm import error**

Run: `cd backend && uv run pytest tests/broker/test_validation.py -v`
Expected: `ModuleNotFoundError` because `app/broker/validation.py` doesn't exist yet.

- [ ] **Step 2A.3: Implement `validate_for_submission`**

Create `backend/app/broker/validation.py`:

```python
"""Pre-submission parameter completeness gate.

Runs as the FIRST step of trader._handle_instruction_ready, before the
auto_trade decision. Returns a Chinese reason string when *inst* lacks
the parser-level fields needed to make a sensible order, or None when
the instruction is OK to proceed.

This gate intentionally does NOT check `quantity`:
  - Stock: parser typically only emits position_size; concrete qty is
    resolved by trader using page_settings.tickers[ticker].trade_quantity.
  - Option: parser never emits quantity; it is fully derived from
    page_settings (option_buy_quantity / option_total_price_limit).

Stock instead requires either explicit `quantity > 0` OR a non-empty
`position_size` — evidence that the user expressed *some* quantity
intent. Option only requires the per-option-contract specifics; qty
resolution stays the trader's job.
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

    if inst.instruction_type not in (InstructionType.BUY, InstructionType.SELL):
        missing.append(f"方向(BUY/SELL,当前: {inst.instruction_type})")
    if inst.price is None and not inst.price_range:
        missing.append("价格")

    if isinstance(inst, StockInstruction):
        if not inst.ticker:
            missing.append("股票名")
        has_qty = inst.quantity is not None and inst.quantity > 0
        has_size = bool(inst.position_size)
        if not has_qty and not has_size:
            missing.append("数量(qty 或 position_size)")
    elif isinstance(inst, OptionInstruction):
        if not inst.ticker:
            missing.append("股票")
        if not inst.strike or inst.strike <= 0:
            missing.append("行权价")
        if inst.option_type not in ("CALL", "PUT"):
            missing.append("CALL/PUT")
        if not inst.expiry:
            missing.append("到期日")
        # NOTE: no quantity check — option qty is derived from page_settings.

    if missing:
        return "参数不齐: " + "、".join(missing)
    return None
```

- [ ] **Step 2A.4: Run validation tests — all green**

Run: `cd backend && uv run pytest tests/broker/test_validation.py -v`
Expected: all 14 cases pass.

### 2B — Wire validation into trader (FIRST step, before auto_trade)

- [ ] **Step 2B.1: Write the failing trader tests**

The file already has helpers `_stock_task(symbol, instruction_type)`, `_option_task(...)`, and `_config(**overrides)` plus `FakeBrokerClient`. Use them directly. Append to `backend/tests/broker/test_trader.py`:

```python
# ---------------------------------------------------------------------------
# Pre-submission validation gate — Task 2 (revised design)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_trader_skips_when_instruction_invalid_side() -> None:
    """A task whose instruction has CLOSE side fails the validation gate
    before the auto_trade check, regardless of auto_trade."""
    bus = EventBus()
    fake_broker = FakeBrokerClient()
    register_trader(bus, fake_broker, _config(auto_trade=True))

    task = _stock_task(instruction_type=InstructionType.CLOSE)
    await bus.publish(Event(Topics.TASK_INSTRUCTION_READY, TaskPayload(task)))
    await bus.wait_idle(timeout=2.0)

    assert task.status == Status.SKIPPED
    assert task.reject_reason is not None
    assert "参数不齐" in task.reject_reason
    assert "BUY" in task.reject_reason and "SELL" in task.reject_reason
    # Crucially: the broker was never called
    assert fake_broker.submitted_stock_orders == []


@pytest.mark.asyncio
async def test_trader_holds_for_manual_when_valid_and_auto_trade_off() -> None:
    """Valid instruction + auto_trade=false: validation gate passes, then
    the auto_trade gate keeps the task at INSTRUCTION_READY with reject_reason
    set, ready for manual confirmation. The broker is NOT called."""
    bus = EventBus()
    fake_broker = FakeBrokerClient()
    register_trader(bus, fake_broker, _config(auto_trade=False))

    task = _stock_task()  # BUY, complete instruction
    await bus.publish(Event(Topics.TASK_INSTRUCTION_READY, TaskPayload(task)))
    await bus.wait_idle(timeout=2.0)

    assert task.status == Status.INSTRUCTION_READY  # held for manual
    assert task.reject_reason is not None
    assert "auto_trade" in task.reject_reason
    assert fake_broker.submitted_stock_orders == []


@pytest.mark.asyncio
async def test_trader_proceeds_when_valid_and_auto_trade_on() -> None:
    """Valid instruction + auto_trade=true: both gates pass, broker called."""
    bus = EventBus()
    fake_broker = FakeBrokerClient()
    register_trader(bus, fake_broker, _config(auto_trade=True))

    task = _stock_task()  # BUY, complete instruction
    await bus.publish(Event(Topics.TASK_INSTRUCTION_READY, TaskPayload(task)))
    await bus.wait_idle(timeout=2.0)

    # Status advanced past INSTRUCTION_READY
    assert task.status in (Status.PENDING, Status.SUBMITTING, Status.FILLED)
    assert len(fake_broker.submitted_stock_orders) == 1
```

> The exact attribute name on `FakeBrokerClient` (`submitted_stock_orders` vs `submitted_orders` etc.) may differ — open `backend/tests/broker/_fakes.py` and use the actual name. Adjust the assertions accordingly. The intent is "broker recorded a submission" or "broker recorded zero submissions". Also: `_stock_task` already calls `attach_instruction`, so the task arrives at INSTRUCTION_READY exactly as it would in production.

- [ ] **Step 2B.2: Run — confirm failures**

Run: `cd backend && uv run pytest tests/broker/test_trader.py -k "missing_side or manual or auto_trade_on" -v`
Expected: `test_trader_skips_when_instruction_missing_side` fails (currently the trader's existing CLOSE check uses different reason text); the other two might fail or coincidentally pass depending on existing behavior. Key signal: validation gate not yet wired.

- [ ] **Step 2B.3: Implement the validation gate in `trader.py`**

Edit `backend/app/broker/trader.py`. Add import near the top (next to other `app.broker.*` imports):

```python
from app.broker.validation import validate_for_submission
```

Then in `_handle_instruction_ready`, replace the existing top of the function:

```python
async def _handle_instruction_ready(event: Event) -> None:
    payload = event.payload
    if not isinstance(payload, TaskPayload):
        return
    task: Task = payload.task
    inst: Instruction | None = task.instruction
    if inst is None:
        return

    # ---- Top-level validation ----
    auto_trade_enabled = auto_trade_getter() if auto_trade_getter is not None else config.auto_trade
    if not auto_trade_enabled:
        # Keep task at INSTRUCTION_READY so the UI can trigger manual confirmation.
        task.reject_reason = "auto_trade disabled in config; awaiting manual confirmation"
        await bus.publish(Event(Topics.TASK_STATUS_CHANGED, TaskPayload(task)))
        return
    if not getattr(inst, "symbol", None):
        await _publish_skip(task, "instruction missing symbol")
        return
    if inst.instruction_type not in (InstructionType.BUY, InstructionType.SELL):
        await _publish_skip(task, f"unsupported instruction type: {inst.instruction_type}")
        return
```

with:

```python
async def _handle_instruction_ready(event: Event) -> None:
    payload = event.payload
    if not isinstance(payload, TaskPayload):
        return
    task: Task = payload.task
    inst: Instruction | None = task.instruction
    if inst is None:
        return

    # ① Parameter completeness gate — runs before auto_trade so incomplete
    # tasks never reach the manual-confirmation UI.
    reason = validate_for_submission(inst)
    if reason is not None:
        await _publish_skip(task, reason)
        return

    # ② auto_trade gate — manual-confirm UI only appears for tasks that
    # passed gate ①, which guarantees the parser-level fields are present.
    auto_trade_enabled = auto_trade_getter() if auto_trade_getter is not None else config.auto_trade
    if not auto_trade_enabled:
        task.reject_reason = "auto_trade disabled in config; awaiting manual confirmation"
        await bus.publish(Event(Topics.TASK_STATUS_CHANGED, TaskPayload(task)))
        return

    # ③ Defensive (now unreachable when gate ① is honored, but kept as
    # belt-and-braces for non-validated callers in tests).
    if not getattr(inst, "symbol", None):
        await _publish_skip(task, "instruction missing symbol")
        return
    if inst.instruction_type not in (InstructionType.BUY, InstructionType.SELL):
        await _publish_skip(task, f"unsupported instruction type: {inst.instruction_type}")
        return
```

- [ ] **Step 2B.4: Run new trader tests — all pass**

Run: `cd backend && uv run pytest tests/broker/test_trader.py -k "missing_side or manual or auto_trade_on" -v`
Expected: all three pass.

- [ ] **Step 2B.5: Run full broker tests**

Run: `cd backend && uv run pytest tests/broker -v`
Expected: all green. If pre-existing trader tests broke (e.g. they construct a task with `instruction_type=CLOSE` expecting a specific skip reason), update those expectations to the new `"参数不齐: 方向…"` reason — that *is* the new correct behavior.

- [ ] **Step 2B.6: Run the full backend suite**

Run: `cd backend && uv run pytest -q`
Expected: all green. If `tests/integration/test_acceptance.py` builds end-to-end fixtures with a CLOSE instruction or some other invalid case, update those expectations.

- [ ] **Step 2B.7: Commit**

```bash
git add backend/app/broker/validation.py backend/app/broker/trader.py \
        backend/tests/broker/test_validation.py backend/tests/broker/test_trader.py
# also include any pre-existing test fixture updates
git status --short  # verify only intended files
git commit -m "$(cat <<'EOF'
feat(broker): validate required fields before order submission

Trader now runs validate_for_submission as the FIRST step of
_handle_instruction_ready, before the auto_trade gate. Stock requires
ticker / BUY-or-SELL / price / (quantity OR position_size); option
requires ticker / BUY-or-SELL / price / strike / CALL-or-PUT / expiry.
Option quantity is intentionally not checked — it's resolved from
page_settings later. Incomplete instructions are SKIPPED with a
Chinese reject_reason, never showing manual-confirm buttons.

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
