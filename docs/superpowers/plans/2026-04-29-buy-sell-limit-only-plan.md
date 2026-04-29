# 买卖统一使用 LIMIT 单 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the two MARKET-order branches in `_decide_order_type_and_context` with `LIMIT @ last_done`, so BUY/SELL never use market orders. When the live quote is more favorable than the signal price, the limit price tracks the live quote ("占便宜"); otherwise it stays at the signal price.

**Architecture:** Single decision function rewrite in `backend/app/broker/trader.py`. Four test files updated to assert the new contract. No schema, no API, no wiring change.

**Tech Stack:** Python 3.11, pytest, ruff. Backend test runner: `cd backend && uv run pytest -v`.

**Spec:** `docs/superpowers/specs/2026-04-29-buy-sell-limit-only-design.md`

---

## File Map

**Modify (production):**

- `backend/app/broker/trader.py:78-119` — `_decide_order_type_and_context` rewrites BUY-below-signal and SELL-above-signal branches to return `("LIMIT", last_done, ...)`

**Modify (tests):**

- `backend/tests/broker/test_trader.py:115-181` — `test_stock_buy_happy_path`, `test_option_buy_happy_path`
- `backend/tests/broker/test_trader_deviation.py:308-361` — `test_buy_market_when_quote_below_signal`, `test_sell_market_when_quote_above_signal` (rename + assertion swap)
- `backend/tests/integration/test_broker_lifecycle.py:151` — inline comment only (no `order_type` assertion in that test)
- `backend/tests/integration/test_acceptance.py:213,236,289` — docstring + comment + one assertion

**Out of scope:**

- `backend/tests/storage/test_schema.py`, `backend/tests/api/test_schemas.py`, `backend/tests/broker/test_longport_client.py`, `backend/tests/broker/test_broker_client_protocol.py` — these use `"MARKET"` as a schema/protocol example value, unrelated to trader decision logic. Do NOT touch.
- Legacy `broker/auto_trader.py` (refactor-v2 has superseded it for the live path).

---

## Pre-flight

- [ ] **P1: Confirm working tree state**

```bash
git status --short
```

Expected: only the spec file `docs/superpowers/specs/2026-04-29-buy-sell-limit-only-design.md` is committed; the listed pre-existing modifications in `frontend/src/components/Card/CardExpanded.tsx`, `frontend/src/components/Card/cardHelpers.ts`, `frontend/src/components/Dashboard/TaskStream.tsx`, `frontend/src/components/WhopPanel/WhopPanel.tsx` may show as `M` — leave them alone.

- [ ] **P2: Run baseline backend tests so failures we introduce are isolated**

```bash
cd backend && uv run pytest -q 2>&1 | tail -20
```

Expected: all green (or note any pre-existing failures unrelated to `broker/trader.py`).

---

## Task 1: Rewrite `_decide_order_type_and_context` & update its unit tests

**Files:**

- Modify: `backend/app/broker/trader.py:78-119`
- Modify: `backend/tests/broker/test_trader.py:115-181`
- Modify: `backend/tests/broker/test_trader_deviation.py:308-361`

This task bundles the production change with the unit tests that directly cover the decision function. Integration test fixups are in Task 2.

- [ ] **Step 1: Update `test_stock_buy_happy_path` assertions in `backend/tests/broker/test_trader.py`**

Replace the assertion block at lines 115-144. Before:

```python
    # last_done < signal 25 → MARKET for BUY
    fake.quote_by_symbol["TSLA.US"] = 20.0
```

After:

```python
    # last_done 20 < signal 25 → LIMIT @ last_done (20)
    fake.quote_by_symbol["TSLA.US"] = 20.0
```

Then the assertions at lines 135-143. Before:

```python
    assert order["price"] is None
    assert order["order_type"] == "MARKET"

    assert len(received_events) == 1
    submitted_task: Task = received_events[0].payload.task
    assert submitted_task.status == Status.PENDING
    assert submitted_task.submit_order_type == "MARKET"
    assert submitted_task.submit_order_context is not None
    assert "市价" in (submitted_task.submit_order_context or "")
```

After:

```python
    assert order["price"] == pytest.approx(20.0)
    assert order["order_type"] == "LIMIT"

    assert len(received_events) == 1
    submitted_task: Task = received_events[0].payload.task
    assert submitted_task.status == Status.PENDING
    assert submitted_task.submit_order_type == "LIMIT"
    assert submitted_task.submit_order_context is not None
    assert "限价" in (submitted_task.submit_order_context or "")
```

- [ ] **Step 2: Update `test_option_buy_happy_path` assertions**

In the same file at lines 154-181. Before:

```python
    # last_done < signal 3.0 → MARKET for BUY
    fake.quote_by_symbol["AAPL260117C150000.US"] = 2.0
```

