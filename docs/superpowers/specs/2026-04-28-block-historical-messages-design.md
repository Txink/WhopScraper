# Block Historical Messages — Design

**Date**: 2026-04-28
**Status**: Spec, awaiting user review.
**Branch**: refactor-v2

## 1. Background & Motivation

Today the per-page setting `block_non_today_messages` SKIPs ordering when a
message's UTC posted-date differs from the server's UTC today. The user
asked for a finer-grained variant: when a listener (re)starts and pulls
messages out of the DOM, those that were *already there* before the
listener came up should be parsed-and-stored but never ordered. This
covers two real situations:

- "I just clicked 重启 — don't trade the back-history that's about to
  flood the pipeline."
- "I started monitoring at 13:00; the morning's posts are still in the
  DOM and shouldn't fire orders even though they are 'today'."

The decided semantics: **historical = `message.posted_at < listener.started_at`**.
This subsumes "non-today" (everything before today is also before today's
boot) while also covering same-day-before-boot cases that the current
check misses.

The decision is to **delete `block_non_today_messages` entirely (field,
schema, gate, tests, UI section) and add a fresh `block_historical_messages`
field with the new semantics**. No reuse, no rename-with-fallback. The
two settings answer different questions and a clean delete + add keeps
the codebase honest.

## 2. User-Visible Change

### Removed

- The `PageSettingsModal` section "禁止下单非当天消息（仅解析指令，不发送订单）"
  (lines around 146-158) and its associated state.
- The trader gate ① b that compares posted-date to today.

### Added

A new section in the same place:

- **Label**: `禁止下单历史消息（消息发布时间早于本次监听启动时间）`
- **Hint**: `消息 posted_at < listener.started_at → 任务标记 SKIPPED（仅解析入库，不发送订单）。比"按当天/非当天"更细：当天但启动前发布的消息也会被拦。`

Saving the page settings takes effect immediately for messages flowing
through the trader; no listener restart is required (the marker is
already on the task by the time trader runs).

**Applies to both stock and option pages.** The setting lives in the
common `PageSettings` block of the modal (not in the option-only
section), and the trader gate is symmetric across `StockInstruction`
and `OptionInstruction`.

### Behavioral compatibility note

Two breaking changes to surface in `CHANGELOG.md`:

1. The `block_non_today_messages` API field and `whop_pages.json` key are
   removed. Any user previously relying on the toggle will lose the
   setting silently (default of new field is `false`); they need to
   re-enable `block_historical_messages` in the UI.
2. Semantics tighten: same-day-before-boot messages are now also
   blocked when the new toggle is on.

## 3. Architecture

```
WhopListener._scan_once
    │
    │ for each new msg in DOM:
    │     is_historical = (
    │         msg.posted_at is not None
    │         and self._started_at is not None
    │         and msg.posted_at.astimezone(UTC) < self._started_at
    │     )
    │     bus.publish(MessagePayload(message=msg, is_historical=is_historical))
    │
    ▼
message handler (creates Task)
    │
    │ Task.is_historical = payload.is_historical
    │
    ▼
storage (TaskRow.is_historical column persisted)
    │
    ▼
trader._process_task
    │
    │ gate ① b (replaces old non-today gate at the same position):
    │   if page_settings.block_historical_messages and task.is_historical:
    │       _publish_skip(task, "历史消息（posted=…）"); return
    │
    ▼
... whitelist / completeness / auto_trade / submit ...
```

### Why mark on the Task (not look up at trader time)

Listeners can be restarted between message capture and trader processing.
If the trader queried the registry for `listener.started_at` lazily, a
restart would mutate the cutoff and reclassify already-captured messages.
Tagging at capture time freezes the verdict.

### Why delete-and-add (not rename-with-fallback)

A backward-compat read in `page_settings_from_dict` would silently
preserve a previously-enabled setting under the new tightened semantics
(same-day-before-boot blocking activates). That is a footgun for users
who consciously enabled "non-today" and didn't ask for the broader
behavior. A clean delete forces them to re-opt-in to the new semantics
through the UI, which is the safer story.

## 4. Detailed Changes

### 4.1 Backend — domain & schema

**`backend/app/whop/page_settings.py`**

- Remove `block_non_today_messages` from `PageSettings` (the field, the
  comment line 24, and every reference in `DEFAULT_STOCK_SETTINGS`,
  `DEFAULT_OPTION_SETTINGS`, `default_settings_for`,
  `page_settings_to_dict`, `page_settings_from_dict`).
