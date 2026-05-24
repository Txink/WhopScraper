# Task 1: Schema + Migration

**Files:**
- Modify: `backend/app/storage/schema.py`
- Create: `backend/alembic/versions/<rev>_alerts_and_manual_orders.py` (rev id from `uv run alembic revision`)
- Test: `backend/tests/storage/test_alerts_schema.py`

## Steps

- [ ] **Step 1: Write the failing test**

Create `backend/tests/storage/test_alerts_schema.py`:

```python
"""Schema-level smoke tests for the alerts + manual-orders migration."""
from __future__ import annotations

import pytest
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import AsyncEngine

from app.storage import schema  # noqa: F401 — register ORM


@pytest.mark.asyncio
async def test_tasks_has_source_and_last_replaced_at(engine: AsyncEngine) -> None:
    async with engine.connect() as conn:
        cols = await conn.run_sync(lambda c: {c.name for c in inspect(c).get_columns("tasks")})
    assert "source" in cols
    assert "last_replaced_at" in cols


@pytest.mark.asyncio
async def test_alerts_table_columns(engine: AsyncEngine) -> None:
    async with engine.connect() as conn:
        cols = await conn.run_sync(lambda c: {c["name"] for c in inspect(c).get_columns("alerts")})
    expected = {
        "id", "ticker", "symbol", "condition_type", "operator", "threshold",
        "pct_change_baseline", "volume_window", "repeat_mode", "cooldown_seconds",
        "enabled", "note", "created_at", "last_triggered_at", "trigger_count",
    }
    assert expected <= cols


@pytest.mark.asyncio
async def test_alert_events_table_columns(engine: AsyncEngine) -> None:
    async with engine.connect() as conn:
        cols = await conn.run_sync(lambda c: {c["name"] for c in inspect(c).get_columns("alert_events")})
    expected = {
        "id", "alert_id", "triggered_at", "ticker", "symbol",
        "snapshot_price", "snapshot_pct", "snapshot_volume", "message",
    }
    assert expected <= cols
```

If `engine` fixture isn't already defined in `tests/conftest.py`, add it:

```python
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine, AsyncEngine
from app.storage.db import Base


@pytest_asyncio.fixture
async def engine() -> AsyncEngine:
    eng = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd backend
uv run pytest tests/storage/test_alerts_schema.py -v
```

Expected: 3 failures — column / table not found.

- [ ] **Step 3: Add columns + new tables in `schema.py`**

Append two new column declarations to `TaskRow` (after `account_id`):

```python
    # Origin of the order. "signal" = whop-driven via parser/trader pipeline;
    # "manual" = submitted by user via the trading panel (no Message /
    # Instruction rows). NULL for legacy rows (pre-migration); treated as
    # "signal" by code paths that branch on this.
    source: Mapped[str | None] = mapped_column(String, nullable=True)
    # Most recent successful replace_order time. NULL until the order has
    # been modified at least once via PATCH /api/orders/{id}.
    last_replaced_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
```

Append two new `Base` subclasses at the bottom of `schema.py`:

```python
# ---------------------------------------------------------------------------
# alerts — per-ticker user-defined price / pct_change / volume watchers
# evaluated by AlertEngine against LongPort quote pushes.
# ---------------------------------------------------------------------------


class AlertRow(Base):
    __tablename__ = "alerts"
    __table_args__ = (
        Index("idx_alerts_ticker_enabled", "ticker", "enabled"),
        Index("idx_alerts_symbol_enabled", "symbol", "enabled"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(String, nullable=False)
    symbol: Mapped[str] = mapped_column(String, nullable=False)
    condition_type: Mapped[str] = mapped_column(String, nullable=False)
    operator: Mapped[str] = mapped_column(String, nullable=False)
    threshold: Mapped[float] = mapped_column(nullable=False)
    pct_change_baseline: Mapped[str | None] = mapped_column(String, nullable=True)
    volume_window: Mapped[str | None] = mapped_column(String, nullable=True)
    repeat_mode: Mapped[str] = mapped_column(String, nullable=False)
    cooldown_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=300)
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("1")
    )
    note: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    last_triggered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    trigger_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class AlertEventRow(Base):
    __tablename__ = "alert_events"
    __table_args__ = (
        Index("idx_alert_events_alert_ts", "alert_id", "triggered_at"),
        Index("idx_alert_events_ticker_ts", "ticker", "triggered_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    alert_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("alerts.id", ondelete="CASCADE"), nullable=False
    )
    triggered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    ticker: Mapped[str] = mapped_column(String, nullable=False)
    symbol: Mapped[str] = mapped_column(String, nullable=False)
    snapshot_price: Mapped[float] = mapped_column(nullable=False)
    snapshot_pct: Mapped[float | None] = mapped_column(nullable=True)
    snapshot_volume: Mapped[float | None] = mapped_column(nullable=True)
    message: Mapped[str] = mapped_column(String, nullable=False)
```

