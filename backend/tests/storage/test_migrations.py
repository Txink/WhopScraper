"""Alembic migration integration test —— verify head migration produces the expected schema."""

import asyncio
from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import create_async_engine

from alembic import command
from app.storage import schema  # noqa: F401  ensure tables register
from app.storage.db import Base

BACKEND_DIR = Path(__file__).resolve().parents[2]


def _alembic_cfg(url: str) -> Config:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    cfg.set_main_option("sqlalchemy.url", url)
    return cfg


def _run_upgrade(cfg: Config) -> None:
    """Run alembic upgrade head in a thread-safe, sync context."""
    command.upgrade(cfg, "head")


@pytest.mark.asyncio
async def test_upgrade_head_creates_expected_tables(tmp_path):
    db_file = tmp_path / "mig.db"
    async_url = f"sqlite+aiosqlite:///{db_file}"
    sync_url = f"sqlite:///{db_file}"

    # Apply migrations via sync alembic API in a thread to avoid conflicting
    # with the already-running pytest-asyncio event loop.
    cfg = _alembic_cfg(sync_url)
    await asyncio.to_thread(_run_upgrade, cfg)

    # Inspect created DB using ASYNC engine
    engine = create_async_engine(async_url)
    try:
        async with engine.connect() as conn:
            tables = await conn.run_sync(lambda sc: set(inspect(sc).get_table_names()))
    finally:
        await engine.dispose()

    expected = {"tasks", "messages", "instructions", "push_events", "positions", "alembic_version"}
    assert expected.issubset(tables), f"missing tables: {expected - tables}"


@pytest.mark.asyncio
async def test_migration_matches_base_metadata(tmp_path):
    """Compare migration-created tables to Base.metadata schema."""
    db_file = tmp_path / "mig.db"
    cfg = _alembic_cfg(f"sqlite:///{db_file}")
    await asyncio.to_thread(_run_upgrade, cfg)

    async_engine = create_async_engine(f"sqlite+aiosqlite:///{db_file}")
    try:
        async with async_engine.connect() as conn:
            mig_tables = await conn.run_sync(
                lambda sc: {
                    t: set(c["name"] for c in inspect(sc).get_columns(t))
                    for t in ("tasks", "messages", "instructions", "push_events", "positions")
                }
            )
    finally:
        await async_engine.dispose()

    # Only compare the 5 spec tables (Base.metadata may also contain test-only
    # tables such as _Counter defined in test_db.py).
    _SPEC_TABLES = {"tasks", "messages", "instructions", "push_events", "positions"}
    expected = {
        table.name: {col.name for col in table.columns}
        for table in Base.metadata.tables.values()
        if table.name in _SPEC_TABLES
    }
    for name, cols in expected.items():
        assert mig_tables[name] == cols, (
            f"column mismatch on {name}: expected {cols}, got {mig_tables[name]}"
        )
