"""Map (symbol, wall-clock time) → current market state.

Used by :pyfunc:`app.broker.longport_client._quote_to_dict` to decide which
session tier of a multi-session quote to surface. The state also rides
the wire as ``trade_session`` so the frontend can paint a 盘中 / 盘前 /
盘后 / 夜盘 / 休市 pill on each stock card.

Holidays are *not* consulted — we only check weekday + hour-of-day. A US
Independence Day weekday will still classify as "regular" between 09:30
and 16:00 ET, but the broker's quote timestamp tells the user how stale
the price actually is, so the wrong badge is recoverable. Calendar
correctness can come later if needed.
"""

from __future__ import annotations

from datetime import datetime, time, timezone
from typing import Literal
from zoneinfo import ZoneInfo

MarketState = Literal["regular", "pre", "post", "overnight", "closed"]

_ET = ZoneInfo("America/New_York")  # handles DST automatically
_HKT = ZoneInfo("Asia/Hong_Kong")
_CST = ZoneInfo("Asia/Shanghai")    # A-share market clock


def market_state_for(symbol: str, now: datetime | None = None) -> MarketState:
    """Return the market state for ``symbol`` at ``now``.

    ``symbol`` is the SDK identifier (e.g. ``"TSLA.US"``, ``"700.HK"``,
    ``"600519.SH"``). Suffix selects the market. Unknown suffixes default
    to ``"regular"`` so option contracts and any future markets degrade to
    showing the broker's last_done as-is.

    ``now`` is the wall-clock reference (default ``datetime.now(UTC)``).
    Tests pass a fixed UTC value to lock in deterministic behaviour.
    """
    if now is None:
        now = datetime.now(timezone.utc)
    if "." not in symbol:
        return "regular"
    market = symbol.rsplit(".", 1)[-1].upper()
    if market == "US":
        return _us_state(now)
    if market == "HK":
        return _hk_state(now)
    if market in ("SH", "SZ"):
        return _a_share_state(now)
    return "regular"


def _us_state(now_utc: datetime) -> MarketState:
    """US equity sessions (ET, DST-aware via zoneinfo).

    Schedule:
      - Mon-Fri 04:00–09:30  →  pre
      - Mon-Fri 09:30–16:00  →  regular
      - Mon-Fri 16:00–20:00  →  post
      - Sun 20:00 → Fri 04:00 (across midnight gaps), 20:00→04:00 each
        weekday evening → 04:00 next morning  →  overnight
      - Everything else (Sat, Sun before 20:00, Fri 20:00 → Sun 20:00) →
        closed

    LongBridge's overnight session runs Sun 20:00 ET through Fri 04:00 ET
    with weekday-evening seams. The simplified rule here treats any
    20:00–24:00 of Sun-Thu and 00:00–04:00 of Mon-Fri as overnight, which
    matches that schedule.
    """
    local = now_utc.astimezone(_ET)
    wd = local.weekday()  # Mon=0 .. Sun=6
    t = local.time()

    # Weekday daytime (Mon-Fri 04:00–20:00) — pre / regular / post.
    if wd <= 4:
        if time(4, 0) <= t < time(9, 30):
            return "pre"
        if time(9, 30) <= t < time(16, 0):
            return "regular"
        if time(16, 0) <= t < time(20, 0):
            return "post"
        # Mon-Fri 00:00–04:00 → tail of prior session's overnight.
        if t < time(4, 0):
            return "overnight"
        # Mon-Thu 20:00–24:00 → start of next overnight.
        if t >= time(20, 0) and wd <= 3:
            return "overnight"
        # Fri 20:00 onwards → weekend closed.
        return "closed"

    # Sat — no trading.
    if wd == 5:
        return "closed"
    # Sun — overnight starts at 20:00 ET (lead-in to Monday).
    if t >= time(20, 0):
        return "overnight"
    return "closed"


def _hk_state(now_utc: datetime) -> MarketState:
    """HK equity sessions (HKT, no DST).
      09:30–12:00 morning, 13:00–16:00 afternoon, lunch break 12:00–13:00.
      Mon-Fri only. HK has no extended-hours / overnight session."""
    local = now_utc.astimezone(_HKT)
    if local.weekday() > 4:
        return "closed"
    t = local.time()
    if time(9, 30) <= t < time(12, 0):
        return "regular"
    if time(13, 0) <= t < time(16, 0):
        return "regular"
    return "closed"


def _a_share_state(now_utc: datetime) -> MarketState:
    """A-share sessions (CST = HKT timezone, no DST).
      09:30–11:30 morning, 13:00–15:00 afternoon.
      Mon-Fri only. No extended-hours / overnight session."""
    local = now_utc.astimezone(_CST)
    if local.weekday() > 4:
        return "closed"
    t = local.time()
    if time(9, 30) <= t < time(11, 30):
        return "regular"
    if time(13, 0) <= t < time(15, 0):
        return "regular"
    return "closed"
