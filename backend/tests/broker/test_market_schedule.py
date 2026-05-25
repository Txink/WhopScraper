"""Tests for the global MarketSchedule service."""

from __future__ import annotations

from datetime import date, datetime, time, timezone
from unittest.mock import patch

import pytest

from app.broker.market_schedule import MarketSchedule
from tests.broker._fakes import FakeBrokerClient


def _seed_sessions_via_fake() -> FakeBrokerClient:
    """Build a fake broker that responds with US + HK + CN schedules."""
    broker = FakeBrokerClient()
    broker.trading_sessions_map = {  # type: ignore[attr-defined]
        "US": [
            (time(4, 0), time(9, 30), "pre"),
            (time(9, 30), time(16, 0), "regular"),
            (time(16, 0), time(20, 0), "post"),
            (time(20, 0), time(23, 59, 59), "overnight"),
            (time(0, 0), time(4, 0), "overnight"),
        ],
        "HK": [
            (time(9, 30), time(12, 0), "regular"),
            (time(13, 0), time(16, 0), "regular"),
        ],
        "CN": [
            (time(9, 30), time(11, 30), "regular"),
            (time(13, 0), time(15, 0), "regular"),
        ],
    }
    broker.trading_days_map = {  # type: ignore[attr-defined]
        "US": [date(2030, 1, 2), date(2030, 1, 1), date(2029, 12, 31)],
        "HK": [date(2030, 1, 2), date(2030, 1, 1)],
        "CN": [date(2030, 1, 2)],
    }
    return broker


# --- state_for -----------------------------------------------------------


@pytest.mark.asyncio
async def test_hk_after_close_is_closed() -> None:
    """HK 19:32 HKT (the originally-reported bug) → 休市."""
    sch = MarketSchedule(_seed_sessions_via_fake())
    await sch.force_refresh()
    now = datetime(2030, 1, 2, 11, 32, tzinfo=timezone.utc)  # 19:32 HKT
    assert sch.state_for("HK", now) == "closed"


@pytest.mark.asyncio
async def test_hk_during_session() -> None:
    sch = MarketSchedule(_seed_sessions_via_fake())
    await sch.force_refresh()
    now = datetime(2030, 1, 2, 2, 0, tzinfo=timezone.utc)  # 10:00 HKT
    assert sch.state_for("HK", now) == "regular"


@pytest.mark.asyncio
async def test_hk_lunch_break_is_closed() -> None:
    sch = MarketSchedule(_seed_sessions_via_fake())
    await sch.force_refresh()
    now = datetime(2030, 1, 2, 4, 30, tzinfo=timezone.utc)  # 12:30 HKT
    assert sch.state_for("HK", now) == "closed"


@pytest.mark.asyncio
async def test_us_pre_market() -> None:
    sch = MarketSchedule(_seed_sessions_via_fake())
    await sch.force_refresh()
    now = datetime(2030, 1, 2, 12, 0, tzinfo=timezone.utc)  # 07:00 ET
    assert sch.state_for("US", now) == "pre"


@pytest.mark.asyncio
async def test_us_overnight_after_midnight() -> None:
    sch = MarketSchedule(_seed_sessions_via_fake())
    await sch.force_refresh()
    now = datetime(2030, 1, 2, 7, 0, tzinfo=timezone.utc)  # 02:00 ET
    assert sch.state_for("US", now) == "overnight"


@pytest.mark.asyncio
async def test_sh_and_sz_resolve_to_cn() -> None:
    sch = MarketSchedule(_seed_sessions_via_fake())
    await sch.force_refresh()
    now = datetime(2030, 1, 2, 2, 0, tzinfo=timezone.utc)  # 10:00 HKT (= CN)
    assert sch.state_for("SH", now) == "regular"
    assert sch.state_for("SZ", now) == "regular"


@pytest.mark.asyncio
async def test_state_for_unknown_market_defaults_to_regular() -> None:
    sch = MarketSchedule(_seed_sessions_via_fake())
    await sch.force_refresh()
    now = datetime(2030, 1, 2, 2, 0, tzinfo=timezone.utc)
    assert sch.state_for("XX", now) == "regular"


