"""Pure condition evaluators used by AlertEngine.

Each evaluator takes already-computed inputs (no I/O); the engine is
responsible for assembling the inputs from quote pushes.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Literal

Operator = Literal[">=", "<="]
Baseline = Literal["today_open", "prev_close"]


def _cmp(value: float, operator: Operator, threshold: float) -> bool:
    return value >= threshold if operator == ">=" else value <= threshold


def evaluate_price(*, last_done: float, operator: Operator, threshold: float) -> bool:
    return _cmp(last_done, operator, threshold)


def evaluate_pct_change(
    *,
    last_done: float,
    baseline_open: float,
    baseline_prev_close: float,
    baseline: Baseline,
    operator: Operator,
    threshold: float,
) -> bool:
    ref = baseline_open if baseline == "today_open" else baseline_prev_close
    if ref <= 0:
        return False
    pct = (last_done - ref) / ref * 100.0
    return _cmp(pct, operator, threshold)


@dataclass
class VolumeWindowState:
    """Rolling window of (timestamp, cumulative_volume) samples.

    Engine calls ``observe(ts, cumulative_volume)`` on every quote push;
    the deque is trimmed so only samples within ``window_seconds`` of
    the latest sample remain. Window volume = latest − oldest.
    """

    window_seconds: int
    samples: deque[tuple[datetime, float]] = field(default_factory=deque)

    def observe(self, ts: datetime, cumulative_volume: float) -> None:
        self.samples.append((ts, cumulative_volume))
        cutoff = ts - timedelta(seconds=self.window_seconds)
        while len(self.samples) > 1 and self.samples[0][0] < cutoff:
            self.samples.popleft()

    def window_volume(self) -> float:
        if len(self.samples) < 2:
            return 0.0
        return self.samples[-1][1] - self.samples[0][1]


def evaluate_volume(
    state: VolumeWindowState, *, operator: Operator, threshold: float
) -> bool:
    return _cmp(state.window_volume(), operator, threshold)


def format_message(
    *,
    ticker: str,
    condition_type: str,
    operator: Operator,
    threshold: float,
    snapshot_price: float,
    snapshot_pct: float | None,
    snapshot_volume: float | None,
) -> str:
    op_label = "≥" if operator == ">=" else "≤"
    if condition_type == "price":
        return (
            f"{ticker} 触发 价格 {op_label} ${threshold:,.2f}"
            f"（当前 ${snapshot_price:,.2f}）"
        )
    if condition_type == "pct_change":
        thr = _signed(threshold)
        cur_pct = _signed(snapshot_pct or 0.0)
        return (
            f"{ticker} 触发 涨跌 {op_label} {thr}"
            f"（当前 {cur_pct} / ${snapshot_price:,.2f}）"
        )
    vol = int(snapshot_volume or 0)
    return (
        f"{ticker} 触发 成交量 {op_label} {int(threshold):,} 股"
        f"（当前 {vol:,} 股 / ${snapshot_price:,.2f}）"
    )


def _signed(pct: float) -> str:
    sign = "−" if pct < 0 else ""
    return f"{sign}{abs(pct):.2f}%"
