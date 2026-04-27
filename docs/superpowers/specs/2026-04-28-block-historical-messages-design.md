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

To keep the page-settings panel simple, we **rename and redefine the
existing `block_non_today_messages` setting** rather than introducing a
parallel toggle. No new checkbox; the existing one's semantics tighten.

## 2. User-Visible Change

In the `PageSettingsModal`, the "禁止下单非当天消息" section becomes:

- **Label**: `禁止下单历史消息（消息发布时间早于本次监听启动时间）`
- **Hint**: `消息 posted_at < listener.started_at → 任务标记 SKIPPED（仅解析入库，不发送订单）。比"当天/非当天"更细：当天但启动前发布的消息也会被拦。`

Saving the page settings takes effect immediately for messages flowing
through the trader; no listener restart is required (the marker is
already on the task by the time trader runs).

### Behavioral compatibility note

Users who currently have this setting **enabled** will see slightly
stricter behavior after upgrade: messages posted earlier today but
before the current listener boot will newly be SKIPPED. This is the
intended tightening, but should be called out in CHANGELOG.

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
    │ gate ① b: if page_settings.block_historical_messages and task.is_historical:
    │              _publish_skip(task, "历史消息（posted=…）"); return
    │
    ▼
... whitelist / completeness / auto_trade / submit ...
```

### Why mark on the Task (not just look up at trader time)

Listeners can be restarted between message capture and trader processing.
If the trader queried the registry for `listener.started_at` lazily, a
restart would mutate the cutoff and reclassify already-captured messages.
Tagging at capture time freezes the verdict.

### Why rename the field (not just reinterpret)

Keeping `block_non_today_messages` as the field name while quietly
changing its semantics would be a footgun for anyone reading code or
tests. The rename is the clean signal that semantics changed; we add a
read-side fallback to absorb in-flight `whop_pages.json` files.

## 4. Detailed Changes

### 4.1 Backend — domain & schema

**`backend/app/whop/page_settings.py`**

- `PageSettings.block_non_today_messages` → `PageSettings.block_historical_messages`.
- Update docstring/comment ("拦截非当天消息下单" → "拦截历史消息下单（posted_at < listener.started_at）").
- `DEFAULT_STOCK_SETTINGS`, `DEFAULT_OPTION_SETTINGS`, `default_settings_for`:
  rename references.
- `page_settings_to_dict`: write key `block_historical_messages`.
- `page_settings_from_dict`: prefer new key, fall back to old:
  ```python
  block = bool(d.get(
      "block_historical_messages",
      d.get("block_non_today_messages", base.block_historical_messages),
  ))
  ```
  This absorbs existing `whop_pages.json` files transparently. The next
  `_save_entries()` writes the new key, and the legacy key vanishes
  naturally (no forced migration script).

**`backend/app/api/schemas.py`**

- `WhopPageSettingsOut.block_non_today_messages` → `block_historical_messages`.
- `WhopPageSettingsPatch.block_non_today_messages` → `block_historical_messages`.
- `whop_page_to_out` (line 449): rename the field reference.

**`backend/app/api/http.py`**

- Lines 526 / 551 / 552: rename references in the read+patch paths.
- Patch input: `body.block_historical_messages`; patch dict key matches.

### 4.2 Backend — listener

**`backend/app/whop/listener.py`**

- `_scan_once`: compute `is_historical` per the formula above; pass it
  via `MessagePayload(message=tagged, is_historical=is_historical)`.
- No new constructor parameter; no change to `start()`, `_first_scan_done`,
  `_prime_*`, `restart_page`. The "first scan" state machine is **not
  needed** because the historical check is per-message based on timestamps.

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
Locate via `grep` for `MESSAGE_RECEIVED` subscribers.

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

Replace the date-comparison block with the historical-marker check
(stays at the same gate position — between whitelist and completeness):

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

### 4.6 Frontend

**`frontend/src/api/domain-types.ts`** — regenerated from openapi after
backend rename. No hand-edit.

**`frontend/src/components/Dashboard/PageSettingsModal.tsx`**

- State variable `blockNonToday` → `blockHistorical`.
- Initial value: `page.settings.block_historical_messages`.
- Patch body: `patch.block_historical_messages = blockHistorical`.
- Label / hint text per §2.

Search the rest of `frontend/src/` for any other readers of
`block_non_today_messages` (likely none, but verify).

### 4.7 Tests

**Backend — rewrite**

- `backend/tests/whop/test_page_settings.py` — rename references; add a
  case asserting `page_settings_from_dict` accepts both the new key and
  the legacy `block_non_today_messages` key (round-trip writes the new
  key only).
- `backend/tests/api/test_whop_settings.py` — rename field references
  in PATCH / GET assertions.
- `backend/tests/broker/test_trader_deviation.py:306-358` — three
  existing "non-today → SKIPPED" cases get rewritten:
  - Construct messages where `posted_at < started_at` and assert the
    SKIPPED reason contains `"历史消息"`.
  - Construct messages where `posted_at >= started_at` (or
    `is_historical=False`) and assert the task proceeds into ① a.
  - Assert that `block_historical_messages=False` always proceeds.
- `backend/tests/broker/test_trader.py`,
  `backend/tests/broker/test_trader_lot_lookup.py` — rename
  `block_non_today_messages=False` → `block_historical_messages=False`
  in PageSettings constructions.

**Backend — new**

- `backend/tests/whop/test_listener.py` (or extend existing): inject
  fake messages with controlled `posted_at`; assert
  `MessagePayload.is_historical` matches `posted_at < started_at`.
- Message-handler test: payload flag propagates onto the persisted
  `TaskRow.is_historical`.

**Frontend**

- `PageSettingsModal.test.tsx` — update label / hint string assertions;
  add a case where the user toggles the checkbox and the saved patch
  body contains `block_historical_messages`.

## 5. Migration & Rollout

**Schema**: one Alembic upgrade, batch_alter_table to add the column.
Backfilled to `false` so the system behaves as before for existing
tasks.

**`whop_pages.json` (filesystem state)**: zero-touch. Read-side
fallback in `page_settings_from_dict` accepts the legacy key. The first
save after upgrade rewrites entries with the new key.

**`CHANGELOG.md`**: one BREAKING entry summarizing the semantics change.

**Order of merges**: backend (schema + alembic + trader + listener) →
frontend (modal). Backend changes are backward-compatible at the API
level with the legacy frontend (the renamed PATCH field is the only
contract change, and the frontend is updated in lock-step).

## 6. Out of Scope

- Adding a *separate* "first-scan only" toggle (rejected — the user
  decided posted_at-vs-started_at is the right axis).
- Storing `listener_started_at` on `Message` (unnecessary — the boolean
  on Task is sufficient).
- Backfilling `is_historical` for pre-existing tasks (no business
  reason; they are mostly DONE/REJECTED already).
- Renaming the SKIPPED reason format used by `block_non_today_messages`
  in any other code path (the only caller is the gate in §4.5).

## 7. Open Questions

None — all open questions resolved during brainstorming.
