"""Pure condition evaluators. No DB, no broker, no asyncio."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.alerts.conditions import (
    VolumeWindowState,
    evaluate_pct_change,
    evaluate_price,
    evaluate_volume,
    format_message,
)


def test_price_ge_hits() -> None:
    assert evaluate_price(last_done=200.10, operator=">=", threshold=200.00) is True


def test_price_ge_misses() -> None:
    assert evaluate_price(last_done=199.95, operator=">=", threshold=200.00) is False


def test_price_le_hits() -> None:
    assert evaluate_price(last_done=179.50, operator="<=", threshold=180.00) is True


def test_pct_change_today_open() -> None:
    assert evaluate_pct_change(
        last_done=97.0, baseline_open=100.0, baseline_prev_close=99.0,
        baseline="today_open", operator="<=", threshold=-3.0,
    ) is True
    assert evaluate_pct_change(
        last_done=98.5, baseline_open=100.0, baseline_prev_close=99.0,
        baseline="today_open", operator="<=", threshold=-3.0,
    ) is False


def test_pct_change_prev_close() -> None:
    assert evaluate_pct_change(
        last_done=103.0, baseline_open=100.0, baseline_prev_close=100.0,
        baseline="prev_close", operator=">=", threshold=2.5,
    ) is True


def test_pct_change_zero_baseline_does_not_crash() -> None:
    assert evaluate_pct_change(
        last_done=10.0, baseline_open=0.0, baseline_prev_close=0.0,
        baseline="today_open", operator=">=", threshold=1.0,
    ) is False


def test_volume_window_1min_hits_after_threshold() -> None:
    now = datetime(2026, 5, 25, 14, 0, tzinfo=UTC)
    state = VolumeWindowState(window_seconds=60)
    state.observe(now, cumulative_volume=1_000_000)
    state.observe(now + timedelta(seconds=10), cumulative_volume=1_010_000)
    state.observe(now + timedelta(seconds=55), cumulative_volume=1_050_000)
    assert evaluate_volume(state, operator=">=", threshold=50_000) is True
    assert evaluate_volume(state, operator=">=", threshold=50_001) is False


def test_volume_window_drops_samples_older_than_window() -> None:
    now = datetime(2026, 5, 25, 14, 0, tzinfo=UTC)
    state = VolumeWindowState(window_seconds=60)
    state.observe(now, cumulative_volume=1_000_000)
    state.observe(now + timedelta(seconds=120), cumulative_volume=1_050_000)
    assert evaluate_volume(state, operator=">=", threshold=1) is False


def test_format_message_price() -> None:
    assert format_message(
        ticker="AAPL", condition_type="price", operator=">=",
        threshold=200.0, snapshot_price=200.15, snapshot_pct=None, snapshot_volume=None,
    ) == "AAPL 触发 价格 ≥ $200.00（当前 $200.15）"


def test_format_message_pct() -> None:
    assert format_message(
        ticker="NVDA", condition_type="pct_change", operator="<=",
        threshold=-3.0, snapshot_price=480.10, snapshot_pct=-3.21, snapshot_volume=None,
    ) == "NVDA 触发 涨跌 ≤ −3.00%（当前 −3.21% / $480.10）"


def test_format_message_volume() -> None:
    msg = format_message(
        ticker="TSLA", condition_type="volume", operator=">=",
        threshold=50_000, snapshot_price=180.0, snapshot_pct=None, snapshot_volume=52_300,
    )
    assert "TSLA" in msg and "52,300" in msg
