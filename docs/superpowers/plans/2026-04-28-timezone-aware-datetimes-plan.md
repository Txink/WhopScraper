# Timezone-aware datetimes (real UTC + Asia/Shanghai display) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the project's "naked Beijing wall-clock + literal Z suffix masquerading as UTC" convention with proper timezone-aware datetimes — every timestamp stored as real UTC, every display rendered in `Asia/Shanghai`.

**Architecture:**
1. Backend parser (`parse_whop_timestamp`) interprets Whop's wall-clock strings as `Asia/Shanghai`-local and returns real-UTC `datetime`. The listener's `is_historical = posted_at < started_at` comparison then becomes correct (both sides in real UTC).
2. A one-off Alembic data migration shifts every existing `messages.posted_at` value back by 8 hours so the new semantic interpretation matches historical reality. (Other `created_at` / `updated_at` / `received_at` columns are already real UTC and need no migration.)
3. Frontend display helpers (`fmtTime`, `weekKeyOf`, raw timestamp displays) switch from `getUTC*` / local-zone helpers to `Intl.DateTimeFormat({ timeZone: "Asia/Shanghai", ... })`. The wall-clock the user sees stays the same (Beijing), but the computation becomes correct in any browser timezone.

**Tech Stack:** Python 3.12 (`zoneinfo`), SQLAlchemy 2 + Alembic on SQLite (`DateTime(timezone=True)`), FastAPI + Pydantic v2, React + TypeScript + Vitest, `Intl.DateTimeFormat` for frontend timezone rendering.

**Pre-existing convention being torn down (codified in `frontend/src/components/Card/cardHelpers.ts:32-36`):**
> "Backend stores Whop's wall-clock time as a UTC ISO string (e.g. 'Yesterday 11:24 PM' → '2026-04-24T23:24:00Z'). Local timezone conversion would shift the displayed hour by tz offset and no longer match what the user sees in Whop."

That convention is exactly what this plan eliminates.

---

## File Structure

**Backend — new files:**
- `backend/app/utils/__init__.py` (only if missing)
- `backend/app/utils/timezones.py` — `BEIJING = ZoneInfo("Asia/Shanghai")` shared constant.
- `backend/alembic/versions/<auto>_shift_messages_posted_at_to_real_utc.py` — one-off data migration.

**Backend — modified files:**
- `backend/app/whop/extractor.py:132-194` — rewrite `parse_whop_timestamp` to interpret input as Beijing wall-clock and return real UTC.
- `backend/app/whop/listener.py:249-253` — simplify `is_historical` comparison (drop the now-unnecessary `.astimezone(UTC)`).
- `backend/tests/whop/test_extractor.py:328-397` — update `_NOW` and all expected values to reflect real-UTC semantics.
- `backend/tests/whop/test_listener.py` — add a cross-day historical-marker regression test.

**Frontend — modified files:**
- `frontend/src/components/Card/cardHelpers.ts:29-44` — rewrite `fmtTime` to use `Asia/Shanghai`; replace the misleading comment block.
- `frontend/src/components/Dashboard/weekUtils.ts:3-12` — rewrite `weekKeyOf` to compute Sunday-of-week in `Asia/Shanghai`.
- `frontend/src/components/Card/CardExpanded.tsx:100` — replace the `T`/`Z` strip-and-display with a proper Beijing render.
- `frontend/src/components/Dashboard/DatabaseRecordsPanel.tsx:7-11` — pin `fmtTime` to `Asia/Shanghai`.

**Frontend — new files:**
- `frontend/src/components/Card/cardHelpers.test.ts` (new) — unit tests for `fmtTime`.
- `frontend/src/components/Dashboard/weekUtils.test.ts` already exists — extend with cross-timezone cases.

**Docs:**
- `docs/CHANGELOG.md` (or wherever the project tracks changes — check at execute time) — note BREAKING change: `messages.posted_at` semantics changed.

---

## Phase 1 — Backend: Beijing constant

### Task 1: Add `BEIJING` timezone constant

**Files:**
- Create: `backend/app/utils/timezones.py`
- Check: `backend/app/utils/__init__.py` (create empty if missing)

- [ ] **Step 1: Confirm `app/utils/` exists**

Run: `ls backend/app/utils/ 2>/dev/null || echo MISSING`
- If output is `MISSING`: `mkdir -p backend/app/utils && touch backend/app/utils/__init__.py`
- Else: continue.

- [ ] **Step 2: Create the timezone module**

Write `backend/app/utils/timezones.py`:

```python
"""Project-wide timezone constants.

The system runs in a single business timezone (Beijing). Storage is
real UTC; presentation and calendar arithmetic that mirrors what a
Beijing-based user sees on Whop happens in ``BEIJING``.
"""

from __future__ import annotations

from zoneinfo import ZoneInfo

BEIJING: ZoneInfo = ZoneInfo("Asia/Shanghai")
"""Asia/Shanghai (UTC+8, no DST). Use for any 'what the trader's wall clock says' computation."""
```

- [ ] **Step 3: Verify it imports**

Run: `cd backend && python -c "from app.utils.timezones import BEIJING; print(BEIJING)"`
Expected: `Asia/Shanghai`

- [ ] **Step 4: Commit**

```bash
git add backend/app/utils/timezones.py backend/app/utils/__init__.py
git commit -m "feat(utils): add BEIJING timezone constant for project-wide use"
```

---

## Phase 2 — Backend: parser refactor (TDD)

### Task 2: Rewrite `parse_whop_timestamp` test fixtures for real-UTC semantics

**Files:**
- Modify: `backend/tests/whop/test_extractor.py:325-397`

Why first: writing the tests first locks in the new contract. The current tests bake in the buggy "wall-clock as UTC" assumption (e.g. `"Today at 2:30 PM"` with `now=2026-04-25T12:00Z` → `2026-04-25T14:30Z`). The new contract: **`now` is a real moment; the parser interprets the Whop string as Beijing wall-clock; the return value is the same instant expressed in real UTC.**

