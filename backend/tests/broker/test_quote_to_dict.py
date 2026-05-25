"""Tests for ``_quote_to_dict`` — session-aware change% reference price.

The user spec:
- 盘前 / 盘中 → change vs yesterday's RTH close (prev_close)
- 盘后 / 夜盘 → change vs TODAY's RTH close (last_done frozen at 16:00 ET)

These two reference prices are intentionally different.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.broker.longport_client import _quote_to_dict


def _security_quote(
    *,
    symbol: str = "TSLA.US",
    last_done: float = 250.0,
    prev_close: float = 240.0,
    open_: float = 245.0,
    high: float = 252.0,
    low: float = 244.0,
    volume: int = 100,
    turnover: float = 25000.0,
    pre: SimpleNamespace | None = None,
    post: SimpleNamespace | None = None,
    overnight: SimpleNamespace | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        symbol=symbol,
        last_done=last_done,
        prev_close=prev_close,
        open=open_,
        high=high,
        low=low,
        volume=volume,
        turnover=turnover,
        pre_market_quote=pre,
        post_market_quote=post,
        overnight_quote=overnight,
    )


def _tier(*, last_done: float, high: float = 0.0, low: float = 0.0,
          volume: int = 0, turnover: float = 0.0) -> SimpleNamespace:
    return SimpleNamespace(
        last_done=last_done,
        high=high,
        low=low,
        volume=volume,
        turnover=turnover,
    )


def test_regular_session_change_uses_prev_close() -> None:
    """During 盘中, reference = yesterday's RTH close (prev_close)."""
    q = _security_quote(last_done=250.0, prev_close=240.0)
    d = _quote_to_dict(q, state="regular")
    assert d["last_done"] == 250.0
    assert d["prev_close"] == 240.0
    assert d["today_close"] is None
    # 250 - 240 = 10, 10 / 240 ≈ 4.17%
    assert d["change"] == 10.0
    assert d["change_pct"] == pytest.approx(4.1666666, rel=1e-4)


def test_pre_market_change_uses_prev_close() -> None:
    """During 盘前, reference = yesterday's RTH close. Tier last_done
    is the pre_market_quote's live price."""
    q = _security_quote(
        last_done=240.0,           # frozen at yesterday's RTH close
        prev_close=240.0,           # same here pre-market (SDK quirk)
        pre=_tier(last_done=243.0),
    )
    d = _quote_to_dict(q, state="pre")
    assert d["last_done"] == 243.0
    assert d["prev_close"] == 240.0
    assert d["today_close"] is None
    # 243 - 240 = 3, 3 / 240 = 1.25%
    assert d["change"] == 3.0
    assert d["change_pct"] == 1.25


def test_post_market_change_uses_today_close() -> None:
    """During 盘后, reference = TODAY's RTH close (frozen last_done).

    Concretely: today RTH closed at 246. Post-market drifts to 245.50.
    User expects change% to show -0.20% (the post-market move), NOT
    +2.29% (yesterday's full-day move).
    """
    q = _security_quote(
        last_done=246.0,            # today's RTH close, frozen at 16:00 ET
        prev_close=240.0,           # yesterday's RTH close
        post=_tier(last_done=245.50),
    )
    d = _quote_to_dict(q, state="post")
    assert d["last_done"] == 245.50
    assert d["prev_close"] == 240.0
    assert d["today_close"] == 246.0
    # 245.50 - 246 = -0.50, -0.50 / 246 ≈ -0.203%
    assert d["change"] == pytest.approx(-0.50, rel=1e-4)
    assert d["change_pct"] == pytest.approx(-0.50 / 246 * 100, rel=1e-4)


def test_overnight_change_uses_today_close() -> None:
    """Same rule as post: reference = today's RTH close."""
    q = _security_quote(
        last_done=246.0,
        prev_close=240.0,
        overnight=_tier(last_done=247.0),
    )
    d = _quote_to_dict(q, state="overnight")
    assert d["last_done"] == 247.0
    assert d["today_close"] == 246.0
    assert d["change"] == pytest.approx(1.0, rel=1e-4)
    assert d["change_pct"] == pytest.approx(1.0 / 246 * 100, rel=1e-4)


