"""Verify the ``2c15fa4a14ca`` migration shifts ``messages.posted_at`` by ±8h.

Drives the real alembic CLI against a temp-file SQLite DB:

    1. ``upgrade b3e4f5a6c7d8`` — applies every migration up to (but not
       including) the shift migration; this gives us the schema without
       the shift applied yet.
    2. Insert four known ``messages`` rows (with their dependent
       ``tasks`` rows, since ``messages.id`` is a FK). The fourth row
       has ``posted_at == received_at`` to simulate the parse-failure
       fallback path in ``app/whop/extractor.py:_parse_timestamp`` —
       those rows are already real UTC and must NOT be shifted.
    3. ``upgrade head`` (= ``2c15fa4a14ca``) — applies the shift.
       Assert the first three ``posted_at`` values are exactly 8 hours
       earlier, and the fallback row is unchanged.
    4. ``downgrade -1`` — reverses the shift.
       Assert the first three ``posted_at`` values are back to their
       originals, and the fallback row is still unchanged.

This exercises the migration's SQL on a real SQLite engine, including
the ``datetime(value, '-8 hours')`` string-arithmetic that SQLite uses
to manipulate ISO-formatted timestamps.
"""

from __future__ import annotations

import asyncio
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic.config import Config

from alembic import command

BACKEND_DIR = Path(__file__).resolve().parents[2]

# Revision IDs in the chain.  ``_PREV_HEAD`` is the migration immediately
# before our shift, so we can stage the DB with all earlier schema applied
# but the shift itself not yet run.
_PREV_HEAD = "b3e4f5a6c7d8"
_SHIFT_REV = "2c15fa4a14ca"

# Three known posted_at instants — chosen to cross day boundaries when
# shifted by -8h so we exercise more than just hour subtraction.
_FIXTURES = [
    # (task_id, posted_at_str, expected_after_minus_8h)
    ("t1", "2026-04-25 18:00:00+00:00", "2026-04-25 10:00:00"),
    ("t2", "2026-04-25 04:00:00+00:00", "2026-04-24 20:00:00"),
    ("t3", "2026-04-25 08:00:00+00:00", "2026-04-25 00:00:00"),
]

# Fourth fixture: parse-failure fallback row where posted_at == received_at.
# This row is REAL UTC (from datetime.now(UTC)) and the migration must
# leave it untouched in both directions. Distinct from the three above so
# a copy-paste error would surface immediately.
_FALLBACK_ID = "t4_fallback"
_FALLBACK_POSTED_AT = "2024-01-15 12:34:56+00:00"


def _alembic_cfg(url: str) -> Config:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    cfg.set_main_option("sqlalchemy.url", url)
    return cfg


def _seed_rows(db_path: Path) -> None:
    """Insert task + message fixture rows directly via sqlite3."""
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA foreign_keys=ON")
        now = datetime.now(UTC).isoformat(sep=" ")
        for task_id, posted_at, _expected in _FIXTURES:
            conn.execute(
                "INSERT INTO tasks (id, type, status, created_at, updated_at, is_historical) "
                "VALUES (?, 'message', 'parsed', ?, ?, ?)",
                (task_id, now, now, False),
            )
            conn.execute(
                "INSERT INTO messages "
                "(id, content, raw_content, source, posted_at, received_at) "
                "VALUES (?, 'c', 'rc', 'whop', ?, ?)",
                (task_id, posted_at, now),
            )
        # Fallback row: posted_at == received_at (parse-failure path).
        conn.execute(
            "INSERT INTO tasks (id, type, status, created_at, updated_at, is_historical) "
            "VALUES (?, 'message', 'parsed', ?, ?, ?)",
            (_FALLBACK_ID, now, now, False),
        )
        conn.execute(
            "INSERT INTO messages "
            "(id, content, raw_content, source, posted_at, received_at) "
            "VALUES (?, 'c', 'rc', 'whop', ?, ?)",
            (_FALLBACK_ID, _FALLBACK_POSTED_AT, _FALLBACK_POSTED_AT),
        )
        conn.commit()
    finally:
        conn.close()


def _read_posted_at(db_path: Path) -> dict[str, str]:
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute("SELECT id, posted_at FROM messages ORDER BY id").fetchall()
    finally:
        conn.close()
    return {row[0]: row[1] for row in rows}


@pytest.mark.asyncio
async def test_shift_migration_round_trip(tmp_path: Path) -> None:
    db_file = tmp_path / "shift.db"
    sync_url = f"sqlite:///{db_file}"
    cfg = _alembic_cfg(sync_url)

    # 1. Apply schema up to (but not including) the shift migration.
    await asyncio.to_thread(command.upgrade, cfg, _PREV_HEAD)

    # 2. Seed known rows.
    _seed_rows(db_file)
    original = _read_posted_at(db_file)
    assert set(original) == {"t1", "t2", "t3", _FALLBACK_ID}

    # 3. Apply the shift (upgrade to head).
    await asyncio.to_thread(command.upgrade, cfg, "head")
    after_upgrade = _read_posted_at(db_file)

    # SQLite's datetime(..., '-8 hours') returns 'YYYY-MM-DD HH:MM:SS' (no tz suffix).
    # That's the storage format SQLAlchemy reads back into a tz-aware datetime via
    # its DateTime(timezone=True) adapter.
    expected = {task_id: expected_str for task_id, _orig, expected_str in _FIXTURES}
    # The fallback row (posted_at == received_at) must be untouched by the upgrade.
    expected[_FALLBACK_ID] = _FALLBACK_POSTED_AT
    assert after_upgrade == expected, (
        f"upgrade did not shift -8h as expected:\n  got      {after_upgrade}\n  expected {expected}"
    )
    assert after_upgrade[_FALLBACK_ID] == _FALLBACK_POSTED_AT, (
        "upgrade incorrectly shifted the parse-failure fallback row "
        f"(posted_at == received_at): got {after_upgrade[_FALLBACK_ID]!r}, "
        f"expected {_FALLBACK_POSTED_AT!r} (unchanged)"
    )

    # 4. Reverse: downgrade by one revision and confirm we get the originals back.
    await asyncio.to_thread(command.downgrade, cfg, _PREV_HEAD)
    after_downgrade = _read_posted_at(db_file)

    # downgrade applies '+8 hours' to the already-shifted values.
    # Compare on parsed datetimes to be tolerant of trailing-zero / tz-suffix
    # formatting differences between the seeded ISO string and SQLite's output.
    def _parse(s: str) -> datetime:
        # Strip trailing '+00:00' or 'Z' if present — SQLite's datetime() drops it.
        s = s.replace("Z", "").rstrip()
        if s.endswith("+00:00"):
            s = s[: -len("+00:00")].rstrip()
        return datetime.fromisoformat(s)

    for task_id, original_str, _expected_str in _FIXTURES:
        assert _parse(after_downgrade[task_id]) == _parse(original_str), (
            f"downgrade did not restore {task_id}: "
            f"got {after_downgrade[task_id]!r}, expected {original_str!r}"
        )

    # The fallback row must STILL be unchanged after downgrade
    # (the WHERE filter excludes it from both directions).
    assert _parse(after_downgrade[_FALLBACK_ID]) == _parse(_FALLBACK_POSTED_AT), (
        "downgrade incorrectly shifted the parse-failure fallback row "
        f"(posted_at == received_at): got {after_downgrade[_FALLBACK_ID]!r}, "
        f"expected {_FALLBACK_POSTED_AT!r} (unchanged)"
    )
