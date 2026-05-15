"""Tests for the v2 schema migration script (``migrate_pairs_v2``).

The test fixture's ``session_factory`` produces the v2 schema directly
(via ``Base.metadata.create_all``), so we exercise the migration's
no-op path on a freshly-created v2 DB plus the additive-column path on a
fresh DB with the t_pair_tags column manually dropped.

End-to-end "pre-v2 → v2" testing (TEXT id → INTEGER PK + tag backfill)
is exercised in CI against a captured pre-v2 SQLite snapshot rather than
in this unit test, because reconstructing the pre-v2 schema in code
duplicates the migration's intent.
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.storage.migrate_pairs_v2 import migrate


async def test_v2_migration_is_noop_on_fresh_v2_db(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """On a fresh v2 schema the migration should add nothing, recreate
    nothing, and report zero counters across the board."""
    async with session_factory() as session:
        summary = await migrate(session)
    # Fresh v2 db already has t_pair_tags and profit columns and an
    # INTEGER PK, so every counter should stay at 0.
    assert summary == {
        "broker_exec_tag_added": 0,
        "pair_profit_added": 0,
        "pairs_migrated": 0,
        "broker_exec_tags_filled": 0,
    }


async def test_v2_migration_adds_tag_column_when_missing(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """If broker_executions ever lacks t_pair_tags (e.g. a partial prior
    run), the additive ALTER fires and re-derives tags from existing pairs.
    Simulated here by dropping the column manually."""
    async with session_factory() as session:
        await session.execute(
            text(
                "CREATE TABLE broker_executions_no_tag ("
                " order_id TEXT PRIMARY KEY,"
                " account_id TEXT NOT NULL,"
                " task_id TEXT,"
                " symbol TEXT NOT NULL,"
                " ticker TEXT NOT NULL,"
                " side TEXT NOT NULL,"
                " qty INTEGER NOT NULL,"
                " price REAL NOT NULL,"
                " ts DATETIME NOT NULL,"
                " synced_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP"
                ")"
            )
        )
        await session.execute(text("DROP TABLE broker_executions"))
        await session.execute(
            text("ALTER TABLE broker_executions_no_tag RENAME TO broker_executions")
        )
        await session.commit()

        summary = await migrate(session)
    assert summary["broker_exec_tag_added"] == 1