After:

```python
    # last_done 2.0 < signal 3.0 → LIMIT @ last_done (2.0)
    fake.quote_by_symbol["AAPL260117C150000.US"] = 2.0
```

Then at lines 174-180. Before:

```python
    assert order["price"] is None
    assert order["order_type"] == "MARKET"

    assert len(received_events) == 1
    submitted_task: Task = received_events[0].payload.task
    assert submitted_task.status == Status.PENDING
    assert submitted_task.submit_order_type == "MARKET"
```

After:

```python
    assert order["price"] == pytest.approx(2.0)
    assert order["order_type"] == "LIMIT"

    assert len(received_events) == 1
    submitted_task: Task = received_events[0].payload.task
    assert submitted_task.status == Status.PENDING
    assert submitted_task.submit_order_type == "LIMIT"
```

- [ ] **Step 3: Rename + rewrite `test_buy_market_when_quote_below_signal` in `test_trader_deviation.py`**

At line 308-327. Before:

```python
@pytest.mark.asyncio
async def test_buy_market_when_quote_below_signal():
    bus = EventBus()
    broker = _RecordingBroker()
    broker.quote_last["TSLL.US"] = 9.5
    page_settings = PageSettings(
        dedupe_processed_messages=True,
        price_deviation_tolerance=1.0,
        tickers={"TSLL": TickerConfig(trade_quantity=100)},
    )
    register_trader(bus, broker, _config(), registry=_registry_with(page_settings))

    task = _stock_task("TSLL", position_size="常规仓", price=10.0)
    await bus.publish(Event(Topics.TASK_INSTRUCTION_READY, TaskPayload(task)))
    await bus.wait_idle()

    assert broker.submitted[0]["order_type"] == "MARKET"
    assert broker.submitted[0]["price"] is None
    assert task.submit_order_type == "MARKET"
    assert task.submit_quote_last_done == pytest.approx(9.5)
```

After:

```python
@pytest.mark.asyncio
async def test_buy_limit_at_last_done_when_quote_below_signal():
    """BUY + last_done < signal → LIMIT @ last_done (取更低价)."""
    bus = EventBus()
    broker = _RecordingBroker()
    broker.quote_last["TSLL.US"] = 9.5
    page_settings = PageSettings(
        dedupe_processed_messages=True,
        price_deviation_tolerance=1.0,
        tickers={"TSLL": TickerConfig(trade_quantity=100)},
    )
    register_trader(bus, broker, _config(), registry=_registry_with(page_settings))

    task = _stock_task("TSLL", position_size="常规仓", price=10.0)
    await bus.publish(Event(Topics.TASK_INSTRUCTION_READY, TaskPayload(task)))
    await bus.wait_idle()

    assert broker.submitted[0]["order_type"] == "LIMIT"
    assert broker.submitted[0]["price"] == pytest.approx(9.5)
    assert task.submit_order_type == "LIMIT"
    assert task.submit_quote_last_done == pytest.approx(9.5)
```

- [ ] **Step 4: Rename + rewrite `test_sell_market_when_quote_above_signal` in same file**

At line 330-361. Before:

```python
@pytest.mark.asyncio
async def test_sell_market_when_quote_above_signal():
    bus = EventBus()
    broker = _RecordingBroker()
    broker.quote_last["TSLL.US"] = 10.5
    page_settings = PageSettings(
        dedupe_processed_messages=True,
        price_deviation_tolerance=1.0,
        tickers={"TSLL": TickerConfig(trade_quantity=100)},
    )
    register_trader(bus, broker, _config(), registry=_registry_with(page_settings))

    task = _stock_task("TSLL", position_size="常规仓", price=10.0)
    task.instruction = StockInstruction(  # type: ignore[assignment]
        instruction_type=InstructionType.SELL,
        price=10.0,
        price_range=None,
        quantity=100,
        position_size="常规仓",
        stop_loss_price=None,
        take_profit_price=None,
        context_source=None,
        parser_notes=[],
        ticker="TSLL",
        symbol="TSLL.US",
        sell_quantity=None,
    )
    await bus.publish(Event(Topics.TASK_INSTRUCTION_READY, TaskPayload(task)))
    await bus.wait_idle()

    assert broker.submitted[0]["order_type"] == "MARKET"
    assert broker.submitted[0]["side"] == "SELL"
```

After:

