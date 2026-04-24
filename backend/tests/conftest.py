"""Shared test fixtures."""
from __future__ import annotations

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.storage.db import Base, create_engine


@pytest_asyncio.fixture
async def in_memory_engine() -> AsyncEngine:
    """Fresh in-memory async SQLite engine with Base.metadata.create_all()."""
    engine = create_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def session_factory(in_memory_engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(in_memory_engine, expire_on_commit=False)
