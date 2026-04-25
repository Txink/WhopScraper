"""Shared test fixtures."""

from __future__ import annotations

from typing import Any

import pytest_asyncio
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.storage.db import Base, create_engine


@pytest_asyncio.fixture
async def in_memory_engine() -> AsyncEngine:
    """Fresh in-memory async SQLite engine with Base.metadata.create_all().

    SQLite disables foreign-key enforcement by default.  The ``connect`` event
    listener below runs ``PRAGMA foreign_keys=ON`` on every new connection so
    that ON DELETE CASCADE behaviour (and other FK constraints) work correctly
    in tests.
    """
    engine = create_engine("sqlite+aiosqlite:///:memory:")

    # Enable FK enforcement for SQLite.
    # aiosqlite wraps the driver connection in ``AsyncAdapt_aiosqlite_connection``
    # rather than exposing a plain ``sqlite3.Connection``, so we use the
    # generic ``cursor().execute()`` path that works for both the sync
    # (sqlite3.Connection) and async-adapted variants.
    @event.listens_for(engine.sync_engine, "connect")
    def _enable_foreign_keys(dbapi_conn: Any, _connection_record: object) -> None:
        # dbapi_conn is AsyncAdapt_aiosqlite_connection (aiosqlite) or
        # sqlite3.Connection (sync SQLite).  Both expose a cursor() method.
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def session_factory(in_memory_engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(in_memory_engine, expire_on_commit=False)