- Add `block_historical_messages: bool = False` to `PageSettings` with a
  comment: `# 拦截下单历史消息（posted_at < listener.started_at），仅解析不下单`.
- Wire it through the same five touchpoints (defaults, dict to/from).
- `page_settings_from_dict` reads only the new key:
  `bool(d.get("block_historical_messages", base.block_historical_messages))`.
  Legacy `block_non_today_messages` key in existing JSON is silently
  ignored on load and dropped on next save.

**`backend/app/api/schemas.py`**

- Remove `block_non_today_messages` from `WhopPageSettingsOut` and
  `WhopPageSettingsPatch`.
- Add `block_historical_messages: bool` (Out) and `bool | None = None`
  (Patch).
- `whop_page_to_out` (line 449): replace the field reference.

**`backend/app/api/http.py`**

- Lines 526 / 551 / 552: remove the old field, add the new one in the
  same shape (read path + patch dict assembly).

### 4.2 Backend — listener

**`backend/app/whop/listener.py`**

- `_scan_once`: compute `is_historical` per the formula above; pass it
  via `MessagePayload(message=tagged, is_historical=is_historical)`.
- No new constructor parameter; no change to `start()`,
  `_first_scan_done`, `_prime_*`, `restart_page`. The "first scan" state
  machine is **not needed** because the historical check is per-message
  based on timestamps.

**Edge cases inside `_scan_once`**:

- `msg.posted_at is None` (parser failed / extractor returned no time)
  → `is_historical = False`. We default to "treat as live" so a parsing
  miss doesn't silently swallow orders.
- `self._started_at is None` (impossible after `start()` completes,
  defensive) → `is_historical = False`.
- Timezone: `posted_at` may not be UTC; compare in UTC explicitly.

### 4.3 Backend — events / handler / domain

**`backend/app/core/events.py`**

```python
@dataclass(frozen=True)
class MessagePayload:
    message: Message
    is_historical: bool = False
```

**`backend/app/domain/task.py`**

Add a field on `Task`:
```python
is_historical: bool = False
```

**Message handler** (the subscriber that turns `MessagePayload` →
`Task`): propagate `payload.is_historical` to the new `Task` instance.
Locate via `grep` for `MESSAGE_RECEIVED` subscribers in
`backend/app/`.

### 4.4 Backend — storage

**`backend/app/storage/schema.py`**

- `TaskRow`: add `is_historical = Column(Boolean, nullable=False, server_default=sa.text("0"))`.
- Repository read (`load_task` / equivalent): map column → `Task.is_historical`.
- Repository write (`save_task` / equivalent): persist field.

**Alembic migration** — new revision file in
`backend/alembic/versions/`. Mirror the style of
`947fff1b2fcd_add_messages_url.py`:

```python
def upgrade():
    with op.batch_alter_table("tasks") as b:
        b.add_column(sa.Column("is_historical", sa.Boolean(), nullable=False, server_default=sa.text("0")))

def downgrade():
    with op.batch_alter_table("tasks") as b:
        b.drop_column("is_historical")
```

`batch_alter_table` is required because SQLite cannot add a NOT NULL
column without a default in a single ALTER. `server_default="0"`
backfills existing rows to false (= treat them as live, preserving
prior behavior).

### 4.5 Backend — trader

**`backend/app/broker/trader.py:223`**

Delete the old date-comparison block entirely. Insert the new check at
the same position (between whitelist gate ① a and completeness gate ① c):

```python
# ① b. Historical-message check (per-page setting).
if (
    page_settings is not None
    and page_settings.block_historical_messages
    and task.is_historical
):
    posted = task.message.posted_at
    await _publish_skip(task, f"历史消息（posted={posted}）")
    return
```

The reason string drops the `today=` term; `started_at` is on the
listener (not the task) so we don't quote it back.

**Applies to both stock and option tasks** — the check makes no
`isinstance(inst, StockInstruction | OptionInstruction)` discrimination,
identical to the gate it replaces. Tests in §4.7 cover both shapes.

### 4.6 Frontend

**`frontend/src/api/domain-types.ts`** — regenerated from openapi after
backend changes. No hand-edit.

**`frontend/src/components/Dashboard/PageSettingsModal.tsx`**