```python
@pytest.mark.asyncio
async def test_sell_limit_at_last_done_when_quote_above_signal():
    """SELL + last_done > signal → LIMIT @ last_done (取更高价)."""
    bus = EventBus()
    broker = _RecordingBroker()
    broker.quote_last["TSLL.US"] = 10.5
    page_settings = PageSettings(
        dedupe_processed_messages=True,
        price_deviation_tolerance=1.0,
        tickers={"TSLL": TickerConfig(trade_quantity=100)},
    )
    register_trader(bus, broker, _config(), registry=_registry_with(page_settings))

    task = _stock_task("TSLL", position_size="常规仓", price=10.0)
    task.instruction = StockInstruction(  # type: ignore[assignment]
        instruction_type=InstructionType.SELL,
        price=10.0,
        price_range=None,
        quantity=100,
        position_size="常规仓",
        stop_loss_price=None,
        take_profit_price=None,
        context_source=None,
        parser_notes=[],
        ticker="TSLL",
        symbol="TSLL.US",
        sell_quantity=None,
    )
    await bus.publish(Event(Topics.TASK_INSTRUCTION_READY, TaskPayload(task)))
    await bus.wait_idle()

    assert broker.submitted[0]["order_type"] == "LIMIT"
    assert broker.submitted[0]["side"] == "SELL"
    assert broker.submitted[0]["price"] == pytest.approx(10.5)
    assert task.submit_order_type == "LIMIT"
```

- [ ] **Step 5: Run unit tests — verify they FAIL**

```bash
cd backend && uv run pytest tests/broker/test_trader.py tests/broker/test_trader_deviation.py -v 2>&1 | tail -40
```

Expected: at least 4 failures (`test_stock_buy_happy_path`, `test_option_buy_happy_path`, `test_buy_limit_at_last_done_when_quote_below_signal`, `test_sell_limit_at_last_done_when_quote_above_signal`) because the production decision function still returns `"MARKET"`.

- [ ] **Step 6: Rewrite `_decide_order_type_and_context` in `backend/app/broker/trader.py`**

Replace lines 78-119. Before:

```python
def _decide_order_type_and_context(
    *,
    side: InstructionType,
    signal_price: float,
    last_done: float | None,
) -> tuple[OrderType, float | None, str]:
    """Return ``(order_type, submit_price, rationale_cn)``.

    ``submit_price`` is the limit price for LIMIT orders, or ``None`` for MARKET
    (broker ignores it for MO).
    """
    if last_done is None:
        return (
            "LIMIT",
            signal_price,
            f"未取到有效现价 → 限价单 @ {signal_price:.3f}",
        )
    if side == InstructionType.BUY:
        if last_done < signal_price:
            return (
                "MARKET",
                None,
                f"买入：现价 {last_done:.3f} < 信号价 {signal_price:.3f} → 市价单",
            )
        return (
            "LIMIT",
            signal_price,
            f"买入：现价 {last_done:.3f} ≥ 信号价 {signal_price:.3f} → 限价单 @ {signal_price:.3f}",
        )
    if side == InstructionType.SELL:
        if last_done > signal_price:
            return (
                "MARKET",
                None,
                f"卖出：现价 {last_done:.3f} > 信号价 {signal_price:.3f} → 市价单",
            )
        return (
            "LIMIT",
            signal_price,
            f"卖出：现价 {last_done:.3f} ≤ 信号价 {signal_price:.3f} → 限价单 @ {signal_price:.3f}",
        )
    return "LIMIT", signal_price, f"未知方向 → 限价单 @ {signal_price:.3f}"
```

After:

```python
def _decide_order_type_and_context(
    *,
    side: InstructionType,
    signal_price: float,
    last_done: float | None,
) -> tuple[OrderType, float | None, str]:
    """Return ``(order_type, submit_price, rationale_cn)``.

    Always emits LIMIT orders. When the live quote is more favorable than the
    signal price (lower for BUY, higher for SELL), the limit price tracks the
    live quote — otherwise it stays at the signal price. ``submit_price`` is
    the limit price; ``None`` is reserved for the unused MARKET path.
    """
    if last_done is None:
        return (
            "LIMIT",
            signal_price,
            f"未取到有效现价 → 限价单 @ {signal_price:.3f}",
        )
    if side == InstructionType.BUY:
        if last_done < signal_price:
            return (
                "LIMIT",
                last_done,
                f"买入：现价 {last_done:.3f} < 信号价 {signal_price:.3f} → 限价单 @ {last_done:.3f}（取更低价）",
            )
        return (
            "LIMIT",
            signal_price,
            f"买入：现价 {last_done:.3f} ≥ 信号价 {signal_price:.3f} → 限价单 @ {signal_price:.3f}",
        )
    if side == InstructionType.SELL:
        if last_done > signal_price:
            return (
                "LIMIT",
                last_done,
                f"卖出：现价 {last_done:.3f} > 信号价 {signal_price:.3f} → 限价单 @ {last_done:.3f}（取更高价）",
            )
        return (
            "LIMIT",
            signal_price,
            f"卖出：现价 {last_done:.3f} ≤ 信号价 {signal_price:.3f} → 限价单 @ {signal_price:.3f}",
        )
    return "LIMIT", signal_price, f"未知方向 → 限价单 @ {signal_price:.3f}"
```

