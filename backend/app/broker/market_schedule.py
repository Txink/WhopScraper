"""Global market-schedule cache with 6h fatigue refresh.

Centralises trading-session windows and the recent trading-day calendar
so the rest of the project can ask "what state is HK in right now?" or
"what was the most recent US trading day before today?" without hitting
the broker SDK every time. The cache is refreshed at most once every
``REFRESH_FATIGUE_SECONDS`` to keep SDK call volume bounded; first call
after a process restart triggers an immediate refresh.

Lifecycle: one instance per broker (rebuilt during account-switch
reload). SubscriptionManager.attach() kicks off the initial refresh via
:meth:`maybe_refresh` so the schedule is warm by the time the first
quote push arrives.

Other consumers (``LongPortClient._market_state_for``,
``executions_sync``, any future module needing market-hours) call
:meth:`state_for` / :meth:`is_trading_day` / :meth:`last_trading_day`
on the singleton instead of issuing their own SDK calls.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import date, datetime, time as dtime, timedelta, timezone
from zoneinfo import ZoneInfo

from app.broker.broker_client import BrokerClient

logger = logging.getLogger(__name__)

_HKT = ZoneInfo("Asia/Hong_Kong")
_ET = ZoneInfo("America/New_York")


def _market_tz(market: str) -> ZoneInfo:
    """Local timezone for the market code (``US`` / ``HK`` / ``CN``)."""
    if market == "US":
        return _ET
    return _HKT  # HK and CN share UTC+8


class MarketSchedule:
    """Cached trading schedule with self-throttled refresh.

    Holds two parallel datasets fetched from the broker SDK:

    - ``_sessions``: per-market list of ``(begin_time, end_time, state)``
      windows for *today*. Empty list = market closed today (weekend /
      holiday). State strings match the wire schema: ``regular`` /
      ``pre`` / ``post`` / ``overnight``.

    - ``_trading_days``: per-market list of recent trading dates,
      newest-first. Default 3 days back — enough to resolve "yesterday's
      RTH close" across long-weekend holiday gaps.

    Thread model: the refresh lock is an asyncio Lock — refresh runs
    inside the event loop. Pure-read methods (``state_for``,
    ``is_trading_day``) are sync and lock-free; callers don't need to
    await them. They can be called from SDK callback threads safely
    because the underlying dicts are reassigned atomically on refresh
    (no in-place mutation during reads).
    """

    REFRESH_FATIGUE_SECONDS = 6 * 3600  # 6 hours

    def __init__(self, broker: BrokerClient) -> None:
        self._broker = broker
        self._sessions: dict[str, list[tuple[dtime, dtime, str]]] = {}
        self._trading_days: dict[str, list[date]] = {}
        self._last_refreshed_at: float | None = None
        self._refresh_lock = asyncio.Lock()

    # ------------------------------------------------------------------ #
    # Refresh                                                              #
    # ------------------------------------------------------------------ #

    async def maybe_refresh(self) -> bool:
        """Refresh the cache if the fatigue window has elapsed (or never).
        Returns True if a refresh happened, False if skipped.

        Concurrent callers serialise on the lock; the second caller sees
        the freshly-populated cache and the predicate returns False."""
        async with self._refresh_lock:
            now = time.monotonic()
            if (
                self._last_refreshed_at is not None
                and (now - self._last_refreshed_at) < self.REFRESH_FATIGUE_SECONDS
            ):
                return False
            await self._refresh_now()
            self._last_refreshed_at = now
            return True

    async def force_refresh(self) -> None:
        """Bypass the fatigue check. Used by tests and explicit user-
        triggered refresh actions (account switch covered separately —
        manager is rebuilt and starts cold)."""
        async with self._refresh_lock:
            await self._refresh_now()
            self._last_refreshed_at = time.monotonic()

    async def _refresh_now(self) -> None:
        """Single SDK round-trip per dataset. Errors are logged but not
        raised — stale-cache > no-cache; the next refresh window will
        retry."""
        try:
            sessions_raw = await asyncio.to_thread(self._broker.fetch_trading_sessions)
        except Exception as exc:  # noqa: BLE001
            logger.warning("MarketSchedule: trading_sessions refresh failed: %s", exc)
            sessions_raw = self._sessions  # keep prior cache

        sessions_clean: dict[str, list[tuple[dtime, dtime, str]]] = {}
        for market, windows in sessions_raw.items():
            kept: list[tuple[dtime, dtime, str]] = []
            for begin, end, state in windows:
                if isinstance(begin, dtime) and isinstance(end, dtime):
                    kept.append((begin, end, state))
            sessions_clean[market] = kept
        self._sessions = sessions_clean

        try:
            days_raw = await asyncio.to_thread(
                self._broker.fetch_trading_days, days_back=3,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("MarketSchedule: trading_days refresh failed: %s", exc)
            days_raw = self._trading_days

        days_clean: dict[str, list[date]] = {}
        for market, days in days_raw.items():
            days_clean[market] = [d for d in days if isinstance(d, date)]
        self._trading_days = days_clean

        logger.info(
            "MarketSchedule: refreshed — markets=%s trading_days=%s",
            {m: len(w) for m, w in self._sessions.items()},
            {m: len(d) for m, d in self._trading_days.items()},
        )

    # ------------------------------------------------------------------ #
    # Pure-read API                                                        #
    # ------------------------------------------------------------------ #

    def state_for(self, market: str, now: datetime | None = None) -> str:
        """Return ``"regular" / "pre" / "post" / "overnight" / "closed"``
        for ``market`` at ``now`` (default = ``datetime.now(UTC)``).

        Looks up the cached schedule first. If no schedule is loaded
        for the market (cold cache or SDK failure), returns ``"regular"``
        for unknown markets and the static clock heuristic otherwise.
        """
        if now is None:
            now = datetime.now(timezone.utc)
        if market not in {"US", "HK", "CN", "SH", "SZ"}:
            return "regular"

        market_key = "CN" if market in ("SH", "SZ") else market
        windows = self._sessions.get(market_key)
        if windows is None:
            # Cold cache — fall back to static clock heuristic.
            from app.broker.market_hours import market_state_for
            return market_state_for(f"X.{market_key}", now)

        local = now.astimezone(_market_tz(market_key))
        if local.weekday() > 4 and market_key != "US":
            # HK / CN never trade on weekends; SDK only returns the
            # current day's sessions, so on weekends the windows are
            # empty and the loop below would also return "closed" — the
            # early return is a clarity micro-optimization.
            return "closed"

        tod = local.time()
        for begin, end, state in windows:
            if begin <= tod < end:
                return state
        return "closed"

    def is_trading_day(self, market: str, day: date) -> bool:
        """``True`` if ``day`` is a known trading day for ``market``.
        Returns ``False`` for days outside the cached window — callers
        should not rely on this for far-past or far-future dates."""
        if market in ("SH", "SZ"):
            market = "CN"
        return day in (self._trading_days.get(market) or [])

    def last_trading_day(self, market: str, *, before: date | None = None) -> date | None:
        """Most recent trading day strictly before ``before`` (default
        = today). Returns ``None`` if the cache doesn't extend back
        far enough."""
        if before is None:
            before = date.today()
        if market in ("SH", "SZ"):
            market = "CN"
        for d in (self._trading_days.get(market) or []):
            if d < before:
                return d
        return None

    @property
    def last_refreshed_at(self) -> float | None:
        """Monotonic timestamp of the last successful refresh. ``None``
        before the first refresh has completed."""
        return self._last_refreshed_at

    @property
    def known_markets(self) -> list[str]:
        """Markets for which the cache holds a session schedule."""
        return list(self._sessions.keys())