# --- weekend / holiday guards (the bug behind the user-reported pill flip) ---


@pytest.mark.asyncio
async def test_us_saturday_morning_is_closed_not_pre() -> None:
    """User-reported regression: Sat ET 04:00 wall-clock matched the
    cached weekday ``pre`` window 04:00-09:30 → ``state_for`` wrongly
    returned ``pre`` when the market was clearly closed for the weekend.
    """
    sch = MarketSchedule(_seed_sessions_via_fake())
    await sch.force_refresh()
    # 2030-01-05 is a Saturday.  09:00 UTC = 04:00 ET (during the cached
    # weekday "pre" window, but on a non-trading day).
    now = datetime(2030, 1, 5, 9, 0, tzinfo=timezone.utc)
    assert sch.state_for("US", now) == "closed"


@pytest.mark.asyncio
async def test_us_saturday_during_regular_hours_is_closed() -> None:
    sch = MarketSchedule(_seed_sessions_via_fake())
    await sch.force_refresh()
    # Sat 14:30 UTC = 09:30 ET (would match the regular window on a
    # weekday).
    now = datetime(2030, 1, 5, 14, 30, tzinfo=timezone.utc)
    assert sch.state_for("US", now) == "closed"


@pytest.mark.asyncio
async def test_us_sunday_evening_is_closed_not_overnight() -> None:
    """Sun 22:00 ET would match the cached overnight window 20:00-24:00
    but Sunday itself isn't a trading day, so the would-be overnight has
    no regular session to feed into."""
    sch = MarketSchedule(_seed_sessions_via_fake())
    await sch.force_refresh()
    # 2030-01-06 is a Sunday. 03:00 UTC next day = 22:00 ET Sun.
    now = datetime(2030, 1, 7, 3, 0, tzinfo=timezone.utc)
    assert sch.state_for("US", now) == "closed"


@pytest.mark.asyncio
async def test_us_monday_before_4am_is_closed_not_overnight() -> None:
    """Mon 02:00 ET would match overnight window 00:00-04:00 but
    yesterday (Sunday) wasn't a trading day, so no overnight ran."""
    sch = MarketSchedule(_seed_sessions_via_fake())
    await sch.force_refresh()
    # Mon Jan 7, 2030 isn't in the cache's listed dates, but it's a
    # weekday. The cache only has [Jan 2, Jan 1, Dec 31]. is_trading
    # for Jan 7: > newest cached → weekday heuristic → True. is_trading
    # for Sun Jan 6: weekend → False. Overnight rejected.
    now = datetime(2030, 1, 7, 7, 0, tzinfo=timezone.utc)  # 02:00 ET Mon
    assert sch.state_for("US", now) == "closed"


@pytest.mark.asyncio
async def test_us_friday_evening_is_closed_not_overnight() -> None:
    """Fri 22:00 ET would match overnight 20:00-24:00 but tomorrow
    (Saturday) isn't a trading day, so Friday's evening has no overnight."""
    sch = MarketSchedule(_seed_sessions_via_fake())
    await sch.force_refresh()
    # Fri Jan 4, 2030. 03:00 UTC Sat = 22:00 ET Fri. Outside cache range
    # → heuristic for Fri (weekday=True), Sat (weekend=False).
    now = datetime(2030, 1, 5, 3, 0, tzinfo=timezone.utc)
    assert sch.state_for("US", now) == "closed"


