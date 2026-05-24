# Task 4: Alert Condition Evaluators (pure functions)

Pure deterministic evaluators isolated from engine + DB so they unit-test trivially.

**Files:**
- Create: `backend/app/alerts/__init__.py`, `backend/app/alerts/conditions.py`
- Test: `backend/tests/alerts/test_conditions.py`

## Steps

- [ ] **Step 1: Write failing tests**

`backend/tests/alerts/test_conditions.py`:

```python
"""Pure condition evaluators. No DB, no broker, no asyncio."""
from __future__ import annotations

from collections import deque
from datetime import datetime, timedelta, timezone

import pytest

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
    # Defensive: pre-IPO/halt data can report 0; never raise.
    assert evaluate_pct_change(
        last_done=10.0, baseline_open=0.0, baseline_prev_close=0.0,
        baseline="today_open", operator=">=", threshold=1.0,
    ) is False


def test_volume_window_1min_hits_after_threshold() -> None:
    now = datetime(2026, 5, 25, 14, 0, tzinfo=timezone.utc)
    state = VolumeWindowState(window_seconds=60)
    state.observe(now, cumulative_volume=1_000_000)
    state.observe(now + timedelta(seconds=10), cumulative_volume=1_010_000)
    state.observe(now + timedelta(seconds=55), cumulative_volume=1_050_000)
    # Within 60s window: latest − oldest = 50_000
    assert evaluate_volume(state, operator=">=", threshold=50_000) is True
    assert evaluate_volume(state, operator=">=", threshold=50_001) is False


def test_volume_window_drops_samples_older_than_window() -> None:
    now = datetime(2026, 5, 25, 14, 0, tzinfo=timezone.utc)
    state = VolumeWindowState(window_seconds=60)
    state.observe(now, cumulative_volume=1_000_000)
    state.observe(now + timedelta(seconds=120), cumulative_volume=1_050_000)
    # First sample evicted; window contains only the latest → delta = 0.
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
```

- [ ] **Step 2: Run — verify they fail**

```bash
cd backend && uv run pytest tests/alerts/test_conditions.py -v
```

Expected: ImportError — module does not exist.

- [ ] **Step 3: Implement**

`backend/app/alerts/__init__.py`:

```python
"""Alerts subsystem."""
```

`backend/app/alerts/conditions.py`:

```python
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
    # volume
    vol = int(snapshot_volume or 0)
    return (
        f"{ticker} 触发 成交量 {op_label} {int(threshold):,} 股"
        f"（当前 {vol:,} 股 / ${snapshot_price:,.2f}）"
    )


def _signed(pct: float) -> str:
    sign = "−" if pct < 0 else ""
    return f"{sign}{abs(pct):.2f}%"
```

- [ ] **Step 4: Run + verify**

```bash
cd backend && uv run pytest tests/alerts/test_conditions.py -v
uv run mypy app/alerts
uv run ruff check app/alerts
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add backend/app/alerts/__init__.py backend/app/alerts/conditions.py \
        backend/tests/alerts/test_conditions.py
git commit -m "$(cat <<'EOF'
feat(alerts): pure condition evaluators (price / pct_change / volume)

Engine-independent functions for the three alert types. VolumeWindowState
is a rolling deque over cumulative LongPort volume, sized by
``volume_window`` (1min / 5min).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```
