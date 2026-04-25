"""Alembic env.py —— async SQLite + SQLAlchemy 2.x.

Reads DATABASE_URL from app.core.config.get_settings().
Imports app.storage.schema so all Row classes register on Base.metadata
for autogenerate.
"""

from __future__ import annotations

import asyncio
import sys
from logging.config import fileConfig
from pathlib import Path

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from alembic import context

# ---------------------------------------------------------------------------
# Ensure ``backend/`` is on sys.path so ``import app`` works when alembic CLI
# is invoked from any working directory.
# ---------------------------------------------------------------------------
_BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

# ---------------------------------------------------------------------------
# Project imports (must come after sys.path fix above)
# ---------------------------------------------------------------------------
from app.core.config import get_settings  # noqa: E402
from app.storage import schema  # noqa: E402, F401  — registers all Row classes on Base.metadata
from app.storage.db import Base  # noqa: E402

# ---------------------------------------------------------------------------
# Alembic Config object — provides access to values in alembic.ini.
# ---------------------------------------------------------------------------
config = context.config

# Interpret the config file for Python logging.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Expose metadata for autogenerate support.
target_metadata = Base.metadata

# ---------------------------------------------------------------------------
# Resolve DATABASE_URL to an absolute path.
#
# Settings.database_url defaults to ``sqlite+aiosqlite:///./data/signals.db``
# which is a relative path resolved from the current working directory.  When
# the alembic CLI is invoked from ``backend/`` the parent ``data/`` dir does
# not exist there; the project-root ``data/`` dir does.  We normalise the URL
# so that it always points to ``<project-root>/data/signals.db`` regardless of
# cwd.
# ---------------------------------------------------------------------------
_PROJECT_ROOT = _BACKEND_DIR.parent  # one level up from backend/


def _resolve_url(url: str) -> str:
    """Expand a relative SQLite path in *url* to an absolute path.

    Only touches ``sqlite`` / ``sqlite+aiosqlite`` URLs whose path component
    starts with ``./`` or ``../``.  Other URLs are returned unchanged.
    """
    import re

    match = re.match(r"(sqlite(?:\+aiosqlite)?:///)(\.\.?/.*)", url)
    if not match:
        return url
    prefix, rel_path = match.groups()
    abs_path = (_PROJECT_ROOT / rel_path).resolve()
    abs_path.parent.mkdir(parents=True, exist_ok=True)
    return f"{prefix}{abs_path}"


def _get_url() -> str:
    """Return the database URL.

    Prefers ``sqlalchemy.url`` from alembic.ini / programmatic config (used by
    the test suite via ``cfg.set_main_option``), falling back to
    ``get_settings().database_url``.  Relative SQLite paths are expanded to
    absolute paths anchored at the project root.
    """
    cfg_url: str | None = config.get_main_option("sqlalchemy.url")
    # The ini template ships with a placeholder; treat it as absent.
    if cfg_url and not cfg_url.startswith("driver://"):
        return _resolve_url(cfg_url)
    return _resolve_url(get_settings().database_url)


# ---------------------------------------------------------------------------
# Offline mode
# ---------------------------------------------------------------------------
def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    Configures context with just a URL (no Engine / DBAPI needed).
    SQL DDL is emitted to stdout.
    """
    url = _get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


# ---------------------------------------------------------------------------
# Online (async) mode
# ---------------------------------------------------------------------------
def do_run_migrations(connection: Connection) -> None:
    """Synchronous callback used by connection.run_sync()."""
    context.configure(connection=connection, target_metadata=target_metadata)

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Create an async engine and run migrations against a live connection."""
    url = _get_url()
    # Ensure we use the async driver — convert plain sqlite:/// to sqlite+aiosqlite:///
    # (happens when the test suite passes a sync URL via cfg.set_main_option).
    if url.startswith("sqlite:///") and "+aiosqlite" not in url:
        url = url.replace("sqlite:///", "sqlite+aiosqlite:///", 1)
    connectable = create_async_engine(url, poolclass=pool.NullPool)

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    asyncio.run(run_async_migrations())


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
