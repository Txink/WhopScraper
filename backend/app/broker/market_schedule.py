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

        Cached session windows are time-of-day patterns from a recent
        SDK fetch — they do NOT carry a date. Naively matching the
        current local time against them is unsafe on weekends/holidays:
        e.g. on Saturday ET 04:00 the cached weekday "pre" window
        04:00-09:30 still matches, returning "pre" when markets are
        clearly closed. This implementation validates each potential
        match against the actual trading-date calendar (``_trading_days``)
        so the result agrees with whether the market is open today
        (and, for overnight, whether the adjacent ET dates are trading
        days too — overnight only runs between two consecutive trading
        weekdays).

        Falls back to the static clock heuristic when the cache is
        cold (broker init race).
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
        local_date = local.date()
        tod = local.time()

        def is_trading(d: date) -> bool:
            """Holiday-aware trading-day check.

            The cache holds the last few trading dates (days_back=3) so
            we can't blanket-say "not in cache = not trading" — future
            dates (e.g. tomorrow, needed for overnight validation) won't
            be cached but may very well be trading days. Three-way logic:

            1. ``d in cached`` → definitively a trading day.
            2. Weekend → definitively closed.
            3. Weekday inside cached date range but not listed → known
               holiday (the broker returned the surrounding days but
               omitted ``d``).
            4. Weekday outside cached range OR cold cache → fall back to
               the weekday heuristic (assume trading).
            """
            cached = self._trading_days.get(market_key, []) or []
            if d in cached:
                return True
            if d.weekday() > 4:
                return False
            if cached:
                oldest, newest = min(cached), max(cached)
                if oldest <= d <= newest:
                    return False  # gap inside cached range = holiday
            return True

        # HK / CN: only one (regular) session per trading day; no
        # overnight, no weekend trading.
        if market_key in ("HK", "CN"):
            if not is_trading(local_date):
                return "closed"
            for begin, end, state in windows:
                if begin <= tod < end:
                    return state
            return "closed"

        # US: pre/regular/post happen on a trading day; overnight
        # bridges two consecutive trading days (20:00 → 04:00 next day).
        from datetime import time as _t, timedelta
        for begin, end, state in windows:
            if not (begin <= tod < end):
                continue
            if state == "overnight":
                # 20:00-23:59 → start of TODAY's overnight; requires
                # both today and tomorrow to be trading days.
                # 00:00-03:59 → tail of YESTERDAY's overnight; requires
                # both yesterday and today to be trading days.
                if tod >= _t(20, 0):
                    if is_trading(local_date) and is_trading(local_date + timedelta(days=1)):
                        return "overnight"
                elif tod < _t(4, 0):
                    if is_trading(local_date - timedelta(days=1)) and is_trading(local_date):
                        return "overnight"
                # Falls through to "closed" if either adjacent day is
                # not a trading day.
                continue
            # pre / regular / post: today must be a trading day.
            if is_trading(local_date):
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
