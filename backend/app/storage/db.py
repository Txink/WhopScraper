"""Async SQLAlchemy 2.x engine, session factory, and session_scope helper.

Usage
-----
**FastAPI dependency** (inject ``AsyncSession`` via ``Depends``)::

    from fastapi import Depends
    from sqlalchemy.ext.asyncio import AsyncSession
    from app.storage.db import make_session_factory, create_engine

    _engine = create_engine()
    _factory = make_session_factory(_engine)

    async def get_db() -> AsyncSession:
        async with session_scope(_factory) as session:
            yield session  # FastAPI closes it after the request

**Non-FastAPI call site** (event listeners, CLI scripts)::

    async with session_scope() as session:
        ...
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase


# ---------------------------------------------------------------------------
# ORM base – all ORM table classes must inherit from this.
# ---------------------------------------------------------------------------
class Base(DeclarativeBase):
    """Shared declarative base for all ORM models."""


# ---------------------------------------------------------------------------
# Engine factory
# ---------------------------------------------------------------------------
def create_engine(url: str | None = None) -> AsyncEngine:
    """Create an ``AsyncEngine``.

    Parameters
    ----------
    url:
        SQLAlchemy connection URL.  If *None*, the value is read from
        ``Settings.database_url`` (loaded from the environment / ``.env``).

    Returns
    -------
    AsyncEngine
    """
    if url is None:
        from app.core.config import get_settings

        url = get_settings().database_url

    return create_async_engine(url, echo=False)


# ---------------------------------------------------------------------------
# Session factory
# ---------------------------------------------------------------------------
def make_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Return an ``async_sessionmaker`` bound to *engine*.

    ``expire_on_commit=False`` prevents lazy-load errors after a ``commit()``.
    """
    return async_sessionmaker(engine, expire_on_commit=False)


# ---------------------------------------------------------------------------
# Session scope context manager
# ---------------------------------------------------------------------------
@asynccontextmanager
async def session_scope(
    factory: async_sessionmaker[AsyncSession] | None = None,
) -> AsyncIterator[AsyncSession]:
    """Async context manager that provides a transactional ``AsyncSession``.

    Commits on clean exit, rolls back on exception.

    Parameters
    ----------
    factory:
        An ``async_sessionmaker`` to use.  If *None*, a new engine is created
        from ``Settings.database_url`` and a default factory is used.
    """
    if factory is None:
        engine = create_engine()
        factory = make_session_factory(engine)

    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