@pytest.mark.asyncio
async def test_us_holiday_today_with_forward_window_is_closed() -> None:
    """Memorial Day 2026-05-25 (the originally-reported bug): today
    is itself the holiday Monday. The broker cache must include
    *upcoming* trading days (e.g. Tue 5/26) so today's date falls
    inside [oldest_past, newest_future] — then is_trading() spots
    the gap and state_for returns 'closed' instead of falling back
    to the weekday heuristic.

    This is the realistic, end-to-end shape the user encountered: a
    cache that brackets today is what makes holiday detection work
    for the current day."""
    broker = _seed_sessions_via_fake()
    broker.trading_days_map["US"] = [  # type: ignore[attr-defined]
        date(2026, 5, 26),  # Tue — next trading day after Memorial Day
        date(2026, 5, 22),  # Fri — last trading day before
        date(2026, 5, 21),  # Thu
        date(2026, 5, 20),  # Wed
    ]
    sch = MarketSchedule(broker)
    await sch.force_refresh()
    # Mon May 25, 2026 13:30 UTC = 09:30 ET (start of regular session
    # on any normal weekday).
    now = datetime(2026, 5, 25, 13, 30, tzinfo=timezone.utc)
    assert sch.state_for("US", now) == "closed"


@pytest.mark.asyncio
async def test_refresh_requests_forward_window_from_broker() -> None:
    """The cache must include upcoming trading days, not just history.
    Without forward dates today (when it's a holiday) is always past
    the cache's newest entry → is_trading() falls back to weekday
    heuristic and misclassifies the holiday as a trading day."""
    broker = _seed_sessions_via_fake()
    captured: dict = {}

    def capturing(**kwargs):  # type: ignore[no-untyped-def]
        captured.update(kwargs)
        return dict(broker.trading_days_map)  # type: ignore[attr-defined]

    broker.fetch_trading_days = capturing  # type: ignore[method-assign]
    sch = MarketSchedule(broker)
    await sch.force_refresh()

    assert captured.get("days_forward", 0) >= 7, (
        "MarketSchedule must request a forward window so today (which "
        "may be a holiday) is bracketed in the cached date range"
    )


@pytest.mark.asyncio
async def test_us_holiday_inside_cached_range_is_closed() -> None:
    """If the broker omits a weekday from the trading-days cache (e.g.
    a holiday), state_for should treat that date as non-trading."""
    broker = _seed_sessions_via_fake()
    # Synthesize a "Mon Dec 31 is holiday" scenario by populating the
    # cache with [Jan 2, Dec 30] only — Dec 31 inside [Dec 30, Jan 2]
    # but absent.
    broker.trading_days_map["US"] = [  # type: ignore[attr-defined]
        date(2030, 1, 2), date(2029, 12, 30),
    ]
    sch = MarketSchedule(broker)
    await sch.force_refresh()
    # Dec 31, 2029 ET 11:00 = 16:00 UTC. Weekday heuristic would say
    # trading; cache should override → closed.
    now = datetime(2029, 12, 31, 16, 0, tzinfo=timezone.utc)
    assert sch.state_for("US", now) == "closed"


@pytest.mark.asyncio
async def test_hk_holiday_inside_cached_range_is_closed() -> None:
    """Same holiday-inside-cache guard for HK."""
    broker = _seed_sessions_via_fake()
    broker.trading_days_map["HK"] = [  # type: ignore[attr-defined]
        date(2030, 1, 2), date(2029, 12, 30),
    ]
    sch = MarketSchedule(broker)
    await sch.force_refresh()
    # Dec 31, 2029 04:00 UTC = 12:00 HKT (would be lunch break on
    # a real trading day, but here Dec 31 is excluded → fully closed).
    now = datetime(2029, 12, 31, 2, 0, tzinfo=timezone.utc)  # 10:00 HKT
    assert sch.state_for("HK", now) == "closed"


@pytest.mark.asyncio
async def test_cold_cache_falls_back_to_clock_heuristic() -> None:
    """Before the first refresh, ``state_for`` should still return a
    plausible answer using the static market_hours heuristic."""
    sch = MarketSchedule(FakeBrokerClient())
    # 2030-01-02 was a Wednesday; HK 10:00 HKT is regular.
    now = datetime(2030, 1, 2, 2, 0, tzinfo=timezone.utc)
    assert sch.state_for("HK", now) == "regular"


# --- fatigue / refresh ---------------------------------------------------