- [ ] **Step 7: Re-run unit tests — verify they now PASS**

```bash
cd backend && uv run pytest tests/broker/test_trader.py tests/broker/test_trader_deviation.py -v 2>&1 | tail -40
```

Expected: all green.

- [ ] **Step 8: Do not commit yet — Task 2 finishes the integration tests**

---

## Task 2: Update integration test docstrings/comments

**Files:**

- Modify: `backend/tests/integration/test_broker_lifecycle.py:151`
- Modify: `backend/tests/integration/test_acceptance.py:213,236,289`

These tests don't deeply assert on `order_type`; one assertion in `test_acceptance.py:289` does need flipping, the rest are stale comments/docstrings that document the old behavior.

- [ ] **Step 1: Fix inline comment in `test_broker_lifecycle.py`**

At line 151. Before:

```python
    client.quote_by_symbol["TSLL.US"] = 25.0  # < signal 26.5 → BUY MARKET
```

After:

```python
    client.quote_by_symbol["TSLL.US"] = 25.0  # < signal 26.5 → BUY LIMIT @ 25.0
```

- [ ] **Step 2: Update docstring + comment in `test_acceptance.py`**

At line 213. Before:

```python
        order submitted with computed qty (700 * 0.5 = 350); order_type follows
        quote vs signal (here: MARKET when last_done < signal).
```

After:

```python
        order submitted with computed qty (700 * 0.5 = 350); order_type is
        always LIMIT — limit price = last_done when last_done < signal.
```

At line 236. Before:

```python
    # BUY + last_done < signal (~16.02) → MARKET
    fake_broker.quote_by_symbol["TSLL.US"] = 15.0
```

After:

```python
    # BUY + last_done 15.0 < signal ~16.02 → LIMIT @ 15.0
    fake_broker.quote_by_symbol["TSLL.US"] = 15.0
```

At line 289. Before:

```python
        assert order["order_type"] == "MARKET"
```

After:

```python
        assert order["order_type"] == "LIMIT"
        assert order["price"] == pytest.approx(15.0)
```

(`pytest` is already imported at the top of the file — no new import needed. If the test fails to find `pytest.approx`, add `import pytest` at the top.)

- [ ] **Step 3: Run the integration tests**

```bash
cd backend && uv run pytest tests/integration/test_broker_lifecycle.py tests/integration/test_acceptance.py -v 2>&1 | tail -30
```

Expected: all green.

---

## Task 3: Full backend regression + lint + commit

- [ ] **Step 1: Full backend test suite**

```bash
cd backend && uv run pytest -q 2>&1 | tail -30
```

Expected: matches the baseline pass count from P2 (no new failures, no skips that weren't there before).

- [ ] **Step 2: Lint**

```bash
cd backend && uv run ruff check app/broker/trader.py tests/broker/test_trader.py tests/broker/test_trader_deviation.py tests/integration/test_broker_lifecycle.py tests/integration/test_acceptance.py
```

Expected: `All checks passed!`

- [ ] **Step 3: Stage and commit**

```bash
git add backend/app/broker/trader.py \
        backend/tests/broker/test_trader.py \
        backend/tests/broker/test_trader_deviation.py \
        backend/tests/integration/test_broker_lifecycle.py \
        backend/tests/integration/test_acceptance.py
git status --short
```

Expected: only the 5 listed files staged; no other modifications swept in.

Commit:

```bash
git commit -m "$(cat <<'EOF'
feat(broker): always-LIMIT trader rule — drop MARKET when quote favors us

BUY/SELL now always submit LIMIT orders. When live quote is more favorable
than the signal price (lower for BUY, higher for SELL), the limit price
tracks the live quote ("占便宜"); otherwise it stays at the signal price.

Spec: docs/superpowers/specs/2026-04-29-buy-sell-limit-only-design.md
EOF
)"
```

- [ ] **Step 4: Sanity-check the diff**

```bash
git show --stat HEAD
```

Expected: 5 files changed, the production change is the small rewrite of `_decide_order_type_and_context`, the test changes match Tasks 1-2.

---

## Self-Review Notes (for the executor)

- The decision table in the spec maps 1:1 to the new function body. If you find a case in the function not covered by the spec table, stop and re-read the spec.
- `OrderType` Literal still includes `"MARKET"` — that's intentional; the broker protocol layer is left untouched in case the decision function later grows another branch.
- If you discover a test outside the four files above also asserting `order_type == "MARKET"` against trader output, that's a test the spec missed — bring it up before silently editing.
