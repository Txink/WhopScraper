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

import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

# Project root: backend/app/storage/db.py → parents[3] → project root
_PROJECT_ROOT = Path(__file__).resolve().parents[3]


# ---------------------------------------------------------------------------
# ORM base – all ORM table classes must inherit from this.
# ---------------------------------------------------------------------------
class Base(DeclarativeBase):
    """Shared declarative base for all ORM models."""


def _resolve_sqlite_url(url: str) -> str:
    """Anchor relative SQLite paths to the project root, not CWD.

    Accepts URLs like:
      sqlite+aiosqlite:///./data/signals.db   -> sqlite+aiosqlite:////abs/path/data/signals.db
      sqlite+aiosqlite:///data/signals.db     -> sqlite+aiosqlite:////abs/path/data/signals.db
      sqlite+aiosqlite:///:memory:            -> unchanged
      sqlite+aiosqlite:////abs/path/db.sqlite -> unchanged (already absolute)

    Also creates the parent directory if it doesn't exist (so first-run with
    no existing data/ folder doesn't error out).
    """
    m = re.match(r"^(sqlite(?:\+\w+)?://)(/.*)$", url)
    if not m:
        return url
    scheme, raw_path = m.group(1), m.group(2)

    # Memory DBs and absolute file paths (//// prefix → leading slash retained) pass through
    if raw_path.startswith("/:memory:") or raw_path == "/:memory:":
        return url
    # Strip the leading slash that's part of the URL syntax
    candidate = raw_path[1:] if raw_path.startswith("/") else raw_path
    candidate = candidate.removeprefix("./")
    p = Path(candidate)
    if not p.is_absolute():
        p = (_PROJECT_ROOT / p).resolve()
    p.parent.mkdir(parents=True, exist_ok=True)
    return f"{scheme}/{p}"


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
        Relative SQLite paths are anchored to the project root (not CWD)
        and the parent directory is auto-created.

    Returns
    -------
    AsyncEngine
    """
    if url is None:
        from app.core.config import get_settings

        url = get_settings().database_url

    url = _resolve_sqlite_url(url)
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
