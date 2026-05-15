"""One-shot migration: pre-v2 → v2做T schema.

Background
----------
The pre-v2 schema:
  - ``t_pairs.id`` was a UUID string PK, ``account_id`` nullable.
  - ``broker_executions`` had no ``t_pair_tags``; "which pair contains this
    trade" was answered by scanning every pair's JSON allocations.
  - ``t_pairs.profit`` did not exist; clients computed it on the fly from
    trade prices.

The v2 schema (matches ``schema.py``):
  - ``t_pairs.id`` is a SQLite-native autoincrement INTEGER; ``account_id``
    required (legacy rows with NULL are dropped).
  - ``broker_executions.t_pair_tags`` is a JSON array of
    ``[pair_id, allocated_qty]`` so pending-做T SQL is one-table.
  - ``t_pairs.profit`` is computed at pair create/extend time and stored.

What this script does
---------------------
1. ``ALTER TABLE broker_executions ADD COLUMN t_pair_tags TEXT NOT NULL
   DEFAULT '[]'`` — additive, safe to repeat (the script no-ops if the
   column already exists).
2. ``ALTER TABLE t_pairs ADD COLUMN profit REAL NOT NULL DEFAULT 0.0`` —
   same idempotency.
3. If ``t_pairs.id`` is still a TEXT column (pre-v2 UUIDs), recreate the
   table with the new shape:
     - Read existing rows ordered by ``created_at``.
     - Drop rows whose ``account_id`` is NULL (legacy, no migration target).
     - Assign sequential INTEGER ids starting at 1.
     - Build a UUID→INT map.
4. Backfill the new table:
     - For each surviving pair, compute ``profit`` from
       ``broker_executions.price`` of the referenced fills.
     - INSERT INTO ``t_pairs_new`` with the new INTEGER id.
5. Backfill ``broker_executions.t_pair_tags`` by walking each migrated
   pair's allocations and writing ``[[new_id, qty], ...]`` per fill.
6. Drop ``t_pairs`` (old), rename ``t_pairs_new`` → ``t_pairs``, create
   the v2 index.

Idempotent: a second run finds the v2 shape already in place, sees the
``t_pair_tags`` column already exists, and exits without further changes.

Run with:
    cd backend && uv run python -m app.storage.migrate_pairs_v2
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections import defaultdict
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.storage.db import create_engine, make_session_factory

logger = logging.getLogger(__name__)


async def _column_exists(
    session: AsyncSession, table: str, column: str
) -> bool:
    """SQLite-flavored column probe via ``PRAGMA table_info``."""
    rows = (await session.execute(text(f"PRAGMA table_info({table})"))).all()
    return any(r[1] == column for r in rows)


async def _column_type(
    session: AsyncSession, table: str, column: str
) -> str | None:
    rows = (await session.execute(text(f"PRAGMA table_info({table})"))).all()
    for r in rows:
        if r[1] == column:
            return str(r[2]).upper()
    return None


async def _add_broker_exec_tag_column(session: AsyncSession) -> bool:
    """Step 1. Returns True if the column was added (False if it already existed)."""
    if await _column_exists(session, "broker_executions", "t_pair_tags"):
        return False
    await session.execute(
        text(
            "ALTER TABLE broker_executions "
            "ADD COLUMN t_pair_tags TEXT NOT NULL DEFAULT '[]'"
        )
    )
    return True


async def _add_pair_profit_column(session: AsyncSession) -> bool:
    """Step 2. Returns True if the column was added."""
    if await _column_exists(session, "t_pairs", "profit"):
        return False
    await session.execute(
        text("ALTER TABLE t_pairs ADD COLUMN profit REAL NOT NULL DEFAULT 0.0")
    )
    return True


async def _needs_pk_recreate(session: AsyncSession) -> bool:
    """``t_pairs.id`` is TEXT in pre-v2, INTEGER in v2."""
    t = await _column_type(session, "t_pairs", "id")
    if t is None:
        # Table doesn't exist at all — create_all already produced the v2
        # shape, nothing to do here.
        return False
    return "INT" not in t


def _compute_profit(
    buys: list[dict[str, Any]],
    sells: list[dict[str, Any]],
    price_by_trade_id: dict[str, float],
) -> float:
    """Same formula as ``pairMath.ts``:
    profit = matched_qty * (avg_sell_price - avg_buy_price)
    where matched_qty = min(sum_buy_qty, sum_sell_qty).
    """
    buy_qty_total = sum(int(b.get("qty", 0)) for b in buys)
    sell_qty_total = sum(int(s.get("qty", 0)) for s in sells)
    if buy_qty_total <= 0 or sell_qty_total <= 0:
        return 0.0
    buy_cost = sum(
        int(b.get("qty", 0)) * float(price_by_trade_id.get(b.get("trade_id", ""), 0.0))
        for b in buys
    )
    sell_rev = sum(
        int(s.get("qty", 0)) * float(price_by_trade_id.get(s.get("trade_id", ""), 0.0))
        for s in sells
    )
    avg_buy = buy_cost / buy_qty_total
    avg_sell = sell_rev / sell_qty_total
    matched = min(buy_qty_total, sell_qty_total)
    return matched * (avg_sell - avg_buy)


async def _recreate_pairs_table(
    session: AsyncSession,
) -> dict[str, int]:
    """Steps 3-6. Returns {old_uuid: new_int_id} for the migrated pairs."""
    # Pull all old pair rows in created_at order so the new INTEGER ids
    # match the user's mental model of "T-1 was created first".
    old_rows = (
        await session.execute(
            text(
                "SELECT id, account_id, ticker, symbol, "
                "buys_json, sells_json, created_at, updated_at "
                "FROM t_pairs "
                "WHERE account_id IS NOT NULL "
                "ORDER BY created_at, id"
            )
        )
    ).all()

    # Pull every broker_execution's price so we can compute pair profit
    # without one-query-per-pair.
    price_rows = (
        await session.execute(
            text("SELECT order_id, price FROM broker_executions")
        )
    ).all()
    price_by_trade_id: dict[str, float] = {r[0]: float(r[1]) for r in price_rows}

    # Build the new table. We deliberately don't use CREATE TABLE … AS
    # because we need control over column types + the AUTOINCREMENT.
    await session.execute(
        text(
            "CREATE TABLE t_pairs_new ("
            " id INTEGER PRIMARY KEY AUTOINCREMENT,"
            " account_id TEXT NOT NULL,"
            " ticker TEXT NOT NULL,"
            " symbol TEXT,"
            " buys_json TEXT NOT NULL,"
            " sells_json TEXT NOT NULL,"
            " profit REAL NOT NULL DEFAULT 0.0,"
            " created_at DATETIME NOT NULL,"
            " updated_at DATETIME NOT NULL"
            ")"
        )
    )

    # Assign sequential ids starting at 1. Explicit id makes the
    # uuid→int mapping deterministic and lets us follow up by writing
    # broker_executions.t_pair_tags using those ids.
    id_map: dict[str, int] = {}
    for new_id, row in enumerate(old_rows, start=1):
        old_id = str(row[0])
        account_id = str(row[1])
        ticker = str(row[2])
        symbol = row[3]
        buys_raw = row[4]
        sells_raw = row[5]
        created_at = row[6]
        updated_at = row[7]

        # Old rows store JSON as TEXT; new schema expects parsed list of
        # dicts. Decode then re-encode so we can also compute profit.
        buys = json.loads(buys_raw) if isinstance(buys_raw, str) else (buys_raw or [])
        sells = json.loads(sells_raw) if isinstance(sells_raw, str) else (sells_raw or [])
        profit = _compute_profit(buys, sells, price_by_trade_id)

        await session.execute(
            text(
                "INSERT INTO t_pairs_new "
                "(id, account_id, ticker, symbol, buys_json, sells_json, profit, "
                " created_at, updated_at) "
                "VALUES "
                "(:id, :account_id, :ticker, :symbol, :buys_json, :sells_json, "
                " :profit, :created_at, :updated_at)"
            ),
            {
                "id": new_id,
                "account_id": account_id,
                "ticker": ticker,
                "symbol": symbol,
                "buys_json": json.dumps(buys),
                "sells_json": json.dumps(sells),
                "profit": profit,
                "created_at": created_at,
                "updated_at": updated_at,
            },
        )
        id_map[old_id] = new_id

    # Swap tables. PRAGMA foreign_keys=OFF is unnecessary — no FKs reference
    # t_pairs.id (the relationship is denormalized in broker_executions.t_pair_tags).
    await session.execute(text("DROP TABLE t_pairs"))
    await session.execute(text("ALTER TABLE t_pairs_new RENAME TO t_pairs"))
    await session.execute(
        text(
            "CREATE INDEX IF NOT EXISTS idx_t_pairs_account_ticker "
            "ON t_pairs (account_id, ticker)"
        )
    )
    return id_map


async def _backfill_broker_exec_tags(
    session: AsyncSession,
) -> int:
    """Step 5 (run after the PK swap). Re-derive t_pair_tags from the
    fresh t_pairs table — INTEGER ids and parsed JSON allocations are
    already in place. Returns the number of broker_execution rows touched.
    """
    pair_rows = (
        await session.execute(
            text("SELECT id, buys_json, sells_json FROM t_pairs")
        )
    ).all()

    # trade_id -> list of [pair_id, qty]
    tags_by_trade: dict[str, list[list[Any]]] = defaultdict(list)
    for pair_id, buys_raw, sells_raw in pair_rows:
        buys = json.loads(buys_raw) if isinstance(buys_raw, str) else (buys_raw or [])
        sells = json.loads(sells_raw) if isinstance(sells_raw, str) else (sells_raw or [])
        for entry in buys + sells:
            tid = entry.get("trade_id")
            qty = int(entry.get("qty", 0))
            if tid and qty:
                tags_by_trade[str(tid)].append([int(pair_id), qty])

    touched = 0
    for tid, tags in tags_by_trade.items():
        result = await session.execute(
            text("UPDATE broker_executions SET t_pair_tags = :tags WHERE order_id = :tid"),
            {"tags": json.dumps(tags), "tid": tid},
        )
        touched += result.rowcount or 0
    return touched


async def migrate(session: AsyncSession) -> dict[str, int]:
    """Run the full migration in one transaction. Returns counter summary."""
    summary: dict[str, int] = {
        "broker_exec_tag_added": 0,
        "pair_profit_added": 0,
        "pairs_migrated": 0,
        "broker_exec_tags_filled": 0,
    }

    if await _add_broker_exec_tag_column(session):
        summary["broker_exec_tag_added"] = 1

    if await _add_pair_profit_column(session):
        summary["pair_profit_added"] = 1

    if await _needs_pk_recreate(session):
        id_map = await _recreate_pairs_table(session)
        summary["pairs_migrated"] = len(id_map)
        # Tags must come AFTER the PK swap so we read the freshly-assigned
        # INTEGER ids back out of t_pairs (and so a partial-failure repeat
        # rebuilds tags from the source of truth).
        summary["broker_exec_tags_filled"] = await _backfill_broker_exec_tags(session)
    else:
        # If PK was already INTEGER but tags column was missing (rare —
        # would imply someone hand-edited the schema), rebuild tags from
        # the existing v2 table.
        if summary["broker_exec_tag_added"]:
            summary["broker_exec_tags_filled"] = await _backfill_broker_exec_tags(session)

    await session.commit()
    return summary


async def _main() -> None:
    logging.basicConfig(level=logging.INFO)
    from app.core.config import get_settings

    settings = get_settings()
    engine = create_engine(settings.database_url)
    factory = make_session_factory(engine)
    try:
        async with factory() as session:
            summary = await migrate(session)
        logger.info("v2 migration complete: %s", summary)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(_main())