@pytest.mark.asyncio
async def test_maybe_refresh_skips_within_fatigue_window() -> None:
    """A second call inside the 6h window must NOT re-hit the broker."""
    broker = _seed_sessions_via_fake()
    sch = MarketSchedule(broker)

    call_count = {"sessions": 0, "days": 0}
    orig_sessions = broker.fetch_trading_sessions
    orig_days = broker.fetch_trading_days

    def counting_sessions() -> dict:  # type: ignore[no-untyped-def]
        call_count["sessions"] += 1
        return orig_sessions()

    def counting_days(**kwargs):  # type: ignore[no-untyped-def]
        call_count["days"] += 1
        return orig_days(**kwargs)

    broker.fetch_trading_sessions = counting_sessions  # type: ignore[method-assign]
    broker.fetch_trading_days = counting_days  # type: ignore[method-assign]

    # First call refreshes.
    refreshed = await sch.maybe_refresh()
    assert refreshed is True
    assert call_count["sessions"] == 1
    assert call_count["days"] == 1

    # Second call within fatigue → skipped.
    refreshed = await sch.maybe_refresh()
    assert refreshed is False
    assert call_count["sessions"] == 1
    assert call_count["days"] == 1


@pytest.mark.asyncio
async def test_force_refresh_bypasses_fatigue() -> None:
    broker = _seed_sessions_via_fake()
    sch = MarketSchedule(broker)
    await sch.force_refresh()
    first_ts = sch.last_refreshed_at
    assert first_ts is not None
    await sch.force_refresh()
    assert sch.last_refreshed_at is not None
    assert sch.last_refreshed_at >= first_ts


# --- trading_days --------------------------------------------------------


@pytest.mark.asyncio
async def test_is_trading_day_and_last_trading_day() -> None:
    sch = MarketSchedule(_seed_sessions_via_fake())
    await sch.force_refresh()

    assert sch.is_trading_day("US", date(2030, 1, 2)) is True
    assert sch.is_trading_day("US", date(2030, 1, 3)) is False  # not in cache
    assert sch.last_trading_day("US", before=date(2030, 1, 2)) == date(2030, 1, 1)
    # SH / SZ resolve via the CN bucket.
    assert sch.is_trading_day("SH", date(2030, 1, 2)) is True


@pytest.mark.asyncio
async def test_refresh_failure_keeps_prior_cache() -> None:
    """If the broker raises on refresh, the prior cache stays usable."""
    broker = _seed_sessions_via_fake()
    sch = MarketSchedule(broker)
    await sch.force_refresh()
    assert sch.state_for(
        "HK", datetime(2030, 1, 2, 2, 0, tzinfo=timezone.utc),
    ) == "regular"

    def boom() -> dict:  # type: ignore[no-untyped-def]
        raise RuntimeError("network blip")

    broker.fetch_trading_sessions = boom  # type: ignore[method-assign]
    await sch.force_refresh()  # should not raise

    # Prior cache still answers correctly.
    assert sch.state_for(
        "HK", datetime(2030, 1, 2, 2, 0, tzinfo=timezone.utc),
    ) == "regular"


# --- current_or_last_trading_day -----------------------------------------


@pytest.mark.asyncio
async def test_current_or_last_trading_day_during_regular_session() -> None:
    """US 10:30 ET on a trading day → returns that date."""
    sch = MarketSchedule(_seed_sessions_via_fake())
    await sch.force_refresh()
    # 2030-01-02 14:30 UTC = 09:30 ET, Wed, in cached trading days.
    now = datetime(2030, 1, 2, 14, 30, tzinfo=timezone.utc)
    assert sch.current_or_last_trading_day("US", now) == date(2030, 1, 2)


