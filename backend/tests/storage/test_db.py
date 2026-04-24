"""Tests for storage/db.py: engine factory, session factory, session_scope."""
from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.orm import Mapped, mapped_column

from app.storage.db import Base, create_engine, make_session_factory, session_scope


# ---------------------------------------------------------------------------
# A throwaway ORM table used only in test_session_scope_commits_simple_sql
# ---------------------------------------------------------------------------
class _Counter(Base):
    __tablename__ = "test_counter"
    __table_args__ = {"extend_existing": True}

    id: Mapped[int] = mapped_column(primary_key=True)
    value: Mapped[int] = mapped_column(default=0)


# ---------------------------------------------------------------------------
# Engine tests
# ---------------------------------------------------------------------------
class TestCreateEngine:
    def test_create_engine_default_uses_settings(self) -> None:
        """Engine created without an explicit URL must use the settings DATABASE_URL."""
        from app.core.config import get_settings

        engine = create_engine()
        expected = get_settings().database_url
        assert str(engine.url) == expected

    def test_create_engine_in_memory(self) -> None:
        """Passing an in-memory URL must produce a working async engine."""
        engine = create_engine("sqlite+aiosqlite:///:memory:")
        assert "memory" in str(engine.url)


# ---------------------------------------------------------------------------
# Session scope test
# ---------------------------------------------------------------------------
@pytest_asyncio.fixture
async def in_memory_engine_local():  # type: ignore[return]
    """Isolated in-memory engine for this test module."""
    engine = create_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    try:
        yield engine
    finally:
        await engine.dispose()


class TestSessionScope:
    async def test_session_scope_commits_simple_sql(self, in_memory_engine_local) -> None:  # type: ignore[no-untyped-def]
        """Insert a row via session_scope and verify it's readable in a new session."""
        factory = make_session_factory(in_memory_engine_local)

        async with session_scope(factory) as session:
            session.add(_Counter(id=1, value=42))

        # Read back in a separate session
        async with session_scope(factory) as session:
            result = await session.execute(text("SELECT value FROM test_counter WHERE id = 1"))
            row = result.scalar_one()
        assert row == 42

    async def test_session_scope_rollback_on_exception(self, in_memory_engine_local) -> None:  # type: ignore[no-untyped-def]
        """session_scope must roll back when an exception is raised inside the block."""
        factory = make_session_factory(in_memory_engine_local)

        with pytest.raises(ValueError):
            async with session_scope(factory) as session:
                session.add(_Counter(id=2, value=99))
                raise ValueError("intentional error")

        # Row should not have been committed
        async with session_scope(factory) as session:
            result = await session.execute(text("SELECT COUNT(*) FROM test_counter WHERE id = 2"))
            count = result.scalar_one()
        assert count == 0