`_NOW = 2026-04-25T12:00 UTC` is Saturday Apr 25, 2026 at 20:00 Beijing — i.e. the Beijing "today" is still Apr 25. So `"Today at 2:30 PM"` means Beijing 14:30 on Apr 25 = real UTC `06:30` on Apr 25. (Subtract 8h from the old expected value.)

- [ ] **Step 1: Read current test file**

Run: `wc -l backend/tests/whop/test_extractor.py`
Read lines 320-400 to confirm the block.

- [ ] **Step 2: Replace the parser-test block**

Open `backend/tests/whop/test_extractor.py` and replace lines 325-397 (the `parse_whop_timestamp` unit-test section) with this exact code. Keep the surrounding file (subminute-seconds tests, etc.) untouched.

```python
# ---------------------------------------------------------------------------
# parse_whop_timestamp unit tests
# ---------------------------------------------------------------------------

from app.domain.message import Message  # noqa: E402
from app.whop.extractor import _assign_subminute_seconds, parse_whop_timestamp  # noqa: E402

# Pin "now" deterministically. _NOW is Saturday 2026-04-25 20:00 Beijing
# (= 12:00 UTC). Beijing "today" therefore = Apr 25 2026.
_NOW = datetime(2026, 4, 25, 12, 0, 0, tzinfo=UTC)


def test_parse_today_at() -> None:
    # Beijing 14:30 Apr 25 → UTC 06:30 Apr 25
    got = parse_whop_timestamp("Today at 2:30 PM", now=_NOW)
    assert got == datetime(2026, 4, 25, 6, 30, 0, tzinfo=UTC)


def test_parse_today_no_at() -> None:
    got = parse_whop_timestamp("Today 2:30 PM", now=_NOW)
    assert got == datetime(2026, 4, 25, 6, 30, 0, tzinfo=UTC)


def test_parse_yesterday_at() -> None:
    # Beijing 23:24 Apr 24 → UTC 15:24 Apr 24
    got = parse_whop_timestamp("Yesterday at 11:24 PM", now=_NOW)
    assert got == datetime(2026, 4, 24, 15, 24, 0, tzinfo=UTC)


def test_parse_yesterday_no_at() -> None:
    got = parse_whop_timestamp("Yesterday 11:24 PM", now=_NOW)
    assert got == datetime(2026, 4, 24, 15, 24, 0, tzinfo=UTC)


def test_parse_thursday_at() -> None:
    # Beijing now is Sat Apr 25; Thursday = Apr 23. Beijing 11:35 → UTC 03:35
    got = parse_whop_timestamp("Thursday at 11:35 AM", now=_NOW)
    assert got == datetime(2026, 4, 23, 3, 35, 0, tzinfo=UTC)


def test_parse_weekday_no_at() -> None:
    got = parse_whop_timestamp("Thursday 11:35 AM", now=_NOW)
    assert got == datetime(2026, 4, 23, 3, 35, 0, tzinfo=UTC)


def test_parse_full_date_with_year() -> None:
    # Beijing 17:43 Apr 13 → UTC 09:43 Apr 13
    got = parse_whop_timestamp("Apr 13, 2026 5:43 PM", now=_NOW)
    assert got == datetime(2026, 4, 13, 9, 43, 0, tzinfo=UTC)


def test_parse_full_date_implicit_year() -> None:
    got = parse_whop_timestamp("Apr 13 5:43 PM", now=_NOW)
    assert got == datetime(2026, 4, 13, 9, 43, 0, tzinfo=UTC)


def test_parse_weekday_when_today_same_weekday() -> None:
    # Beijing now = Sat Apr 25; "Saturday" must mean LAST Saturday (Apr 18).
    # Beijing 09:00 Apr 18 → UTC 01:00 Apr 18
    got = parse_whop_timestamp("Saturday at 9:00 AM", now=_NOW)
    assert got == datetime(2026, 4, 18, 1, 0, 0, tzinfo=UTC)


def test_parse_midnight_am() -> None:
    # 12:51 AM Beijing → 16:51 UTC the previous day
    got = parse_whop_timestamp("Apr 13, 2026 12:51 AM", now=_NOW)
    assert got is not None
    assert got == datetime(2026, 4, 12, 16, 51, 0, tzinfo=UTC)


def test_parse_noon_pm() -> None:
    # 12:00 PM Beijing → 04:00 UTC same day
    got = parse_whop_timestamp("Apr 13, 2026 12:00 PM", now=_NOW)
    assert got is not None
    assert got == datetime(2026, 4, 13, 4, 0, 0, tzinfo=UTC)


def test_parse_garbage_returns_none() -> None:
    assert parse_whop_timestamp("not a real timestamp", now=_NOW) is None
    assert parse_whop_timestamp("", now=_NOW) is None


def test_parse_today_when_utc_and_beijing_dates_differ() -> None:
    """Regression: real-world bug.

    At 2026-04-28 03:02 Beijing the UTC clock still reads 2026-04-27 19:02.
    A Whop "Today at 6:00 PM" message must resolve to Beijing Apr 28 18:00,
    not Apr 27 18:00. (The old UTC-date logic produced the wrong day.)
    """
    now = datetime(2026, 4, 27, 19, 2, 0, tzinfo=UTC)  # = 2026-04-28 03:02 Beijing
    got = parse_whop_timestamp("Today at 6:00 PM", now=now)
    # Beijing 18:00 Apr 28 → UTC 10:00 Apr 28
    assert got == datetime(2026, 4, 28, 10, 0, 0, tzinfo=UTC)


def test_parse_yesterday_when_utc_and_beijing_dates_differ() -> None:
    """At Beijing Apr 28 03:02 (UTC Apr 27 19:02), "Yesterday" = Beijing Apr 27."""
    now = datetime(2026, 4, 27, 19, 2, 0, tzinfo=UTC)
    got = parse_whop_timestamp("Yesterday at 11:00 AM", now=now)
    # Beijing 11:00 Apr 27 → UTC 03:00 Apr 27
    assert got == datetime(2026, 4, 27, 3, 0, 0, tzinfo=UTC)
```