def test_closed_state_uses_prev_close() -> None:
    """休市 uses prev_close (the most recent prior session close)."""
    q = _security_quote(last_done=246.0, prev_close=240.0)
    d = _quote_to_dict(q, state="closed")
    assert d["today_close"] is None
    # 246 - 240 = 6
    assert d["change"] == 6.0


def test_closed_state_prefers_post_market_last_done() -> None:
    """When extended-hours data exists, closed views should reflect the
    freshest reported tick (post-market last for US) — not the stale
    RTH close. Matches LongBridge App's "现价" on a Saturday: TSLL
    closed RTH at 15.060 but drifted to 14.760 in post-market; we want
    14.760 as the chart's last_done so Day P/L includes that drift."""
    q = _security_quote(
        last_done=15.060,     # RTH close
        prev_close=16.650,    # Thursday's close
        post=_tier(last_done=14.760),  # post-market drift
    )
    d = _quote_to_dict(q, state="closed")
    assert d["last_done"] == 14.760
    assert d["prev_close"] == 16.650
    # 14.760 - 16.650 = -1.890 (full Friday move incl. post)
    assert d["change"] == pytest.approx(-1.890, rel=1e-4)


def test_closed_state_prefers_overnight_over_post() -> None:
    """Overnight is more recent than post; prefer it when both exist."""
    q = _security_quote(
        last_done=100.0,
        prev_close=98.0,
        post=_tier(last_done=99.0),
        overnight=_tier(last_done=101.5),
    )
    d = _quote_to_dict(q, state="closed")
    assert d["last_done"] == 101.5


def test_closed_state_falls_back_to_rth_when_no_extended_tiers() -> None:
    """No post/overnight tier (e.g. HK on a weekend) → use RTH close."""
    q = _security_quote(last_done=246.0, prev_close=240.0)
    d = _quote_to_dict(q, state="closed")
    assert d["last_done"] == 246.0


def test_empty_tier_falls_back_to_regular_session_last() -> None:
    """If the chosen tier has zero last_done (post sub-quote empty
    e.g. at the start of post-market before first tick), use the regular
    session's last_done — better than rendering $0."""
    q = _security_quote(
        last_done=246.0,
        prev_close=240.0,
        post=_tier(last_done=0.0),  # empty tier
    )
    d = _quote_to_dict(q, state="post")
    assert d["last_done"] == 246.0  # fell back to q.last_done
    assert d["today_close"] == 246.0
    # 246 - 246 = 0
    assert d["change"] == 0.0


def test_zero_reference_avoids_divide_by_zero() -> None:
    """No prev_close + no today_close → change% is 0, not NaN/inf."""
    q = _security_quote(last_done=10.0, prev_close=0.0)
    d = _quote_to_dict(q, state="regular")
    assert d["change"] == 0.0
    assert d["change_pct"] == 0.0


def test_trading_day_field_is_threaded_through() -> None:
    """`_quote_to_dict` accepts a `trading_day` kwarg and surfaces it
    verbatim in the output dict. Callers (HTTP + push handler) compute
    the value via `MarketSchedule.current_or_last_trading_day` and pass
    it in — the converter itself does not call the schedule."""
    q = _security_quote(symbol="TSLA.US", last_done=250.0, prev_close=240.0)
    row = _quote_to_dict(q, state="regular", trading_day="2026-05-22")
    assert row["trading_day"] == "2026-05-22"


def test_trading_day_defaults_to_none_when_not_provided() -> None:
    """Backwards-compat: callers that don't pass `trading_day` get
    `None` (the frontend falls back to wall-clock in that case)."""
    q = _security_quote(symbol="TSLA.US")
    row = _quote_to_dict(q, state="regular")
    assert row["trading_day"] is None
