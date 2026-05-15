"""Pull broker.history_executions → broker_executions table (account-scoped).

Source of truth for the detail-pane trade list. Distinct from the
trader's own task records — those only cover orders signal-station
submitted; manual fills placed via the LongBridge app / web would
otherwise never reach the UI.

Two sync modes:
- ``sync_broker_executions(days=N)``: pull last N days unconditionally.
  Used by today_executions (Day P/L) which always wants the same window.
- ``sync_broker_executions_incremental(ticker?)``: compute the since from
  ``MAX(ts)`` in DB (per account + optional ticker) and pull only the
  gap. First call falls back to a generous window. Used by the detail
  pane so reopening doesn't re-pull months of fills every time.

Idempotent: PK is order_id; upsert keeps qty / price / ts current.
"""

from __future__ import annotations

import logging
import math
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.storage import repo
from app.storage.schema import BrokerExecutionRow

logger = logging.getLogger(__name__)


class _BrokerWithExecutions(Protocol):
    """Minimal broker shape needed for the sync — keeps the function
    test-friendly (FakeBrokerClient + LongPortClient both satisfy)."""

    def history_executions(
        self,
        *,
        ticker: str | None = None,
        days: int = 30,
        start_at: datetime | None = None,
        end_at: datetime | None = None,
    ) -> list[dict[str, Any]]: ...

    @property
    def account_id(self) -> str: ...


async def sync_broker_executions(
    session: AsyncSession,
    broker: _BrokerWithExecutions,
    *,
    ticker: str | None = None,
    days: int = 30,
) -> int:
    """Pull last ``days`` of broker fills and upsert into the DB. Returns
    the number of rows persisted (after dedupe). Errors are logged and
    swallowed — the UI gets stale data, but doesn't 502 just because
    the SDK hiccuped."""
    account_id = broker.account_id
    if not account_id:
        return 0
    try:
        rows = broker.history_executions(ticker=ticker, days=days)
    except Exception as exc:  # noqa: BLE001
        logger.warning("history_executions sync failed: %s", exc)
        return 0
    return await repo.upsert_broker_executions(
        session, account_id=account_id, rows=rows
    )


async def sync_broker_executions_incremental(
    session: AsyncSession,
    broker: _BrokerWithExecutions,
    *,
    ticker: str | None = None,
    fallback_days: int = 730,
) -> int:
    """Pull only the gap since the latest known fill for this account
    (+ optional ticker).

    Two paths:

    1. DB has prior rows for this account+ticker: compute the gap from
       ``MAX(ts)`` and pull that window via the ``days`` argument.

    2. DB is empty (first-ever sync for this account+ticker): one wide
       call covering ``fallback_days`` (default 730 = 2 years). LongBridge
       accepts arbitrary ``start_at`` / ``end_at`` ranges; the per-call
       row cap (1000) is the only real ceiling, and for a per-ticker
       slice that's plenty — 1000 做T fills in 2 years on one stock is
       beyond the active-trader envelope. If a user ever exceeds it,
       they'd see truncation of the oldest fills.
    """
    account_id = broker.account_id
    if not account_id:
        return 0
    stmt = select(BrokerExecutionRow.ts).where(
        BrokerExecutionRow.account_id == account_id
    )
    if ticker is not None:
        stmt = stmt.where(BrokerExecutionRow.ticker == ticker)
    stmt = stmt.order_by(BrokerExecutionRow.ts.desc()).limit(1)
    result = await session.execute(stmt)
    latest_ts: datetime | None = result.scalar_one_or_none()

    if latest_ts is not None:
        if latest_ts.tzinfo is None:
            latest_ts = latest_ts.replace(tzinfo=UTC)
        gap = datetime.now(UTC) - latest_ts
        # Round up + 1 day cushion. Minimum 1 day (broker.history_executions
        # treats days <= 0 oddly; safer to always pull at least one day).
        days = max(1, math.ceil(gap.total_seconds() / 86400) + 1)
        return await sync_broker_executions(
            session, broker, ticker=ticker, days=days
        )

    # First-time backfill — single wide-range call.
    now = datetime.now(UTC)
    try:
        rows = broker.history_executions(
            ticker=ticker,
            start_at=now - timedelta(days=fallback_days),
            end_at=now,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("history_executions backfill failed: %s", exc)
        return 0
    return await repo.upsert_broker_executions(
        session, account_id=account_id, rows=rows
    )


async def latest_synced_at(
    session: AsyncSession,
    *,
    account_id: str,
    ticker: str | None = None,
) -> datetime | None:
    """``MAX(synced_at)`` across the executions slice. Used by the detail
    pane to surface "上次更新：xxx" — the moment of the most recent
    sync write, not the timestamp of the most recent FILL."""
    stmt = select(BrokerExecutionRow.synced_at).where(
        BrokerExecutionRow.account_id == account_id
    )
    if ticker is not None:
        stmt = stmt.where(BrokerExecutionRow.ticker == ticker)
    stmt = stmt.order_by(BrokerExecutionRow.synced_at.desc()).limit(1)
    return (await session.execute(stmt)).scalar_one_or_none()