- [ ] **Step 3: Run the tests — they should FAIL**

Run: `cd backend && python -m pytest tests/whop/test_extractor.py -k "parse_" -v`
Expected: 14 tests, most failing (the implementation hasn't been updated yet). The two new "utc-and-beijing differ" cases will fail loudest because the old code computes "today" against UTC.

Capture output to confirm the failure mode is "wrong datetime returned" (not "import error" — if it's an import error, the `from app.utils.timezones import BEIJING` line is unreachable; fix Phase 1 first).

- [ ] **Step 4: Commit failing tests**

```bash
git add backend/tests/whop/test_extractor.py
git commit -m "test(parser): pin Beijing-wall-clock semantics for parse_whop_timestamp"
```

---

### Task 3: Rewrite `parse_whop_timestamp` to use Beijing semantics

**Files:**
- Modify: `backend/app/whop/extractor.py:132-194`

- [ ] **Step 1: Replace the function body**

Open `backend/app/whop/extractor.py`. Replace lines 132-194 (the entire `parse_whop_timestamp` function definition) with:

```python
def parse_whop_timestamp(text: str, *, now: datetime | None = None) -> datetime | None:
    """Parse a Whop timestamp string into a real-UTC aware datetime.

    Whop displays wall-clock times in the user's local timezone. This
    project runs against a Beijing-based feed, so the input is interpreted
    as ``Asia/Shanghai`` wall-clock and the result is converted to real UTC.

    Handles all 6 formats shown in Whop chat:
      - "Today at 2:30 PM"         → today at that time (Beijing)
      - "Yesterday at 11:24 PM"    → yesterday at that time (Beijing)
      - "Thursday at 11:35 AM"     → most recent Thursday strictly before today (Beijing)
      - "Thursday 11:35 AM"        → same (variant without "at")
      - "Apr 13, 2026 5:43 PM"     → explicit date + time (interpreted Beijing)
      - "Apr 13 5:43 PM"           → explicit date (current Beijing year)

    ``now`` is the real "current moment" used to anchor relative phrases
    ("Today" / "Yesterday" / weekday). Defaults to ``datetime.now(UTC)``;
    pass it for deterministic tests. May be in any timezone — it is
    converted to Beijing internally.

    Returns a UTC-aware datetime with second=0, microsecond=0.
    Returns None if no pattern matches.
    """
    if not text:
        return None
    text = text.strip()
    if now is None:
        now = datetime.now(UTC)
    now_bj = now.astimezone(BEIJING)
    today_bj = now_bj.date()

    def _build(d: date, h: int, m: int, ampm: str) -> datetime:
        h24 = (h % 12) + (12 if ampm.upper() == "PM" else 0)
        # Construct the wall-clock moment in Beijing, then convert to real UTC.
        bj = datetime.combine(d, time(h24, m), tzinfo=BEIJING)
        return bj.astimezone(UTC)

    # Today at H:MM AM/PM
    if m := _TODAY_RE.match(text):
        return _build(today_bj, int(m.group(1)), int(m.group(2)), m.group(3))

    # Yesterday at H:MM AM/PM
    if m := _YESTERDAY_RE.match(text):
        return _build(today_bj - timedelta(days=1), int(m.group(1)), int(m.group(2)), m.group(3))

    # <Mon> D[, YYYY] H:MM AM/PM  — try full date before weekday to avoid false match
    if m := _FULL_DATE_RE.match(text):
        mon = m.group(1).lower()[:3]
        if mon in _MONTHS_LOWER:
            month_num = _MONTHS_LOWER.index(mon) + 1
            day = int(m.group(2))
            year = int(m.group(3)) if m.group(3) else today_bj.year
            try:
                d = date(year, month_num, day)
                return _build(d, int(m.group(4)), int(m.group(5)), m.group(6))
            except ValueError:
                pass

    # <Weekday>[at] H:MM AM/PM  — most recent occurrence strictly before today
    if m := _WEEKDAY_RE.match(text):
        wd_name = m.group(1).lower()
        if wd_name in _WEEKDAYS_LOWER:
            target_wd = _WEEKDAYS_LOWER.index(wd_name)
            today_wd = today_bj.weekday()
            # days_back must be at least 1 (strictly before today).
            # If today is Thursday and text says "Thursday", that's last Thursday (7 days back).
            days_back = (today_wd - target_wd) % 7
            if days_back == 0:
                days_back = 7
            d = today_bj - timedelta(days=days_back)
            return _build(d, int(m.group(2)), int(m.group(3)), m.group(4))

    return None
```

- [ ] **Step 2: Add the BEIJING import at the top of the file**

In `backend/app/whop/extractor.py`, find the existing imports near the top of the file. Add this line in the import block (alphabetical or near other `from app.` imports):

```python
from app.utils.timezones import BEIJING
```

If the existing block already imports things like `from app.domain.message import Message`, put the new line nearby.

- [ ] **Step 3: Run the parser tests — they should now PASS**

Run: `cd backend && python -m pytest tests/whop/test_extractor.py -k "parse_" -v`
Expected: 14 tests pass.

- [ ] **Step 4: Run the FULL test_extractor file**

Run: `cd backend && python -m pytest tests/whop/test_extractor.py -v`
Expected: all tests pass. If the integration-style tests in this file (the ones above the parser unit tests) fail, look for places where they construct expected `posted_at` values and update them — those expected values were written under the old "fake-UTC" convention.

- [ ] **Step 5: Run the full backend suite to surface fallout**

Run: `cd backend && python -m pytest -x -q`
Expected: tests pass OR a small number fail with concrete `posted_at` mismatches. Triage each failure: most should be tests that hard-code expected `posted_at` values; update those expectations to reflect the new "Beijing-as-input → real-UTC-as-output" semantics. Do NOT silently weaken any assertion.

If a non-test file (production code) fails because it depended on the old semantic — STOP and reread Phase 4 (listener) and Phase 5 (DB migration). The listener code already uses real-UTC `_started_at`, and after this change the comparison just works.

- [ ] **Step 6: Commit the parser implementation**

```bash
git add backend/app/whop/extractor.py
git commit -m "fix(parser): interpret Whop timestamps as Beijing wall-clock, return real UTC

Previously parse_whop_timestamp used datetime.now(UTC).date() to resolve
'Today'/'Yesterday'/weekday phrases, then tagged the result with UTC
tzinfo without timezone conversion. This produced datetimes whose stored
wall-clock matched what Whop displayed, but were off by 8h from the real
moment — and resolved 'Today' to the wrong calendar day during the 8h
window when Beijing and UTC dates disagree.

The function now interprets the input as Asia/Shanghai wall-clock and
returns a real-UTC datetime representing the same instant. Existing
callers (listener, option_parser, _parse_timestamp wrapper) work
unchanged because they treat the result as an opaque tz-aware datetime."
```

If Step 5 also required test-fixture updates in other files, include those files in this commit (or a follow-up commit if they are large).

---

## Phase 3 — Backend: listener simplification + regression test

### Task 4: Simplify `is_historical` comparison

**Files:**
- Modify: `backend/app/whop/listener.py:249-253`

After Task 3, both sides of the comparison are real UTC. The defensive `.astimezone(UTC)` becomes a no-op. We can remove it for clarity, but it costs nothing to keep — the rule is "don't change working code without a reason." Keep the call; it's a cheap belt-and-braces against future contributors who pass naive datetimes. **No code change for Task 4.** Just verify behavior.

- [ ] **Step 1: Re-read the listener block**

Read `backend/app/whop/listener.py` lines 235-265. Confirm:
- Line 187: `self._started_at = datetime.now(UTC)` — real UTC ✓
- Line 240: `now = datetime.now(UTC)` — real UTC, passed as `received_at` ✓
- Line 252: `tagged.posted_at.astimezone(UTC) < self._started_at` — real-UTC vs real-UTC ✓

If any of those is different in the current file, STOP and reconcile with this plan.

- [ ] **Step 2: No code edit — proceed to test in Task 5**

(Skipped intentionally. Document that the comparison is now correct without modification.)

---

### Task 5: Add a cross-day historical-marker regression test

**Files:**
- Modify: `backend/tests/whop/test_listener.py`

- [ ] **Step 1: Read existing listener tests**

Run: `wc -l backend/tests/whop/test_listener.py`
Read the file to see fixtures, helpers, and existing historical-marker tests around line 316/362.

- [ ] **Step 2: Add a regression test for the cross-day window**

The bug being prevented: at 2026-04-28 03:02 Beijing (= 2026-04-27 19:02 UTC), a Whop "Today at 6:00 PM" message (Beijing Apr 28 18:00 = real UTC Apr 28 10:00) must be classified as **future / non-historical** — its `posted_at` is later than `started_at`. Under the old fake-UTC code, posted_at would have been stored as `2026-04-28T18:00Z` and the comparison `18:00 UTC < 19:02 UTC` would have wrongly marked it historical.

Add this test at the bottom of `backend/tests/whop/test_listener.py` (adapt the helper imports to whatever the file already uses; if there's an existing pattern that constructs a listener with a mock browser and a captured event bus, follow it — don't reinvent):

```python
def test_historical_marker_does_not_misclassify_across_utc_beijing_date_boundary(monkeypatch) -> None:
    """At Beijing Apr 28 03:02 (= UTC Apr 27 19:02), a Whop 'Today at 6 PM'
    message means Beijing Apr 28 18:00 = UTC Apr 28 10:00. That instant is
    in the FUTURE relative to listener start, so is_historical must be False.
    Regression for the bug that surfaced when block_historical_messages was
    enabled at 03:02 local time."""

    # Anchor "now" so the parser sees Beijing Apr 28 03:02.
    fake_now = datetime(2026, 4, 27, 19, 2, 0, tzinfo=UTC)

    started_at = fake_now  # listener started "just now"
    posted_at = parse_whop_timestamp("Today at 6:00 PM", now=fake_now)
    assert posted_at == datetime(2026, 4, 28, 10, 0, 0, tzinfo=UTC)

    # Replicate the listener's exact comparison.
    is_historical = (
        posted_at is not None
        and posted_at.astimezone(UTC) < started_at
    )
    assert is_historical is False, (
        f"Today's message (posted_at={posted_at}) wrongly marked historical "
        f"vs started_at={started_at}"
    )
```

Place the import at the top of the test file if not already present:

```python
from app.whop.extractor import parse_whop_timestamp
```

- [ ] **Step 3: Run the test**

Run: `cd backend && python -m pytest tests/whop/test_listener.py -k "across_utc_beijing" -v`
Expected: PASS.

- [ ] **Step 4: Run all listener tests**

Run: `cd backend && python -m pytest tests/whop/test_listener.py -v`
Expected: all pass. If existing tests fail because they hard-coded `posted_at` values under fake-UTC semantics, update those expectations consistently.

- [ ] **Step 5: Commit**

```bash
git add backend/tests/whop/test_listener.py
git commit -m "test(listener): regression for is_historical across UTC/Beijing date boundary"
```

---

## Phase 4 — Backend: data migration

### Task 6: Alembic migration to shift existing `messages.posted_at` by -8h

**Files:**
- Create: `backend/alembic/versions/<auto>_shift_messages_posted_at_to_real_utc.py`

Why this is needed: every existing `messages.posted_at` row was written under the old "Beijing-wall-clock-tagged-as-UTC" convention. After Task 3, new rows are real UTC. Without migrating, mixed-semantic rows would coexist, breaking time arithmetic and historical-marker comparisons against any old row.

Other timestamp columns (`tasks.created_at`, `tasks.updated_at`, `messages.received_at`, `push_events.received_at`, `positions.updated_at`) were always written via `datetime.now(UTC)` and are already real UTC — they need no migration.

- [ ] **Step 1: Generate a fresh migration scaffold**

Run: `cd backend && alembic revision -m "shift_messages_posted_at_to_real_utc"`
Expected: a new file `backend/alembic/versions/<rev>_shift_messages_posted_at_to_real_utc.py` is created. Note its filename.

- [ ] **Step 2: Replace the migration body**

Open the new file and replace its contents with the following. Keep the auto-generated `revision` / `down_revision` lines that Alembic produced — only replace the `upgrade()` / `downgrade()` bodies and the docstring.

```python
"""shift messages.posted_at to real UTC

Until this migration, posted_at was stored as the Whop wall-clock
(Beijing) tagged with UTC tzinfo — i.e. every value was 8 hours ahead
of the true moment. The parser now returns real UTC, so existing rows
must be shifted back by 8 hours to preserve the correct instant.

Reversible: downgrade adds 8 hours back.

Revision ID: <auto>
Revises: <auto>
Create Date: <auto>
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
# (KEEP whatever Alembic generated above this line — do not overwrite.)


def upgrade() -> None:
    """Shift posted_at: stored_value -= 8h to convert Beijing wall-clock to real UTC."""
    bind = op.get_bind()
    dialect = bind.dialect.name
    if dialect == "sqlite":
        op.execute("UPDATE messages SET posted_at = datetime(posted_at, '-8 hours')")
    elif dialect == "postgresql":
        op.execute("UPDATE messages SET posted_at = posted_at - INTERVAL '8 hours'")
    else:
        raise NotImplementedError(
            f"shift migration not implemented for dialect {dialect!r}; "
            "add a branch above before running."
        )


def downgrade() -> None:
    """Reverse: stored_value += 8h."""
    bind = op.get_bind()
    dialect = bind.dialect.name
    if dialect == "sqlite":
        op.execute("UPDATE messages SET posted_at = datetime(posted_at, '+8 hours')")
    elif dialect == "postgresql":
        op.execute("UPDATE messages SET posted_at = posted_at + INTERVAL '8 hours'")
    else:
        raise NotImplementedError(
            f"shift migration not implemented for dialect {dialect!r}; "
            "add a branch above before running."
        )
```

- [ ] **Step 3: Dry-run the migration on a copy of the dev DB**

Locate the SQLite DB file (typical paths: `backend/data/*.db`, `backend/dev.db`, or whatever `alembic.ini` / settings point to). Then:

```bash
cd backend
# 1. Find current DB path. Inspect alembic.ini's sqlalchemy.url and/or app settings.
# 2. Make a backup copy:
cp <db_path> <db_path>.bak-pre-tz-migration
# 3. Show a few posted_at rows BEFORE migrating:
sqlite3 <db_path> "SELECT id, posted_at FROM messages ORDER BY posted_at DESC LIMIT 5"
# 4. Run the migration:
alembic upgrade head
# 5. Show the same rows AFTER:
sqlite3 <db_path> "SELECT id, posted_at FROM messages ORDER BY posted_at DESC LIMIT 5"
```

Expected: each posted_at value is 8 hours earlier than before.

If something looks off, restore from `.bak-pre-tz-migration` and stop — do not commit.

- [ ] **Step 4: Verify downgrade also works**

```bash
cd backend
alembic downgrade -1
sqlite3 <db_path> "SELECT id, posted_at FROM messages ORDER BY posted_at DESC LIMIT 5"
# Should match the pre-migration values
alembic upgrade head
sqlite3 <db_path> "SELECT id, posted_at FROM messages ORDER BY posted_at DESC LIMIT 5"
# Should match the post-migration values again
```

- [ ] **Step 5: Run the test suite once more (post-migration state)**

Run: `cd backend && python -m pytest -x -q`
Expected: green. (Tests use temporary DBs / fixtures, not the dev DB, so this is unaffected by the migration on dev data — it's just a final sanity check.)

- [ ] **Step 6: Commit the migration**

```bash
git add backend/alembic/versions/<filename>.py
git commit -m "feat(db): migrate messages.posted_at to real-UTC semantics

One-off shift of existing posted_at values back by 8 hours. Pairs with
the parser change in the previous commit so that all rows — old and
new — represent real UTC instants. Reversible."
```

---

## Phase 5 — Frontend: display in Asia/Shanghai

### Task 7: Rewrite `cardHelpers.ts:fmtTime` for Asia/Shanghai display

**Files:**
- Modify: `frontend/src/components/Card/cardHelpers.ts:29-44`
- Create: `frontend/src/components/Card/cardHelpers.test.ts`

- [ ] **Step 1: Write failing tests**

Create `frontend/src/components/Card/cardHelpers.test.ts`:

```typescript
import { describe, expect, it } from "vitest";
import { fmtTime, elapsedMs } from "./cardHelpers";

describe("fmtTime", () => {
  it("renders a real-UTC timestamp as Beijing HH:MM:SS", () => {
    // Real UTC 06:30:00 → Beijing 14:30:00
    expect(fmtTime("2026-04-25T06:30:00Z")).toBe("14:30:00");
  });

  it("crosses the date boundary correctly", () => {
    // Real UTC 16:00:00 Apr 24 → Beijing 00:00:00 Apr 25
    expect(fmtTime("2026-04-24T16:00:00Z")).toBe("00:00:00");
  });

  it("handles seconds precision", () => {
    expect(fmtTime("2026-04-25T06:30:42.000Z")).toBe("14:30:42");
  });

  it("renders independent of the host browser timezone", () => {
    // The Intl path uses an explicit timeZone option, so this assertion
    // documents intent: identical input → identical output regardless
    // of where the test runs.
    const a = fmtTime("2026-04-25T06:30:00Z");
    expect(a).toBe("14:30:00");
  });
});

describe("elapsedMs", () => {
  it("computes positive elapsed milliseconds for forward intervals", () => {
    expect(elapsedMs("2026-04-25T06:30:00Z", "2026-04-25T06:30:01Z")).toBe(1000);
  });
});
```

- [ ] **Step 2: Run tests — they should FAIL on the date-boundary case at minimum**

Run: `cd frontend && npx vitest run src/components/Card/cardHelpers.test.ts`
Expected: at least the date-boundary test fails (the current `fmtTime` uses `getUTCHours()`, which would return `16:00:00` for the second case, not the desired `00:00:00`).

- [ ] **Step 3: Replace `fmtTime` with the timezone-aware implementation**

Open `frontend/src/components/Card/cardHelpers.ts` and replace lines 29-44 with:

```typescript
/**
 * Format a real-UTC ISO timestamp as Beijing HH:MM:SS.
 *
 * Backend stores all timestamps as real UTC (e.g. "2026-04-25T06:30:00Z").
 * We render in Asia/Shanghai because the project is operated from Beijing
 * and the user reads Whop wall-clock in that zone — pinning the formatter
 * keeps the display consistent regardless of the browser's local timezone.
 */
const _BJ_HMS = new Intl.DateTimeFormat("en-GB", {
  timeZone: "Asia/Shanghai",
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
  hour12: false,
});

export function fmtTime(iso: string): string {
  const d = new Date(iso);
  // en-GB with hour12=false yields "HH:mm:ss"; some Node/JSC builds emit
  // "24:00:00" for midnight — normalize to "00:00:00".
  return _BJ_HMS.format(d).replace(/^24:/, "00:");
}
```

Leave `formatOptionTitle`, `formatStockTitle`, `formatTitle`, `fmtElapsed`, and `elapsedMs` unchanged.

- [ ] **Step 4: Run the tests — they should PASS**

Run: `cd frontend && npx vitest run src/components/Card/cardHelpers.test.ts`
Expected: all 5 tests pass.

- [ ] **Step 5: Run the broader frontend suite to catch fallout**

Run: `cd frontend && npx vitest run`
Expected: existing tests for `CardCompact` etc. continue to pass. The rendered hour string for fixtures like `posted_at: "2026-04-25T10:42:15.000Z"` will change (old: `"10:42:15"`; new: `"18:42:15"`). Update any test that snapshots the old value to the new Beijing-rendered value. Do NOT weaken assertions to make them pass — change the expected string to the correct one.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/Card/cardHelpers.ts frontend/src/components/Card/cardHelpers.test.ts frontend/src/components/Card/CardCompact.test.tsx
git commit -m "feat(ui): render timestamps in Asia/Shanghai via Intl.DateTimeFormat"
```

(Add other touched test files to the commit as needed.)

---

### Task 8: Rewrite `weekUtils.ts:weekKeyOf` for Asia/Shanghai semantics

**Files:**
- Modify: `frontend/src/components/Dashboard/weekUtils.ts:3-12`
- Modify: `frontend/src/components/Dashboard/weekUtils.test.ts` (extend)

The current implementation uses local-zone Date methods (`d.getDate()`, `setDate()`, `getDay()`), so the week key depends on the host browser timezone. We want it pinned to Asia/Shanghai for stability.

- [ ] **Step 1: Add a failing test**

Open `frontend/src/components/Dashboard/weekUtils.test.ts` and add this test at the end of the file (inside the existing `describe` block, or in a new one):

```typescript
import { describe, expect, it } from "vitest";
import { weekKeyOf } from "./weekUtils";

describe("weekKeyOf — Beijing-pinned", () => {
  it("places a UTC-Saturday late-night moment in the correct Beijing week", () => {
    // Real UTC 2026-04-25T20:00:00Z = Beijing 2026-04-26T04:00 (Sunday).
    // In Beijing, Sunday Apr 26 is the start of the week containing Apr 26.
    expect(weekKeyOf("2026-04-25T20:00:00Z")).toBe("2026-04-26");
  });

  it("rolls a UTC-late-Saturday into the Beijing-Sunday week", () => {
    // Real UTC 2026-04-25T16:00:00Z = Beijing 2026-04-26T00:00 exactly.
    expect(weekKeyOf("2026-04-25T16:00:00Z")).toBe("2026-04-26");
  });

  it("treats early Beijing Saturday as still the previous Sunday's week", () => {
    // Real UTC 2026-04-25T01:00:00Z = Beijing 2026-04-25T09:00 (Saturday).
    // Beijing-Saturday belongs to the week starting on the prior Sunday Apr 19.
    expect(weekKeyOf("2026-04-25T01:00:00Z")).toBe("2026-04-19");
  });
});
```

If `weekKeyOf` is already imported in this test file, drop the duplicate import.

- [ ] **Step 2: Run tests — they should FAIL**

Run: `cd frontend && npx vitest run src/components/Dashboard/weekUtils.test.ts`
Expected: the new tests fail (the local-zone implementation won't agree on Beijing-pinned keys when the host TZ ≠ Asia/Shanghai). They may incidentally pass if the dev machine *is* in Beijing, but the implementation is still wrong — proceed with the rewrite.

- [ ] **Step 3: Rewrite `weekKeyOf`**

In `frontend/src/components/Dashboard/weekUtils.ts`, replace lines 3-12 with:

```typescript
const _BJ_PARTS = new Intl.DateTimeFormat("en-CA", {
  timeZone: "Asia/Shanghai",
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  weekday: "short",
});

/**
 * Sunday-of-week key (YYYY-MM-DD) computed in Asia/Shanghai.
 *
 * Backend timestamps are real UTC; the user thinks in Beijing. We project
 * the moment into Beijing, find that day's calendar date, then walk back
 * to the most recent Sunday — purely as date arithmetic, never as
 * tz-sensitive Date math.
 */
export function weekKeyOf(ts: string): string {
  const d = new Date(ts);
  const parts = _BJ_PARTS.formatToParts(d);
  const get = (t: string) => parts.find((p) => p.type === t)?.value ?? "";
  const y = Number(get("year"));
  const mo = Number(get("month"));
  const dd = Number(get("day"));
  const weekdayShort = get("weekday"); // "Sun" | "Mon" | ...
  const wdMap: Record<string, number> = { Sun: 0, Mon: 1, Tue: 2, Wed: 3, Thu: 4, Fri: 5, Sat: 6 };
  const wd = wdMap[weekdayShort] ?? 0;
  // Walk back `wd` days using a date-only UTC anchor (avoids host-tz drift).
  const anchor = new Date(Date.UTC(y, mo - 1, dd));
  anchor.setUTCDate(anchor.getUTCDate() - wd);
  const yyyy = anchor.getUTCFullYear();
  const mm = String(anchor.getUTCMonth() + 1).padStart(2, "0");
  const day = String(anchor.getUTCDate()).padStart(2, "0");
  return `${yyyy}-${mm}-${day}`;
}
```

Leave `formatWeekRange`, `taskTime`, `computeWeeks`, and the interfaces unchanged. (`formatWeekRange` operates on the YYYY-MM-DD string directly — no host-tz dependency in the output keys.)

- [ ] **Step 4: Run all weekUtils tests**

Run: `cd frontend && npx vitest run src/components/Dashboard/weekUtils.test.ts`
Expected: all tests pass — the existing ones AND the three new Beijing-pinned ones.

If a pre-existing test fails because its expected `weekKey` no longer matches under the new (Beijing-pinned) semantic, update the expected value. The pre-existing tests construct ISO strings via `new Date(YYYY, M-1, D, ...).toISOString()`, which serializes the host-local moment to UTC — so under the new function, they'll need expected keys that reflect what Beijing thinks the week is for that real moment. Walk through each failing case manually; do not weaken assertions.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/Dashboard/weekUtils.ts frontend/src/components/Dashboard/weekUtils.test.ts
git commit -m "fix(ui): pin weekKeyOf to Asia/Shanghai instead of host browser timezone"
```

---

### Task 9: Fix raw-timestamp display in `CardExpanded.tsx`

**Files:**
- Modify: `frontend/src/components/Card/CardExpanded.tsx:100`

The current line strips `T` and `Z` from the ISO string and prints the raw text — under the old fake-UTC convention this happened to match the Whop wall-clock. After Phase 5 it would print the real-UTC wall-clock instead. We want a Beijing-rendered "YYYY-MM-DD HH:MM:SS" instead.

- [ ] **Step 1: Add a Beijing-pinned date+time formatter**

In `frontend/src/components/Card/cardHelpers.ts`, append (below the existing exports):

```typescript
const _BJ_FULL = new Intl.DateTimeFormat("en-CA", {
  timeZone: "Asia/Shanghai",
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
  hour12: false,
});

/**
 * Format a real-UTC ISO timestamp as Beijing "YYYY-MM-DD HH:MM:SS".
 * Use for display contexts where the full date+time is shown verbatim.
 */
export function fmtBeijingFull(iso: string): string {
  const d = new Date(iso);
  // en-CA gives "YYYY-MM-DD, HH:mm:ss"; normalize separator to a space.
  return _BJ_FULL.format(d).replace(", ", " ").replace(/^24:/, "00:");
}
```

- [ ] **Step 2: Add a unit test for `fmtBeijingFull`**

In `frontend/src/components/Card/cardHelpers.test.ts`, add:

```typescript
import { fmtBeijingFull } from "./cardHelpers";

describe("fmtBeijingFull", () => {
  it("renders a real-UTC ISO as Beijing YYYY-MM-DD HH:MM:SS", () => {
    expect(fmtBeijingFull("2026-04-25T06:30:00Z")).toBe("2026-04-25 14:30:00");
  });

  it("crosses the date boundary forwards", () => {
    expect(fmtBeijingFull("2026-04-24T16:30:00Z")).toBe("2026-04-25 00:30:00");
  });
});
```

- [ ] **Step 3: Run the test — should PASS**

Run: `cd frontend && npx vitest run src/components/Card/cardHelpers.test.ts`
Expected: all tests pass (including the two new ones).

- [ ] **Step 4: Wire `fmtBeijingFull` into CardExpanded**

In `frontend/src/components/Card/CardExpanded.tsx`, find line 100:

```tsx
              <span className="v">{message.posted_at.replace("T", " ").replace("Z", "")}</span>
```

Replace with:

```tsx
              <span className="v">{fmtBeijingFull(message.posted_at)}</span>
```

Add the import at the top of the file (alongside any existing import from `./cardHelpers`):

```tsx
import { fmtBeijingFull } from "./cardHelpers";
```

If there's already an import from `./cardHelpers`, merge the named import in.

- [ ] **Step 5: Manually verify in the dev server**

Run: `cd frontend && npm run dev` (or whatever script is configured).
Open the dashboard, expand a card, confirm the `ts` field now reads as Beijing wall-clock (matching what the user sees in Whop). If the displayed value differs from Whop's display by exactly 8h, the migration in Task 6 wasn't run on the dev DB — re-run it.

- [ ] **Step 6: Run frontend tests once more**

Run: `cd frontend && npx vitest run`
Expected: green.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/Card/CardExpanded.tsx frontend/src/components/Card/cardHelpers.ts frontend/src/components/Card/cardHelpers.test.ts
git commit -m "fix(ui): render CardExpanded ts as Beijing wall-clock via fmtBeijingFull"
```

---

### Task 10: Fix `DatabaseRecordsPanel.tsx` `fmtTime` to pin Asia/Shanghai

**Files:**
- Modify: `frontend/src/components/Dashboard/DatabaseRecordsPanel.tsx:7-11`

The current local `fmtTime` here uses `d.toLocaleString()` — host-locale + host-timezone, which is exactly what we don't want.

- [ ] **Step 1: Replace the local helper**

In `frontend/src/components/Dashboard/DatabaseRecordsPanel.tsx`, find lines 7-11:

```typescript
function fmtTime(ts: string): string {
  const d = new Date(ts);
  if (Number.isNaN(d.getTime())) return ts;
  return d.toLocaleString();
}
```

Replace with:

```typescript
import { fmtBeijingFull } from "../Card/cardHelpers";

function fmtTime(ts: string): string {
  const d = new Date(ts);
  if (Number.isNaN(d.getTime())) return ts;
  return fmtBeijingFull(ts);
}
```

If the `import` block at the top of the file already exists, place the new import there alongside the others (don't put `import` mid-file). If TypeScript complains about the unused `d`, drop the local-Date check and just delegate:

```typescript
function fmtTime(ts: string): string {
  const d = new Date(ts);
  if (Number.isNaN(d.getTime())) return ts;
  return fmtBeijingFull(ts);
}
```

(Keep the NaN guard — the panel may receive malformed strings from the DB.)

- [ ] **Step 2: Type-check + run tests**

Run: `cd frontend && npx tsc --noEmit && npx vitest run`
Expected: green.

- [ ] **Step 3: Manually verify the panel**

Open the database-records panel in the dev server. Confirm `created_at` etc. render in Beijing wall-clock format.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/Dashboard/DatabaseRecordsPanel.tsx
git commit -m "fix(ui): pin DatabaseRecordsPanel timestamps to Beijing display"
```

---

## Phase 6 — Cleanup, docs, end-to-end verification

### Task 11: Remove obsolete comments and sweep stale references

**Files:**
- Modify: any code containing comments like "Whop wall-clock as UTC", "strips T/Z", or describing the old fake-UTC convention. The known sites have all been edited above; this is a final sweep.

- [ ] **Step 1: Search for stale comments**

Run from the repo root:

```bash
grep -rn "wall-clock" --include="*.py" --include="*.ts" --include="*.tsx" --include="*.md" .
grep -rn "fake.\?UTC\|naked.\?UTC\|masquerad" --include="*.py" --include="*.ts" --include="*.tsx" --include="*.md" .
grep -rn "strip.*Z\|replace.\"Z\"" --include="*.ts" --include="*.tsx" .
```

For each hit:
- If it's in a file you've already edited and reflects the OLD convention, update the comment to describe the new (Beijing-display, real-UTC-storage) reality.
- If it's in a file you HAVEN'T touched, read context and decide: stale doc → fix; unrelated → leave alone.

- [ ] **Step 2: Update CLAUDE.md if it documents the old convention**

```bash
grep -n "posted_at\|UTC\|Beijing\|timezone" CLAUDE.md 2>/dev/null
```

If anything contradicts the new model, edit it to match. (If CLAUDE.md doesn't exist or is silent on this, skip.)

- [ ] **Step 3: Add a changelog entry**

Locate the project's changelog file (one of: `CHANGELOG.md`, `docs/CHANGELOG.md`, `docs/changelog/...`). Look at recent commits like `b7603b2 docs(changelog): block_non_today_messages → block_historical_messages BREAKING` for the project's changelog conventions.

Add an entry under the appropriate version/date heading:

```markdown
- BREAKING: `messages.posted_at` semantics changed. Previously stored as Whop wall-clock (Beijing) tagged with UTC tzinfo (off by 8h from the real instant). Now stored as real UTC. A one-off Alembic migration shifts existing rows by -8h; new rows are written by the parser already in real UTC. Frontend display helpers (`fmtTime`, `fmtBeijingFull`, `weekKeyOf`, `DatabaseRecordsPanel.fmtTime`) now project to Asia/Shanghai via `Intl.DateTimeFormat` instead of `getUTC*` / host-locale.
```

- [ ] **Step 4: Commit**

```bash
git add -p   # review each hunk; only stage cleanups, no surprises
git commit -m "docs: update timezone-handling comments and changelog"
```

---

### Task 12: End-to-end verification

This is the gate before declaring done. The unit tests passed, but the real test is "does a fresh listener cycle produce correct posted_at and does the UI render the same wall-clock the user sees in Whop?"

- [ ] **Step 1: Backend self-check**

Run: `cd backend && python -m pytest -q`
Expected: green.

- [ ] **Step 2: Frontend self-check**

Run: `cd frontend && npx tsc --noEmit && npx vitest run`
Expected: green.

- [ ] **Step 3: Manual smoke test**

Start the full stack (backend + frontend dev server in two terminals — follow whatever README/scripts the repo provides). Open a Whop page that the listener watches. Wait for a new message to appear.

Verify:
1. The new message's `posted_at` displayed in CardCompact matches the time Whop shows (Beijing wall-clock). ✓
2. The new message's `posted_at` displayed in CardExpanded (the `ts` field at line 100) matches Whop's display. ✓
3. The dashboard week grouping puts today's message in the current week. ✓
4. With `block_historical_messages` enabled, today's just-arrived message is NOT skipped (the original bug). ✓
5. An old (pre-migration) message in the DatabaseRecordsPanel still renders at a sensible Beijing wall-clock — it should match what was historically displayed (because the migration shifted the storage and the display undoes the shift). ✓

If any of those fail, STOP and root-cause. Do not patch over inconsistencies.

- [ ] **Step 4: If everything looks right, push**

(Per project preference — don't push without user confirmation if that's the established norm. The previous commits in `git log` are local-only, so this branch may not have a remote yet.)

---

## Self-Review

**Spec coverage:** the user's "推翻 fake-UTC 约定，全栈改用真时区感知 datetime" is implemented across three planes — parser (Phase 2), storage migration (Phase 4), and frontend display (Phase 5). The cross-day historical-marker bug that triggered this is captured by an explicit regression test (Task 5) and validated end-to-end (Task 12 step 3.4).

**Placeholder scan:** the only `<auto>` placeholders are inside the Alembic migration file, which Alembic itself generates — those are not plan placeholders. No "TBD", "implement later", or unspecified test bodies.

**Type / API consistency:** `parse_whop_timestamp(text, *, now)` keeps its existing signature; only semantics change. `fmtTime`, `weekKeyOf`, `fmtBeijingFull` are all named and tested where introduced. `DatabaseRecordsPanel`'s local `fmtTime` is delegated to `fmtBeijingFull` from `cardHelpers`. The Beijing constant lives in `app.utils.timezones.BEIJING`, imported at exactly the parser site.

**Risks not eliminated by the plan:** the data migration assumes every existing `messages.posted_at` was written under the old convention. If the listener was ever run with a hypothetical earlier version of the parser that already produced real UTC, those rows would be over-corrected. Mitigation: the changelog entry calls this out, and the migration is reversible (downgrade adds 8h back). Inspect `git log -- backend/app/whop/extractor.py` before running the migration on a production DB to confirm the parser has only ever used the fake-UTC convention.
