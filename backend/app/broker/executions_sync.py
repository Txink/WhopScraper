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

Both modes iterate ≤ ``_CHUNK_DAYS`` (90-day) windows because LongBridge's
``history_executions`` / ``history_orders`` reject wider single calls.
See ``knowledge/longbridge-api-limits.md``.

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

#: LongBridge's per-call window cap on ``history_executions`` /
#: ``history_orders``. Wider single calls are rejected. We chunk
#: backward in increments no larger than this.
_CHUNK_DAYS = 90


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


async def _fetch_and_upsert_window(
    session: AsyncSession,
    broker: _BrokerWithExecutions,
    *,
    account_id: str,
    ticker: str | None,
    start: datetime,
    end: datetime,
) -> int:
    """Fetch a single ≤ 90-day window and upsert. Returns rows persisted.

    Broker errors are logged and treated as an empty window — the UI
    gets stale data, but doesn't 502 just because the SDK hiccuped.
    """
    try:
        rows = broker.history_executions(
            ticker=ticker, start_at=start, end_at=end
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "history_executions fetch failed (%s → %s): %s", start, end, exc
        )
        return 0
    if not rows:
        return 0
    return await repo.upsert_broker_executions(
        session, account_id=account_id, rows=rows
    )


async def _sync_chunked(
    session: AsyncSession,
    broker: _BrokerWithExecutions,
    *,
    account_id: str,
    ticker: str | None,
    total_days: int,
    stop_on_empty: bool = False,
) -> int:
    """Walk backward in ≤ ``_CHUNK_DAYS`` windows, upsert each chunk.

    ``stop_on_empty`` short-circuits the moment a window returns zero
    rows — used by first-time backfill when an account opened mid-horizon
    and there's no point asking the broker for years before that.
    """
    now = datetime.now(UTC)
    floor = now - timedelta(days=total_days)
    total = 0
    end = now
    while end > floor:
        start = max(end - timedelta(days=_CHUNK_DAYS), floor)
        persisted = await _fetch_and_upsert_window(
            session,
            broker,
            account_id=account_id,
            ticker=ticker,
            start=start,
            end=end,
        )
        if persisted == 0 and stop_on_empty:
            break
        total += persisted
        end = start
    return total


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
    the SDK hiccuped.

    Iterates 90-day chunks when ``days`` exceeds the broker's per-call cap.
    """
    account_id = broker.account_id
    if not account_id:
        return 0
    return await _sync_chunked(
        session,
        broker,
        account_id=account_id,
        ticker=ticker,
        total_days=days,
    )


async def sync_broker_executions_incremental(
    session: AsyncSession,
    broker: _BrokerWithExecutions,
    *,
    ticker: str | None = None,
    fallback_days: int = 730,
) -> int:
    """Pull broker fills for the detail-pane trade list.

    Two paths, gated on ``positions.history_synced`` for (account, ticker):

    1. ``history_synced = True``: we've previously walked the full
       ``fallback_days`` horizon for this ticker. Just catch new fills
       since ``MAX(ts)`` in DB (chunked if the gap exceeds 90 days).

    2. ``history_synced = False`` (default) OR no positions row at all:
       iterate 90-day chunks back across the full ``fallback_days``
       horizon (no early stop — a sparse trader can have empty quarters
       mid-horizon, and stopping on the first quiet chunk would miss
       older fills). When ``positions.restore_pair_tags`` is set (after
       a broker_executions wipe), rebuilds ``t_pair_tags`` from ``t_pairs``
       before clearing that flag. Sets ``positions.history_synced = True``
       for all rows matching (account, ticker) after the walk completes so
       subsequent opens take the cheap path.

    Why not use ``MAX(ts)`` as the "fully synced" anchor? Because the
    ``/api/broker/today_executions`` endpoint (Day P/L on dashboard load)
    writes a narrow 2-day window across all tickers. Even one row from
    that path would otherwise be misread as "we have history for this
    ticker" and the back-walk would never run. ``history_synced`` lives
    on ``positions``, written only after a deliberate full backfill.
    """
    account_id = broker.account_id
    if not account_id:
        return 0

    already_synced = False
    if ticker is not None:
        already_synced = await repo.is_position_history_synced(
            session, account_id=account_id, ticker=ticker
        )

    if already_synced:
        stmt = select(BrokerExecutionRow.ts).where(
            BrokerExecutionRow.account_id == account_id
        )
        if ticker is not None:
            stmt = stmt.where(BrokerExecutionRow.ticker == ticker)
        stmt = stmt.order_by(BrokerExecutionRow.ts.desc()).limit(1)
        result = await session.execute(stmt)
        latest_ts: datetime | None = result.scalar_one_or_none()
        # Default to a 1-day gap pull when the flag is set but the table
        # has no rows yet (cold cache after manual DELETE) — safer than
        # silently skipping the call.
        days = 1
        if latest_ts is not None:
            if latest_ts.tzinfo is None:
                latest_ts = latest_ts.replace(tzinfo=UTC)
            gap = datetime.now(UTC) - latest_ts
            days = max(1, math.ceil(gap.total_seconds() / 86400) + 1)
        return await _sync_chunked(
            session,
            broker,
            account_id=account_id,
            ticker=ticker,
            total_days=days,
        )

    # Full backfill path — walk the full horizon. Cost: ~8 broker calls
    # once per (account, ticker); subsequent opens take the cheap gap
    # path because history_synced flips to True below.
    persisted = await _sync_chunked(
        session,
        broker,
        account_id=account_id,
        ticker=ticker,
        total_days=fallback_days,
    )
    if ticker is not None:
        if await repo.position_needs_restore_pair_tags(
            session, account_id=account_id, ticker=ticker
        ):
            await repo.restore_pair_tags_from_pairs(
                session, account_id=account_id, ticker=ticker
            )
        await repo.mark_position_history_synced(
            session, account_id=account_id, ticker=ticker
        )
    return persisted


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