@pytest.mark.asyncio
async def test_current_or_last_trading_day_us_holiday_returns_prior_trading_day() -> None:
    """US Memorial Day Monday (gap in cached calendar) → returns the
    prior Friday from the cached trading days."""
    broker = FakeBrokerClient()
    broker.trading_sessions_map = {  # type: ignore[attr-defined]
        "US": [
            (time(4, 0), time(9, 30), "pre"),
            (time(9, 30), time(16, 0), "regular"),
            (time(16, 0), time(20, 0), "post"),
        ],
    }
    # Cached: Fri 5/22, (skip Mon 5/25 holiday), Tue 5/26 - newest first.
    broker.trading_days_map = {  # type: ignore[attr-defined]
        "US": [date(2026, 5, 26), date(2026, 5, 22), date(2026, 5, 21)],
    }
    sch = MarketSchedule(broker)
    await sch.force_refresh()
    # 2026-05-25 14:30 UTC = 10:30 EDT, Memorial Day Monday.
    now = datetime(2026, 5, 25, 14, 30, tzinfo=timezone.utc)
    assert sch.current_or_last_trading_day("US", now) == date(2026, 5, 22)


@pytest.mark.asyncio
async def test_current_or_last_trading_day_us_saturday_returns_friday() -> None:
    """US Saturday morning → returns the prior Friday."""
    broker = FakeBrokerClient()
    broker.trading_sessions_map = {  # type: ignore[attr-defined]
        "US": [(time(9, 30), time(16, 0), "regular")],
    }
    broker.trading_days_map = {  # type: ignore[attr-defined]
        "US": [date(2026, 5, 22), date(2026, 5, 21)],
    }
    sch = MarketSchedule(broker)
    await sch.force_refresh()
    # 2026-05-23 14:30 UTC = 10:30 EDT, Saturday.
    now = datetime(2026, 5, 23, 14, 30, tzinfo=timezone.utc)
    assert sch.current_or_last_trading_day("US", now) == date(2026, 5, 22)


@pytest.mark.asyncio
async def test_current_or_last_trading_day_overnight_tail_rolls_back() -> None:
    """US 02:00 ET = tail of yesterday's overnight session → yesterday's
    date (the trading day that started at yesterday's pre-market)."""
    broker = FakeBrokerClient()
    broker.trading_sessions_map = {  # type: ignore[attr-defined]
        "US": [
            (time(4, 0), time(9, 30), "pre"),
            (time(9, 30), time(16, 0), "regular"),
            (time(16, 0), time(20, 0), "post"),
            (time(20, 0), time(23, 59, 59), "overnight"),
            (time(0, 0), time(4, 0), "overnight"),
        ],
    }
    broker.trading_days_map = {  # type: ignore[attr-defined]
        "US": [date(2026, 5, 22), date(2026, 5, 21), date(2026, 5, 20)],
    }
    sch = MarketSchedule(broker)
    await sch.force_refresh()
    # Fri 2026-05-22 06:00 UTC = Fri 02:00 EDT — tail of Thursday's overnight.
    now = datetime(2026, 5, 22, 6, 0, tzinfo=timezone.utc)
    assert sch.current_or_last_trading_day("US", now) == date(2026, 5, 21)


@pytest.mark.asyncio
async def test_current_or_last_trading_day_cold_cache_returns_local_date() -> None:
    """Before the first refresh (no sessions cached), fall back to the
    local market date so callers get a sane non-None value."""
    sch = MarketSchedule(FakeBrokerClient())  # no refresh
    now = datetime(2026, 5, 25, 14, 30, tzinfo=timezone.utc)
    # 10:30 EDT → 2026-05-25
    assert sch.current_or_last_trading_day("US", now) == date(2026, 5, 25)


@pytest.mark.asyncio
async def test_current_or_last_trading_day_hk_lunch_break_returns_today() -> None:
    """HK 12:30 HKT is the inter-day lunch break — ``state_for`` returns
    ``"closed"`` even though 2030-01-02 is a real trading day. The method
    must return today (not yesterday) by walking back from
    ``local_date + 1`` so today itself is a candidate."""
    sch = MarketSchedule(_seed_sessions_via_fake())
    await sch.force_refresh()
    now = datetime(2030, 1, 2, 4, 30, tzinfo=timezone.utc)  # 12:30 HKT
    assert sch.current_or_last_trading_day("HK", now) == date(2030, 1, 2)