- [ ] **Step 4: Generate + edit Alembic migration**

```bash
cd backend
uv run alembic revision -m "alerts and manual orders"
```

Open the generated file and replace `upgrade()` / `downgrade()` with:

```python
def upgrade() -> None:
    # tasks new columns
    op.add_column("tasks", sa.Column("source", sa.String(), nullable=True))
    op.add_column(
        "tasks",
        sa.Column("last_replaced_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "alerts",
        sa.Column("id", sa.Integer(), autoincrement=True, primary_key=True),
        sa.Column("ticker", sa.String(), nullable=False),
        sa.Column("symbol", sa.String(), nullable=False),
        sa.Column("condition_type", sa.String(), nullable=False),
        sa.Column("operator", sa.String(), nullable=False),
        sa.Column("threshold", sa.Float(), nullable=False),
        sa.Column("pct_change_baseline", sa.String(), nullable=True),
        sa.Column("volume_window", sa.String(), nullable=True),
        sa.Column("repeat_mode", sa.String(), nullable=False),
        sa.Column("cooldown_seconds", sa.Integer(), nullable=False, server_default="300"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("note", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_triggered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("trigger_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index("idx_alerts_ticker_enabled", "alerts", ["ticker", "enabled"])
    op.create_index("idx_alerts_symbol_enabled", "alerts", ["symbol", "enabled"])

    op.create_table(
        "alert_events",
        sa.Column("id", sa.Integer(), autoincrement=True, primary_key=True),
        sa.Column(
            "alert_id",
            sa.Integer(),
            sa.ForeignKey("alerts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("triggered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ticker", sa.String(), nullable=False),
        sa.Column("symbol", sa.String(), nullable=False),
        sa.Column("snapshot_price", sa.Float(), nullable=False),
        sa.Column("snapshot_pct", sa.Float(), nullable=True),
        sa.Column("snapshot_volume", sa.Float(), nullable=True),
        sa.Column("message", sa.String(), nullable=False),
    )
    op.create_index("idx_alert_events_alert_ts", "alert_events", ["alert_id", "triggered_at"])
    op.create_index("idx_alert_events_ticker_ts", "alert_events", ["ticker", "triggered_at"])


def downgrade() -> None:
    op.drop_index("idx_alert_events_ticker_ts", "alert_events")
    op.drop_index("idx_alert_events_alert_ts", "alert_events")
    op.drop_table("alert_events")
    op.drop_index("idx_alerts_symbol_enabled", "alerts")
    op.drop_index("idx_alerts_ticker_enabled", "alerts")
    op.drop_table("alerts")
    with op.batch_alter_table("tasks") as batch:
        batch.drop_column("last_replaced_at")
        batch.drop_column("source")
```

Set `down_revision` to the latest pre-existing revision (currently `d250c4f32ccf` — verify with `uv run alembic heads`).

- [ ] **Step 5: Verify tests pass**

```bash
cd backend
uv run pytest tests/storage/test_alerts_schema.py -v
uv run mypy app
uv run ruff check . && uv run ruff format --check .
```

Expected: 3 passed; mypy clean; ruff clean.

- [ ] **Step 6: Verify migration applies + reverts cleanly**

```bash
cd backend
uv run alembic upgrade head
uv run alembic downgrade -1
uv run alembic upgrade head
```

Expected: each step completes without errors.

- [ ] **Step 7: Commit**

```bash
git add backend/app/storage/schema.py backend/alembic/versions/*alerts_and_manual_orders.py \
        backend/tests/storage/test_alerts_schema.py backend/tests/conftest.py
git commit -m "$(cat <<'EOF'
feat(schema): alerts + manual-orders migration

Adds tasks.source / tasks.last_replaced_at columns plus new alerts +
alert_events tables. Backs the trading-panel and alerts subsystems
from the 2026-05-24 spec.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```
