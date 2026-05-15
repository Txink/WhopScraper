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