- Delete state variable `blockNonToday` and its initializer
  (`page.settings.block_non_today_messages`).
- Delete the "禁止下单非当天消息" `<section>` block.
- Add state `blockHistorical` initialized from
  `page.settings.block_historical_messages`.
- Add a new `<section>` with the label / hint per §2, mirroring the
  prior block's structure (checkbox + hint). The section MUST live in
  the common settings area (above the `page.source === "option"`
  conditional) so it renders for both stock and option pages.
- In `handleSave`, replace `patch.block_non_today_messages = blockNonToday`
  with `patch.block_historical_messages = blockHistorical` — applied
  unconditionally for both source types.

Search the rest of `frontend/src/` for any other readers of
`block_non_today_messages` (likely none, but verify; delete any).

### 4.7 Tests

**Backend — delete**

- All `block_non_today_messages` references in:
  - `backend/tests/broker/test_trader.py`
  - `backend/tests/broker/test_trader_lot_lookup.py`
  - `backend/tests/broker/test_trader_deviation.py:306-358` (three
    "non-today → SKIPPED" cases — delete entirely; replaced below)
  - `backend/tests/whop/test_page_settings.py` (the assertions and
    constructions referencing the old field)
  - `backend/tests/api/test_whop_settings.py` (PATCH/GET cases)

**Backend — new / replace**

- `backend/tests/whop/test_page_settings.py`: default value
  (`block_historical_messages is False`); to_dict round-trip;
  from_dict tolerates missing key; patch merge behavior. Plus an
  explicit case asserting that a JSON dict containing the **legacy**
  `block_non_today_messages` key is loaded WITHOUT silently mapping it
  onto the new field (the legacy key is ignored).
- `backend/tests/api/test_whop_settings.py`: PATCH the new field, read
  it back via GET.
- `backend/tests/broker/test_trader_deviation.py`: replacement cases
  covering **both stock and option** instructions —
  - stock `is_historical=True` + setting on → SKIPPED, reason contains
    `"历史消息"`.
  - option `is_historical=True` + setting on → SKIPPED, same reason.
  - `is_historical=True` + setting off → proceeds into ① a (one of
    each shape is enough).
  - `is_historical=False` + setting on → proceeds into ① a.
- `backend/tests/whop/test_listener.py` (extend or create): inject fake
  messages with controlled `posted_at`; assert
  `MessagePayload.is_historical` matches `posted_at < started_at`.
  Edge cases: `posted_at == started_at` → `False` (strict less-than),
  `posted_at is None` → `False`.
- Message-handler test: payload flag propagates onto the persisted
  `TaskRow.is_historical`.

**Frontend**

- `PageSettingsModal.test.tsx`:
  - Delete the existing "non-today" checkbox / patch assertions.
  - New case: render with `page.settings.block_historical_messages =
    true` → checkbox shown checked.
  - New case: toggle the checkbox and click 保存 → captured PATCH body
    contains `block_historical_messages: true` (and no
    `block_non_today_messages` key).

## 5. Migration & Rollout

**Database schema**: one Alembic upgrade adds `tasks.is_historical`
(default `0`). Backfilled to `false` so existing rows behave as before.

**`whop_pages.json` (filesystem state)**: existing files keep their
`block_non_today_messages` key; the loader silently ignores it. Next
save rewrites the file with only `block_historical_messages`. Users who
had the old toggle on must re-enable the new toggle through the UI.

**`CHANGELOG.md`**: one BREAKING entry covering both the field deletion
and the semantics change (per §2).

**Order of merges**: backend (schema + alembic + trader + listener +
events + handler) → frontend (modal). Until the frontend ships, the UI
will still try to PATCH the deleted `block_non_today_messages` field
(rejected by the new schema). To avoid an awkward window, ship both in
the same release / PR.

## 6. Out of Scope

- Backward-compat alias from `block_non_today_messages` →
  `block_historical_messages` in `page_settings_from_dict` (rejected:
  see §3 "Why delete-and-add").
- A *separate* "first-scan only" toggle (rejected — user decided
  posted_at-vs-started_at is the right axis).
- Storing `listener_started_at` on `Message` (unnecessary — the boolean
  on Task is sufficient).
- Backfilling `is_historical` for pre-existing tasks (no business
  reason; they are mostly DONE/REJECTED already).

## 7. Open Questions

None — all open questions resolved during brainstorming.
