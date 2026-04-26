# Parser Validation Harness Implementation Plan (B1)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the validation infrastructure that lets us measure stock parser quality against a hand-curated 1899-message ground truth. After this plan completes, we will be able to run `validate_parser.py` and get a quantitative PASS/FAIL report against any future parser change.

**Architecture:** Three Python files in `backend/scripts/` (golden_lib, validate_parser, build_golden) + an alias placeholder at `app/parser_v2/__init__.py` + a pytest CI wrapper. The harness runs v1 (existing `stock_parser.parse`) and v2 (currently aliased to v1) against the golden, buckets each message into regression / recovery / still_failing / false_positive, and emits a JSON report + console summary. Initial pass criteria: regressions == 0 AND chatter false-positives == 0; recovery_rate is exempted while v2 is still aliased.

**Tech Stack:** Python 3.11 + asyncio (existing). pytest. No new third-party deps. The 1899-corpus is at `data/stock_origin_message.json`; the harness will produce `data/parser_golden.json`. Tests run with `.venv/bin/python -m pytest -q` from `backend/`.

**Reference spec:** `docs/superpowers/specs/2026-04-26-parser-validation-harness-design.md`

---

## File map

**Create:**
- `backend/app/parser_v2/__init__.py` — alias placeholder; B2 will replace it
- `backend/scripts/__init__.py` — empty package marker (so pytest can `import scripts.validate_parser`)
- `backend/scripts/golden_lib.py` — schema validator + few-shot examples + subagent prompt template
- `backend/scripts/validate_parser.py` — matcher + run_validation() + CLI + console output + JSON report
- `backend/scripts/build_golden.py` — prepare + merge subcommands for golden generation flow
- `backend/tests/parser/test_parser_v2_alias.py` — verify `parser_v2.parse is stock_parser.parse` (identity)
- `backend/tests/parser/test_v2_against_golden.py` — pytest CI wrapper around `run_validation()`
- `backend/tests/scripts/__init__.py` — empty package marker for tests/scripts/
- `backend/tests/scripts/test_golden_lib.py` — schema validator unit tests
- `backend/tests/scripts/test_validate_parser.py` — matcher + run_validation unit tests with synthetic corpus
- `backend/tests/scripts/test_build_golden.py` — prepare/merge unit tests

**Modify:**
- `.gitignore` — add `data/parser_validation_report.json` and `data/golden_batches/`

**Untouched** (referenced but not modified):
- `backend/app/parser/stock_parser.py` — the v1 parser
- `data/stock_origin_message.json` — the 1899-message corpus

---

## Pre-flight

Run from `backend/`:

```bash
.venv/bin/python -m pytest -q
```

Expected: 458 passed, 2 skipped (the state after Item 2A landed). If anything is red, stop and surface — unrelated to this plan.

---

## Task 1: Bootstrap scaffolding (parser_v2 alias, packages, gitignore)

**Files:**
- Create: `backend/app/parser_v2/__init__.py`
- Create: `backend/scripts/__init__.py`
- Create: `backend/tests/scripts/__init__.py`
- Create: `backend/tests/parser/test_parser_v2_alias.py`
- Modify: `.gitignore`

This task wires the placeholder so the harness in later tasks can write `from app.parser_v2 import parse` and have it resolve to the v1 function. The pytest test pins the identity so when B2 lands, the test fails (force the implementor to update this plan / harness explicitly).

- [ ] **Step 1: Write the failing test (alias identity)**

Create `backend/tests/parser/test_parser_v2_alias.py`:

```python
"""Pin parser_v2 → stock_parser alias. Once B2 lands and parser_v2 has its
own implementation, this test fails — that's the signal to flip the harness's
exemption clause."""

from app.parser import stock_parser
from app.parser_v2 import parse as parser_v2_parse


def test_parser_v2_is_alias_of_stock_parser_parse() -> None:
    """Identity check: parser_v2.parse must be the EXACT SAME function object
    as stock_parser.parse during B1.  Use `is` not `==`. The harness's
    exemption clause depends on this identity."""
    assert parser_v2_parse is stock_parser.parse
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd backend && .venv/bin/python -m pytest tests/parser/test_parser_v2_alias.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'app.parser_v2'`.

- [ ] **Step 3: Create the alias module**

Create `backend/app/parser_v2/__init__.py`:

```python
"""parser_v2 — placeholder during B1.

Re-exports stock_parser.parse so harness code can import from a stable name.
B2 will replace this module's content with a token-based slot-filling parser.
The validate_parser harness uses `parser_v2.parse is stock_parser.parse` as
an identity check to detect the placeholder state and skip the recovery_rate
constraint until a real v2 lands.
"""

from app.parser.stock_parser import parse  # noqa: F401  — re-export

__all__ = ["parse"]
```

- [ ] **Step 4: Create empty package markers**

Create `backend/scripts/__init__.py` (empty file).
Create `backend/tests/scripts/__init__.py` (empty file).

- [ ] **Step 5: Update `.gitignore`**

Find the existing "运行时" section (last block) of `.gitignore` and append two lines:

```
data/parser_validation_report.json
data/golden_batches/
```

- [ ] **Step 6: Run the test to verify it passes**

```bash
cd backend && .venv/bin/python -m pytest tests/parser/test_parser_v2_alias.py -v
```

Expected: PASS.

Run the full suite to confirm no regression:

```bash
cd backend && .venv/bin/python -m pytest -q
```

Expected: 459 passed, 2 skipped (was 458; +1 alias test).

- [ ] **Step 7: Commit**

```bash
git add backend/app/parser_v2/ backend/scripts/__init__.py backend/tests/scripts/__init__.py backend/tests/parser/test_parser_v2_alias.py .gitignore
git commit -m "$(cat <<'EOF'
feat(parser_v2): add placeholder module aliasing stock_parser.parse

B1 harness needs a stable `app.parser_v2.parse` name to import; B2 hasn't
shipped yet so the placeholder re-exports the v1 parse function. The
identity check (parser_v2.parse is stock_parser.parse) is pinned by a
new test so when B2 lands it triggers an explicit visit to this module.

Also seeds backend/scripts/ as an importable package and gitignores the
upcoming validate_parser report + intermediate golden batch directory.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: golden_lib — schema validator + few-shot prompt template

**Files:**
- Create: `backend/scripts/golden_lib.py`
- Create: `backend/tests/scripts/test_golden_lib.py`

`golden_lib` is shared by validate_parser (which reads golden entries and trusts their shape) and build_golden (which validates subagent output before merging). It also owns the few-shot examples and the subagent prompt template.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/scripts/test_golden_lib.py`:

```python
"""Tests for scripts/golden_lib.py — schema validator + few-shot examples."""

import pytest

from scripts.golden_lib import (
    FEW_SHOT_EXAMPLES,
    validate_golden_entry,
)


def test_validates_well_formed_chatter_entry() -> None:
    entry = {
        "domID": "post_1",
        "content": "大家好",
        "classification": "chatter",
        "expected": None,
        "requires_context": False,
        "notes": "纯打招呼",
    }
    assert validate_golden_entry(entry) == []


def test_validates_well_formed_trade_signal_entry() -> None:
    entry = {
        "domID": "post_2",
        "content": "TSLL 27.2出一半",
        "classification": "trade_signal",
        "expected": {
            "instruction_type": "SELL",
            "ticker": "TSLL",
            "price": 27.2,
            "price_range": None,
            "referenced_lot_price": None,
            "sell_quantity": "1/2",
            "position_size": None,
        },
        "requires_context": False,
        "notes": "",
    }
    assert validate_golden_entry(entry) == []


def test_validates_well_formed_ambiguous_entry() -> None:
    entry = {
        "domID": "post_3",
        "content": "TSLL 跌破 11 都出",
        "classification": "ambiguous",
        "expected": None,
        "requires_context": False,
        "notes": "条件触发",
    }
    assert validate_golden_entry(entry) == []


def test_rejects_missing_required_field() -> None:
    entry = {
        "domID": "post_x",
        "content": "x",
        "classification": "chatter",
        # missing: expected, requires_context, notes
    }
    errors = validate_golden_entry(entry)
    assert any("expected" in e for e in errors)
    assert any("requires_context" in e for e in errors)
    assert any("notes" in e for e in errors)


def test_rejects_bad_classification_value() -> None:
    entry = {
        "domID": "post_x",
        "content": "x",
        "classification": "garbage",
        "expected": None,
        "requires_context": False,
        "notes": "",
    }
    errors = validate_golden_entry(entry)
    assert any("classification" in e for e in errors)


def test_rejects_chatter_with_non_null_expected() -> None:
    entry = {
        "domID": "post_x",
        "content": "x",
        "classification": "chatter",
        "expected": {"instruction_type": "SELL", "ticker": "X", "price": 1.0,
                     "price_range": None, "referenced_lot_price": None,
                     "sell_quantity": None, "position_size": None},
        "requires_context": False,
        "notes": "",
    }
    errors = validate_golden_entry(entry)
    assert any("chatter" in e and "expected" in e for e in errors)


def test_rejects_ambiguous_with_non_null_expected() -> None:
    entry = {
        "domID": "post_x",
        "content": "x",
        "classification": "ambiguous",
        "expected": {"instruction_type": "SELL", "ticker": "X", "price": 1.0,
                     "price_range": None, "referenced_lot_price": None,
                     "sell_quantity": None, "position_size": None},
        "requires_context": False,
        "notes": "",
    }
    errors = validate_golden_entry(entry)
    assert any("ambiguous" in e and "expected" in e for e in errors)


def test_rejects_trade_signal_with_null_expected() -> None:
    entry = {
        "domID": "post_x",
        "content": "x",
        "classification": "trade_signal",
        "expected": None,
        "requires_context": False,
        "notes": "",
    }
    errors = validate_golden_entry(entry)
    assert any("trade_signal" in e and "expected" in e for e in errors)


def test_rejects_trade_signal_with_missing_expected_field() -> None:
    entry = {
        "domID": "post_x",
        "content": "x",
        "classification": "trade_signal",
        "expected": {"instruction_type": "SELL", "ticker": "X", "price": 1.0},
        # missing: price_range, referenced_lot_price, sell_quantity, position_size
        "requires_context": False,
        "notes": "",
    }
    errors = validate_golden_entry(entry)
    assert any("price_range" in e for e in errors)
    assert any("referenced_lot_price" in e for e in errors)
    assert any("sell_quantity" in e for e in errors)
    assert any("position_size" in e for e in errors)


def test_rejects_trade_signal_with_bad_instruction_type() -> None:
    entry = {
        "domID": "post_x",
        "content": "x",
        "classification": "trade_signal",
        "expected": {
            "instruction_type": "CLOSE",
            "ticker": "X", "price": 1.0,
            "price_range": None, "referenced_lot_price": None,
            "sell_quantity": None, "position_size": None,
        },
        "requires_context": False,
        "notes": "",
    }
    errors = validate_golden_entry(entry)
    assert any("instruction_type" in e for e in errors)


def test_few_shot_examples_are_themselves_valid() -> None:
    """All 10 baked-in few-shot examples must pass schema validation."""
    for i, entry in enumerate(FEW_SHOT_EXAMPLES):
        errors = validate_golden_entry(entry)
        assert errors == [], f"few-shot example {i} fails validation: {errors}"


def test_few_shot_covers_all_classifications() -> None:
    classifications = {e["classification"] for e in FEW_SHOT_EXAMPLES}
    assert classifications == {"chatter", "trade_signal", "ambiguous"}
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd backend && .venv/bin/python -m pytest tests/scripts/test_golden_lib.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'scripts.golden_lib'`.

- [ ] **Step 3: Implement golden_lib**

Create `backend/scripts/golden_lib.py`:

```python
"""golden_lib — shared types & schema for parser_golden.json.

Two consumers:
  - scripts/validate_parser.py: reads golden, trusts schema (validate eagerly)
  - scripts/build_golden.py: validates subagent output before merging

Plus the few-shot examples + subagent prompt template used during
golden generation.

The golden file format and field semantics are defined in
docs/superpowers/specs/2026-04-26-parser-validation-harness-design.md
sections 6 and 7.
"""

from __future__ import annotations

from typing import Any

CLASSIFICATIONS = {"chatter", "trade_signal", "ambiguous"}
INSTRUCTION_TYPES = {"BUY", "SELL"}

EXPECTED_FIELDS = (
    "instruction_type",
    "ticker",
    "price",
    "price_range",
    "referenced_lot_price",
    "sell_quantity",
    "position_size",
)

ENTRY_FIELDS = (
    "domID",
    "content",
    "classification",
    "expected",
    "requires_context",
    "notes",
)


def validate_golden_entry(entry: Any) -> list[str]:
    """Return a list of human-readable error messages; [] = valid.

    Checks structural shape, classification value, and the conditional
    constraints on `expected` (must be null for chatter/ambiguous, must
    be a 7-field dict for trade_signal). Does NOT validate cross-entry
    invariants like uniqueness of domID — that belongs to the merge step.
    """
    errors: list[str] = []

    if not isinstance(entry, dict):
        return [f"entry is not a dict: {type(entry).__name__}"]

    for field in ENTRY_FIELDS:
        if field not in entry:
            errors.append(f"missing field: {field}")

    if errors:
        # Don't bother with deeper checks on a malformed shape
        return errors

    if not isinstance(entry["domID"], str) or not entry["domID"]:
        errors.append("domID must be a non-empty string")
    if not isinstance(entry["content"], str):
        errors.append("content must be a string")
    if entry["classification"] not in CLASSIFICATIONS:
        errors.append(
            f"classification must be one of {CLASSIFICATIONS}, "
            f"got {entry['classification']!r}"
        )
    if not isinstance(entry["requires_context"], bool):
        errors.append("requires_context must be bool")
    if not isinstance(entry["notes"], str):
        errors.append("notes must be string")

    cls = entry["classification"]
    expected = entry["expected"]

    if cls in {"chatter", "ambiguous"}:
        if expected is not None:
            errors.append(f"{cls} entry must have expected=null")
    elif cls == "trade_signal":
        if expected is None:
            errors.append("trade_signal entry must have non-null expected")
        elif not isinstance(expected, dict):
            errors.append("trade_signal expected must be a dict")
        else:
            errors.extend(_validate_expected_dict(expected))

    return errors


def _validate_expected_dict(expected: dict) -> list[str]:
    errors: list[str] = []

    for field in EXPECTED_FIELDS:
        if field not in expected:
            errors.append(f"expected missing field: {field}")

    if errors:
        return errors

    if expected["instruction_type"] not in INSTRUCTION_TYPES:
        errors.append(
            f"expected.instruction_type must be one of {INSTRUCTION_TYPES}, "
            f"got {expected['instruction_type']!r}"
        )

    if not isinstance(expected["ticker"], str) or not expected["ticker"]:
        errors.append("expected.ticker must be non-empty string")

    for fname in ("price", "referenced_lot_price"):
        v = expected[fname]
        if v is not None and not isinstance(v, (int, float)):
            errors.append(f"expected.{fname} must be float or null")

    pr = expected["price_range"]
    if pr is not None:
        if not (isinstance(pr, list) and len(pr) == 2
                and all(isinstance(x, (int, float)) for x in pr)):
            errors.append("expected.price_range must be [low, high] floats or null")

    for fname in ("sell_quantity", "position_size"):
        v = expected[fname]
        if v is not None and not isinstance(v, str):
            errors.append(f"expected.{fname} must be string or null")

    return errors


# ---------------------------------------------------------------------------
# Few-shot examples — embedded in subagent prompt during golden generation.
# These are NOT entries in the actual golden; they're illustrations.
# ---------------------------------------------------------------------------

FEW_SHOT_EXAMPLES: list[dict[str, Any]] = [
    {
        "domID": "few_shot_chatter_greeting",
        "content": "大家好",
        "classification": "chatter",
        "expected": None,
        "requires_context": False,
        "notes": "纯打招呼",
    },
    {
        "domID": "few_shot_chatter_observation",
        "content": "今天大盘看起来要回调",
        "classification": "chatter",
        "expected": None,
        "requires_context": False,
        "notes": "市场观察，无 ticker / 无动作",
    },
    {
        "domID": "few_shot_sell_basic",
        "content": "TSLL 27.2出一半",
        "classification": "trade_signal",
        "expected": {
            "instruction_type": "SELL",
            "ticker": "TSLL",
            "price": 27.2,
            "price_range": None,
            "referenced_lot_price": None,
            "sell_quantity": "1/2",
            "position_size": None,
        },
        "requires_context": False,
        "notes": "",
    },
    {
        "domID": "few_shot_sell_with_lot_ref",
        "content": "12.87减一半12.42的tsll",
        "classification": "trade_signal",
        "expected": {
            "instruction_type": "SELL",
            "ticker": "TSLL",
            "price": 12.87,
            "price_range": None,
            "referenced_lot_price": 12.42,
            "sell_quantity": "1/2",
            "position_size": None,
        },
        "requires_context": False,
        "notes": "",
    },
    {
        "domID": "few_shot_buy_position_size",
        "content": "tsll 11.5 附近建仓常规仓的一半",
        "classification": "trade_signal",
        "expected": {
            "instruction_type": "BUY",
            "ticker": "TSLL",
            "price": 11.5,
            "price_range": None,
            "referenced_lot_price": None,
            "sell_quantity": None,
            "position_size": "常规仓的一半",
        },
        "requires_context": False,
        "notes": "",
    },
    {
        "domID": "few_shot_sell_price_range",
        "content": "TSLL 27-27.5 区间出一半",
        "classification": "trade_signal",
        "expected": {
            "instruction_type": "SELL",
            "ticker": "TSLL",
            "price": None,
            "price_range": [27.0, 27.5],
            "referenced_lot_price": None,
            "sell_quantity": "1/2",
            "position_size": None,
        },
        "requires_context": False,
        "notes": "",
    },
    {
        "domID": "few_shot_sell_requires_context",
        "content": "15.2 全出",
        "classification": "trade_signal",
        "expected": {
            "instruction_type": "SELL",
            "ticker": "TSLL",
            "price": 15.2,
            "price_range": None,
            "referenced_lot_price": None,
            "sell_quantity": "全部",
            "position_size": None,
        },
        "requires_context": True,
        "notes": "ticker 来自 history 上一条 'tsll 14.6 买入'",
    },
    {
        "domID": "few_shot_ambiguous_stop_loss",
        "content": "hims剩下一半设置下跌破54.4都出",
        "classification": "ambiguous",
        "expected": None,
        "requires_context": False,
        "notes": "止损条件，v2 范围外",
    },
    {
        "domID": "few_shot_ambiguous_conditional",
        "content": "TSLL 跌破 11 都出",
        "classification": "ambiguous",
        "expected": None,
        "requires_context": False,
        "notes": "条件性触发，非即时指令",
    },
    {
        "domID": "few_shot_ambiguous_multi",
        "content": "21.7 也减仓点 tsll 剩下原始持仓的一半博弈下发布会 发布会边拉升边出 跌破 21.3 都出",
        "classification": "ambiguous",
        "expected": None,
        "requires_context": False,
        "notes": "首句即时指令 + 计划 + 止损条件混合，整体不可机器化",
    },
]


# ---------------------------------------------------------------------------
# Subagent prompt template for golden generation.
# Placeholders: {{FEW_SHOT_JSON}}, {{INPUT_JSON}}
# ---------------------------------------------------------------------------

BUILD_PROMPT_TEMPLATE = """\
你正在为 stock 信号 parser 验证项目标注 golden truth。

任务：从下面给的原始消息数组（共 N 条），为每条产出一个 golden entry。

### 分类规则

trade_signal: 同时满足
  (1) 明确动作动词（买/卖/出/开/加/减/吸/兑现/建仓/平仓 ...）
  (2) 引用 ticker（大写 2-5 字母 或 中文别名 或 history/refer 提供）
  (3) 至少一个具体价格

chatter: 纯打招呼、纯观察、提问、emoji。

ambiguous:
  - 条件 / 假设（"跌破 X 都出"）
  - 止损 / 止盈
  - 观察夹带半提示（有 ticker 但无明确动作动词）
  - 多指令并列

### expected schema (trade_signal 必填)

7 字段，缺省填 null（不要省略 key）：
  instruction_type ("BUY"|"SELL"),
  ticker (uppercase),
  price (float|null),
  price_range ([low,high]|null),
  referenced_lot_price (float|null),
  sell_quantity (str|null),
  position_size (str|null)

chatter / ambiguous 的 expected 一律 null。

### requires_context

trade_signal 中：
  - 如果 ticker / price 完全在 content 里 → false
  - 如果 ticker / price 需要看 history 才能知道 → true

chatter / ambiguous 一律 false。

### Few-shot 示例

{FEW_SHOT_JSON}

### 输入

{INPUT_JSON}

### 输出

纯 JSON 数组，N 条 entry，顺序与输入一致。每条含 6 字段：
  domID, content, classification, expected, requires_context, notes

不要其他文字。
"""
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
cd backend && .venv/bin/python -m pytest tests/scripts/test_golden_lib.py -v
```

Expected: 12 tests PASS.

Run full suite:

```bash
cd backend && .venv/bin/python -m pytest -q
```

Expected: 471 passed, 2 skipped (was 459; +12).

- [ ] **Step 5: Commit**

```bash
git add backend/scripts/golden_lib.py backend/tests/scripts/test_golden_lib.py
git commit -m "$(cat <<'EOF'
feat(scripts): add golden_lib — schema + few-shot for parser_golden.json

validate_golden_entry checks the entry shape: required fields, valid
classification value, and the conditional constraint that expected
must be null for chatter/ambiguous and a 7-field dict for trade_signal.
Used by both the validate_parser harness (read path) and the
build_golden tool (write/merge path).

Also bakes in 10 few-shot examples covering chatter / standard
SELL / SELL+lot ref / BUY+position_size / price_range / context-needing
SELL / 3 ambiguous flavors. The examples self-test via
test_few_shot_examples_are_themselves_valid.

Plus the BUILD_PROMPT_TEMPLATE used by build_golden.py to construct
each subagent's prompt.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: matcher + diff types in `validate_parser.py`

**Files:**
- Create: `backend/scripts/validate_parser.py` (matcher block only — run_validation comes in Task 4)
- Create: `backend/tests/scripts/test_validate_parser.py`

The `match()` function decides whether a parser output matches a golden expected dict. It owns float tolerance, range comparison, and the field-by-field comparison defined in spec section 6.3.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/scripts/test_validate_parser.py`:

```python
"""Tests for scripts/validate_parser.py — matcher + run_validation."""

import pytest

from app.domain.instruction import InstructionType, StockInstruction
from scripts.validate_parser import match


def _stock(
    *,
    instruction_type: InstructionType = InstructionType.SELL,
    ticker: str = "TSLL",
    price: float | None = 27.2,
    price_range: tuple[float, float] | None = None,
    referenced_lot_price: float | None = None,
    sell_quantity: str | None = None,
    position_size: str | None = None,
) -> StockInstruction:
    return StockInstruction(
        instruction_type=instruction_type,
        price=price,
        price_range=price_range,
        quantity=None,
        position_size=position_size,
        stop_loss_price=None,
        take_profit_price=None,
        context_source=None,
        parser_notes=[],
        ticker=ticker,
        symbol=f"{ticker}.US",
        sell_quantity=sell_quantity,
        referenced_lot_price=referenced_lot_price,
    )


def _expected(**overrides) -> dict:
    base = {
        "instruction_type": "SELL",
        "ticker": "TSLL",
        "price": 27.2,
        "price_range": None,
        "referenced_lot_price": None,
        "sell_quantity": None,
        "position_size": None,
    }
    base.update(overrides)
    return base


def test_match_both_none_passes() -> None:
    assert match(None, None) is True


def test_match_one_none_fails() -> None:
    assert match(_stock(), None) is False
    assert match(None, _expected()) is False


def test_match_identical_passes() -> None:
    assert match(_stock(), _expected()) is True


def test_match_different_instruction_type_fails() -> None:
    assert match(_stock(instruction_type=InstructionType.BUY), _expected()) is False


def test_match_different_ticker_fails() -> None:
    assert match(_stock(ticker="HOOD"), _expected()) is False


def test_match_price_within_tolerance_passes() -> None:
    # 0.0009 difference < 0.001 tolerance
    assert match(_stock(price=27.2009), _expected(price=27.2)) is True


def test_match_price_outside_tolerance_fails() -> None:
    assert match(_stock(price=27.21), _expected(price=27.2)) is False


def test_match_price_one_null_fails() -> None:
    assert match(_stock(price=None), _expected(price=27.2)) is False


def test_match_price_both_null_passes() -> None:
    assert match(_stock(price=None, price_range=(27.0, 27.5)),
                 _expected(price=None, price_range=[27.0, 27.5])) is True


def test_match_price_range_within_tolerance_passes() -> None:
    assert match(_stock(price=None, price_range=(27.0009, 27.5)),
                 _expected(price=None, price_range=[27.0, 27.5])) is True


def test_match_price_range_outside_tolerance_fails() -> None:
    assert match(_stock(price=None, price_range=(27.1, 27.5)),
                 _expected(price=None, price_range=[27.0, 27.5])) is False


def test_match_referenced_lot_price_compared() -> None:
    assert match(_stock(referenced_lot_price=12.42),
                 _expected(referenced_lot_price=12.42)) is True
    assert match(_stock(referenced_lot_price=12.42),
                 _expected(referenced_lot_price=12.5)) is False


def test_match_sell_quantity_strict() -> None:
    assert match(_stock(sell_quantity="1/2"), _expected(sell_quantity="1/2")) is True
    assert match(_stock(sell_quantity="一半"), _expected(sell_quantity="1/2")) is False


def test_match_position_size_strict() -> None:
    assert match(_stock(position_size="常规仓的一半"),
                 _expected(position_size="常规仓的一半")) is True


def test_match_ticker_case_sensitive_uppercase() -> None:
    """Ticker comes uppercase from _make_stock; expected also uppercase. Match is direct."""
    assert match(_stock(ticker="TSLL"), _expected(ticker="TSLL")) is True
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd backend && .venv/bin/python -m pytest tests/scripts/test_validate_parser.py -v
```

Expected: FAIL — `ImportError: cannot import name 'match' from 'scripts.validate_parser'`.

- [ ] **Step 3: Create validate_parser.py with the matcher**

Create `backend/scripts/validate_parser.py`:

```python
"""validate_parser — diff stock parser outputs against parser_golden.json.

Public surface:
  - match(out, expected) -> bool          — single-message comparator
  - run_validation(...) -> ValidationResult — full harness over corpus + golden
  - main()                                — CLI entrypoint

run_validation and CLI are added in later tasks of this plan; this file
starts with the matcher only.

Match semantics — see spec section 6.3:
  strict equality:    instruction_type, ticker, sell_quantity, position_size
  ±0.001 tolerance:   price, referenced_lot_price, price_range (both ends)
  ignored:            parser_notes, context_source, symbol, quantity,
                      raw_message, message_id, stop_loss_price, take_profit_price
"""

from __future__ import annotations

from typing import Any

from app.domain.instruction import StockInstruction

PRICE_TOLERANCE = 0.001


def _float_eq(a: float | None, b: float | None, tol: float = PRICE_TOLERANCE) -> bool:
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    return abs(a - b) <= tol


def _range_eq(
    a: tuple[float, float] | None,
    b: list[float] | tuple[float, float] | None,
    tol: float = PRICE_TOLERANCE,
) -> bool:
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    return _float_eq(a[0], b[0], tol) and _float_eq(a[1], b[1], tol)


def match(out: StockInstruction | None, expected: dict[str, Any] | None) -> bool:
    """Return True iff parser output matches the golden expected dict.

    None on either side: must both be None to match. Non-None on both sides:
    compare 7 load-bearing fields per spec 6.3 rules.
    """
    if out is None and expected is None:
        return True
    if out is None or expected is None:
        return False

    if out.instruction_type.name != expected["instruction_type"]:
        return False
    if out.ticker.upper() != expected["ticker"]:
        return False
    if not _float_eq(out.price, expected["price"]):
        return False
    if not _range_eq(out.price_range, expected["price_range"]):
        return False
    if not _float_eq(out.referenced_lot_price, expected["referenced_lot_price"]):
        return False
    if (out.sell_quantity or None) != (expected["sell_quantity"] or None):
        return False
    if (out.position_size or None) != (expected["position_size"] or None):
        return False
    return True
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
cd backend && .venv/bin/python -m pytest tests/scripts/test_validate_parser.py -v
```

Expected: 15 matcher tests PASS.

Run full suite:

```bash
cd backend && .venv/bin/python -m pytest -q
```

Expected: 486 passed, 2 skipped (was 471; +15).

- [ ] **Step 5: Commit**

```bash
git add backend/scripts/validate_parser.py backend/tests/scripts/test_validate_parser.py
git commit -m "$(cat <<'EOF'
feat(scripts): add validate_parser.match() — golden-vs-output comparator

Strict equality for instruction_type / ticker / sell_quantity /
position_size; ±0.001 float tolerance for price / referenced_lot_price /
price_range. Ignores parser_notes / context_source / symbol / quantity /
raw_message / message_id / stop_loss_price / take_profit_price (per
spec 6.3 ignored-fields list).

15 unit tests cover both-null, one-null, identity, mismatch on each
field, tolerance edges, and price_range two-end comparison.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: validate_parser core — `run_validation()` + bucketing

**Files:**
- Modify: `backend/scripts/validate_parser.py` (append types + run_validation)
- Modify: `backend/tests/scripts/test_validate_parser.py` (append run_validation tests)

`run_validation()` loads the corpus and golden, runs v1 + v2, partitions each message into the right bucket, computes the summary, and decides PASS/FAIL.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/scripts/test_validate_parser.py`:

```python
import json
from pathlib import Path

from scripts.validate_parser import (
    Diff,
    ValidationResult,
    run_validation,
)


def _write_corpus(tmp_path: Path, entries: list[dict]) -> Path:
    p = tmp_path / "corpus.json"
    p.write_text(json.dumps(entries, ensure_ascii=False))
    return p


def _write_golden(tmp_path: Path, entries: list[dict]) -> Path:
    p = tmp_path / "golden.json"
    p.write_text(json.dumps(entries, ensure_ascii=False))
    return p


def _msg(domid: str, content: str) -> dict:
    return {"domID": domid, "content": content,
            "timestamp": "2025-10-07 00:00:00.000",
            "refer": None, "position": "single", "history": []}


def _gold_chatter(domid: str, content: str) -> dict:
    return {"domID": domid, "content": content,
            "classification": "chatter", "expected": None,
            "requires_context": False, "notes": ""}


def _gold_ambiguous(domid: str, content: str, notes: str = "") -> dict:
    return {"domID": domid, "content": content,
            "classification": "ambiguous", "expected": None,
            "requires_context": False, "notes": notes}


def _gold_signal(domid: str, content: str, expected: dict, *, requires_context: bool = False) -> dict:
    return {"domID": domid, "content": content,
            "classification": "trade_signal", "expected": expected,
            "requires_context": requires_context, "notes": ""}


def _expected(**overrides) -> dict:
    base = {
        "instruction_type": "SELL",
        "ticker": "TSLL",
        "price": 27.2,
        "price_range": None,
        "referenced_lot_price": None,
        "sell_quantity": "1/2",
        "position_size": None,
    }
    base.update(overrides)
    return base


def test_run_validation_alias_exemption_skips_recovery_check(tmp_path: Path) -> None:
    """When parser_v2.parse is stock_parser.parse (the B1 alias), recovery
    constraint must be skipped — even if v1 fails on real signals."""
    corpus = [_msg("m1", "TSLL 27.2出一半"),  # v1 parses, expected matches
              _msg("m2", "未知形状的信号 28.4 出 hood")]  # v1 may fail
    golden = [_gold_signal("m1", "TSLL 27.2出一半", _expected()),
              _gold_signal("m2", "未知形状的信号 28.4 出 hood",
                           _expected(ticker="HOOD", price=28.4))]
    result = run_validation(
        corpus_path=_write_corpus(tmp_path, corpus),
        golden_path=_write_golden(tmp_path, golden),
    )
    # Under alias mode: regressions=0 and chatter_fp=0 enough for PASS,
    # regardless of how many trade_signals v2 still misses.
    assert result.summary.passed is True
    assert result.summary.recovery_rate is None  # exempt → undefined


def test_run_validation_chatter_false_positive_fails(tmp_path: Path, monkeypatch) -> None:
    """If v2 (= v1 in alias mode) returns non-None on a chatter message,
    that's a false positive and run_validation must report it."""
    # We can't easily make stock_parser.parse return non-None on chatter,
    # so simulate by patching parser_v2.parse to a stub that always
    # returns a non-None instruction, AND override the alias check.
    from scripts import validate_parser as vp

    def _fake_parse(content, *, message_id):
        return _stock()  # always returns SELL TSLL 27.2

    monkeypatch.setattr(vp, "_v1_parse", _fake_parse)
    monkeypatch.setattr(vp, "_v2_parse", _fake_parse)
    monkeypatch.setattr(vp, "_v2_is_alias_of_v1", lambda: False)

    corpus = [_msg("c1", "大家好")]
    golden = [_gold_chatter("c1", "大家好")]
    result = run_validation(
        corpus_path=_write_corpus(tmp_path, corpus),
        golden_path=_write_golden(tmp_path, golden),
    )
    assert len(result.false_positives_on_chatter_v2) == 1
    assert result.summary.passed is False


def test_run_validation_ambiguous_skipped(tmp_path: Path) -> None:
    corpus = [_msg("a1", "TSLL 跌破 11 都出")]
    golden = [_gold_ambiguous("a1", "TSLL 跌破 11 都出", "条件触发")]
    result = run_validation(
        corpus_path=_write_corpus(tmp_path, corpus),
        golden_path=_write_golden(tmp_path, golden),
    )
    assert result.summary.by_classification["ambiguous"] == 1
    # Ambiguous never enters regression / recovery / still_failing buckets
    assert len(result.regressions) == 0
    assert len(result.recoveries) == 0
    assert len(result.still_failing_non_context) == 0


def test_run_validation_requires_context_separate_bucket(tmp_path: Path) -> None:
    """A trade_signal with requires_context=True doesn't enter regression /
    recovery / still_failing_non_context — it goes to its own bucket."""
    corpus = [_msg("r1", "15.2 全出")]  # parser can't extract ticker
    golden = [_gold_signal(
        "r1", "15.2 全出",
        _expected(ticker="TSLL", price=15.2, sell_quantity="全部"),
        requires_context=True,
    )]
    result = run_validation(
        corpus_path=_write_corpus(tmp_path, corpus),
        golden_path=_write_golden(tmp_path, golden),
    )
    assert len(result.still_failing_context_dependent) == 1
    assert len(result.still_failing_non_context) == 0
    # still_failing_context_dependent does NOT block PASS (informational)
    assert result.summary.passed is True


def test_run_validation_counts_classifications(tmp_path: Path) -> None:
    corpus = [
        _msg("a", "大家好"),
        _msg("b", "TSLL 跌破 11 都出"),
        _msg("c", "TSLL 27.2出一半"),
    ]
    golden = [
        _gold_chatter("a", "大家好"),
        _gold_ambiguous("b", "TSLL 跌破 11 都出"),
        _gold_signal("c", "TSLL 27.2出一半", _expected()),
    ]
    result = run_validation(
        corpus_path=_write_corpus(tmp_path, corpus),
        golden_path=_write_golden(tmp_path, golden),
    )
    assert result.summary.by_classification == {
        "chatter": 1, "ambiguous": 1, "trade_signal": 1,
    }
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd backend && .venv/bin/python -m pytest tests/scripts/test_validate_parser.py -v
```

Expected: FAIL — `ImportError: cannot import name 'run_validation'`.

- [ ] **Step 3: Append run_validation + types to validate_parser.py**

Add to `backend/scripts/validate_parser.py` (after the existing `match` function):

```python
import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from app.parser import stock_parser
from app.parser_v2 import parse as _parser_v2_parse


# Module-level alias indirection so tests can monkeypatch
_v1_parse: Callable = stock_parser.parse
_v2_parse: Callable = _parser_v2_parse


def _v2_is_alias_of_v1() -> bool:
    """True iff parser_v2.parse is the same function object as stock_parser.parse.
    During B1 the alias holds; B2 will replace parser_v2.__init__ with a real
    implementation, breaking the identity and triggering recovery_rate enforcement."""
    return _v2_parse is _v1_parse


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass
class Diff:
    """One per-message diff entry, used in regression / recovery / etc lists."""
    domID: str
    content: str
    v1: dict[str, object] | None  # serialized StockInstruction or None
    v2: dict[str, object] | None
    expected: dict[str, object] | None


@dataclass
class Summary:
    total: int
    by_classification: dict[str, int]
    trade_signals_single_msg_solvable: int
    trade_signals_requires_context: int
    v1_pass_single_msg: int
    v1_fail_single_msg: int
    v2_pass_single_msg: int
    v2_fail_single_msg: int
    regressions: int
    recoveries: int
    recovery_rate: float | None  # None when alias-exempt or denominator 0
    false_positives_on_chatter_v2: int
    still_failing_context_dependent: int
    passed: bool


@dataclass
class ValidationResult:
    summary: Summary
    regressions: list[Diff] = field(default_factory=list)
    recoveries: list[Diff] = field(default_factory=list)
    still_failing_non_context: list[Diff] = field(default_factory=list)
    still_failing_context_dependent: list[Diff] = field(default_factory=list)
    false_positives_on_chatter_v2: list[Diff] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Serialization helper for diff entries
# ---------------------------------------------------------------------------


def _instruction_to_dict(inst: StockInstruction | None) -> dict[str, object] | None:
    if inst is None:
        return None
    return {
        "instruction_type": inst.instruction_type.name,
        "ticker": inst.ticker.upper(),
        "price": inst.price,
        "price_range": list(inst.price_range) if inst.price_range else None,
        "referenced_lot_price": inst.referenced_lot_price,
        "sell_quantity": inst.sell_quantity,
        "position_size": inst.position_size,
    }


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


CORPUS_PATH_DEFAULT = Path(__file__).resolve().parent.parent.parent / "data" / "stock_origin_message.json"
GOLDEN_PATH_DEFAULT = Path(__file__).resolve().parent.parent.parent / "data" / "parser_golden.json"
REPORT_PATH_DEFAULT = Path(__file__).resolve().parent.parent.parent / "data" / "parser_validation_report.json"


def run_validation(
    *,
    corpus_path: Path | None = None,
    golden_path: Path | None = None,
) -> ValidationResult:
    """Load corpus + golden, run v1 / v2, return ValidationResult.

    Path overrides are for tests; production CLI uses the defaults.
    """
    corpus = json.loads(Path(corpus_path or CORPUS_PATH_DEFAULT).read_text())
    golden_list = json.loads(Path(golden_path or GOLDEN_PATH_DEFAULT).read_text())
    golden = {g["domID"]: g for g in golden_list}

    by_classification: Counter[str] = Counter()
    requires_context_count = 0
    single_msg_solvable_count = 0
    v1_pass_single = 0
    v1_fail_single = 0
    v2_pass_single = 0
    v2_fail_single = 0

    regressions: list[Diff] = []
    recoveries: list[Diff] = []
    still_failing_non_context: list[Diff] = []
    still_failing_context_dependent: list[Diff] = []
    false_positives_on_chatter_v2: list[Diff] = []

    for msg in corpus:
        gold = golden.get(msg["domID"])
        if gold is None:
            continue  # no golden for this message — skip silently
        cls = gold["classification"]
        by_classification[cls] += 1

        # Single-message parse only — spec decision 7
        v1_out = _v1_parse(msg["content"], message_id=msg["domID"])
        v2_out = _v2_parse(msg["content"], message_id=msg["domID"])

        if cls == "ambiguous":
            continue

        if cls == "chatter":
            if v2_out is not None:
                false_positives_on_chatter_v2.append(Diff(
                    domID=msg["domID"], content=msg["content"],
                    v1=_instruction_to_dict(v1_out),
                    v2=_instruction_to_dict(v2_out),
                    expected=None,
                ))
            continue

        # cls == "trade_signal"
        expected = gold["expected"]
        v1_pass = match(v1_out, expected)
        v2_pass = match(v2_out, expected)

        if gold["requires_context"]:
            requires_context_count += 1
            if not v2_pass:
                still_failing_context_dependent.append(Diff(
                    domID=msg["domID"], content=msg["content"],
                    v1=_instruction_to_dict(v1_out),
                    v2=_instruction_to_dict(v2_out),
                    expected=expected,
                ))
            continue

        # single-msg solvable trade_signal
        single_msg_solvable_count += 1
        if v1_pass:
            v1_pass_single += 1
        else:
            v1_fail_single += 1
        if v2_pass:
            v2_pass_single += 1
        else:
            v2_fail_single += 1

        if v1_pass and not v2_pass:
            regressions.append(Diff(
                domID=msg["domID"], content=msg["content"],
                v1=_instruction_to_dict(v1_out),
                v2=_instruction_to_dict(v2_out),
                expected=expected,
            ))
        elif not v1_pass and v2_pass:
            recoveries.append(Diff(
                domID=msg["domID"], content=msg["content"],
                v1=_instruction_to_dict(v1_out),
                v2=_instruction_to_dict(v2_out),
                expected=expected,
            ))
        elif not v1_pass and not v2_pass:
            still_failing_non_context.append(Diff(
                domID=msg["domID"], content=msg["content"],
                v1=_instruction_to_dict(v1_out),
                v2=_instruction_to_dict(v2_out),
                expected=expected,
            ))
        # else: both pass, "maintained_pass", no bucket

    # Pass criteria
    is_alias = _v2_is_alias_of_v1()
    no_regressions = len(regressions) == 0
    no_chatter_fp = len(false_positives_on_chatter_v2) == 0

    if is_alias:
        recovery_rate: float | None = None
        passed = no_regressions and no_chatter_fp
    else:
        denom = len(recoveries) + len(still_failing_non_context)
        recovery_rate = (len(recoveries) / denom) if denom > 0 else 1.0
        passed = no_regressions and no_chatter_fp and recovery_rate >= 0.20

    summary = Summary(
        total=len(corpus),
        by_classification=dict(by_classification),
        trade_signals_single_msg_solvable=single_msg_solvable_count,
        trade_signals_requires_context=requires_context_count,
        v1_pass_single_msg=v1_pass_single,
        v1_fail_single_msg=v1_fail_single,
        v2_pass_single_msg=v2_pass_single,
        v2_fail_single_msg=v2_fail_single,
        regressions=len(regressions),
        recoveries=len(recoveries),
        recovery_rate=recovery_rate,
        false_positives_on_chatter_v2=len(false_positives_on_chatter_v2),
        still_failing_context_dependent=len(still_failing_context_dependent),
        passed=passed,
    )

    return ValidationResult(
        summary=summary,
        regressions=regressions,
        recoveries=recoveries,
        still_failing_non_context=still_failing_non_context,
        still_failing_context_dependent=still_failing_context_dependent,
        false_positives_on_chatter_v2=false_positives_on_chatter_v2,
    )
```

Note: The test `test_run_validation_chatter_false_positive_fails` uses `_stock()` from the test fixture. Make sure that helper is at module scope (already added in Task 3 step 1).

- [ ] **Step 4: Run the tests to verify they pass**

```bash
cd backend && .venv/bin/python -m pytest tests/scripts/test_validate_parser.py -v
```

Expected: 20 tests PASS (15 matcher + 5 run_validation).

Run full suite:

```bash
cd backend && .venv/bin/python -m pytest -q
```

Expected: 491 passed, 2 skipped (was 486; +5).

- [ ] **Step 5: Commit**

```bash
git add backend/scripts/validate_parser.py backend/tests/scripts/test_validate_parser.py
git commit -m "$(cat <<'EOF'
feat(scripts): validate_parser.run_validation — bucket + summary

Loads corpus + golden, runs v1 (stock_parser) and v2 (parser_v2 alias),
partitions each message into:
  - chatter:                 chatter false_positive bucket if v2 returned non-None
  - ambiguous:               skipped from all metrics
  - trade_signal+req_ctx:    still_failing_context_dependent bucket (info)
  - trade_signal single-msg: regression / recovery / still_failing_non_context
                             based on (v1_pass, v2_pass) cross-product

Pass criteria evaluated at end:
  - regressions == 0
  - false_positives_on_chatter_v2 == 0
  - recovery_rate >= 0.20  [skipped when v2 is alias of v1]

ValidationResult dataclass holds the summary + per-bucket Diff lists for
JSON report serialization (Task 5).

5 new tests cover the alias exemption, chatter false-positive detection,
ambiguous skip, requires_context separate bucket, and classification counts.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: validate_parser CLI + console + JSON report

**Files:**
- Modify: `backend/scripts/validate_parser.py` (append console + JSON + main)
- Modify: `backend/tests/scripts/test_validate_parser.py` (append CLI tests)

This task wraps `run_validation()` in a CLI: console summary to stdout, JSON report to disk, exit 0/1 by `passed`.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/scripts/test_validate_parser.py`:

```python
import io
import sys

from scripts.validate_parser import (
    format_console_summary,
    write_report_json,
)


def test_format_console_summary_pass(tmp_path: Path) -> None:
    corpus = [_msg("c", "TSLL 27.2出一半")]
    golden = [_gold_signal("c", "TSLL 27.2出一半", _expected())]
    result = run_validation(
        corpus_path=_write_corpus(tmp_path, corpus),
        golden_path=_write_golden(tmp_path, golden),
    )
    output = format_console_summary(result)
    assert "OVERALL: PASS" in output
    assert "regressions:" in output


def test_format_console_summary_alias_marks_recovery_exempt(tmp_path: Path) -> None:
    corpus = [_msg("c", "TSLL 27.2出一半")]
    golden = [_gold_signal("c", "TSLL 27.2出一半", _expected())]
    result = run_validation(
        corpus_path=_write_corpus(tmp_path, corpus),
        golden_path=_write_golden(tmp_path, golden),
    )
    output = format_console_summary(result)
    assert "exempt" in output.lower() or "alias" in output.lower()


def test_write_report_json_round_trip(tmp_path: Path) -> None:
    corpus = [_msg("c", "TSLL 27.2出一半")]
    golden = [_gold_signal("c", "TSLL 27.2出一半", _expected())]
    result = run_validation(
        corpus_path=_write_corpus(tmp_path, corpus),
        golden_path=_write_golden(tmp_path, golden),
    )
    report_path = tmp_path / "report.json"
    write_report_json(result, report_path)

    data = json.loads(report_path.read_text())
    assert "summary" in data
    assert data["summary"]["passed"] is True
    assert "regressions" in data
    assert "recoveries" in data
    assert "still_failing_non_context" in data
    assert "still_failing_context_dependent" in data
    assert "false_positives_on_chatter_v2" in data
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd backend && .venv/bin/python -m pytest tests/scripts/test_validate_parser.py -v
```

Expected: FAIL — `cannot import name 'format_console_summary'`.

- [ ] **Step 3: Append console + JSON + main**

Append to `backend/scripts/validate_parser.py`:

```python
from dataclasses import asdict


def format_console_summary(result: ValidationResult) -> str:
    """Human-readable summary string suitable for terminal output."""
    s = result.summary
    lines: list[str] = []
    lines.append("==== Parser Validation Report ====")
    lines.append(f"total messages: {s.total}")
    lines.append(f"  · chatter:                {s.by_classification.get('chatter', 0)}")
    lines.append(f"  · ambiguous:              {s.by_classification.get('ambiguous', 0)}  (skipped)")
    lines.append(f"  · trade_signal:           {s.by_classification.get('trade_signal', 0)}")
    lines.append(f"      ├─ requires_context:    {s.trade_signals_requires_context}  (excluded from recovery/regression counts)")
    lines.append(f"      └─ single-msg solvable: {s.trade_signals_single_msg_solvable}")
    lines.append("")
    lines.append("v1 vs golden (single-msg solvable trade_signals only):")
    lines.append(f"  pass={s.v1_pass_single_msg}  fail={s.v1_fail_single_msg}")
    lines.append("v2 vs golden (single-msg solvable trade_signals only):")
    lines.append(f"  pass={s.v2_pass_single_msg}  fail={s.v2_fail_single_msg}")
    lines.append("")
    reg_marker = "✓" if s.regressions == 0 else "✗"
    lines.append(f"regressions:           {s.regressions}   {reg_marker} (must be 0)")
    lines.append(f"recoveries:           {s.recoveries:>2}")
    if s.recovery_rate is None:
        lines.append("recovery_rate:    EXEMPT  (parser_v2 is alias of stock_parser; constraint deferred until B2 lands)")
    else:
        rec_marker = "✓" if s.recovery_rate >= 0.20 else "✗"
        # Denominator = v1's failures on single-msg solvable trade_signals.
        # By construction, v1_fail_single_msg == recoveries + still_failing_non_context.
        denom = s.v1_fail_single_msg
        lines.append(
            f"recovery_rate:    {s.recoveries}/{denom} = {s.recovery_rate*100:.2f}%   "
            f"{rec_marker} (must be ≥ 20%)"
        )
    fp_marker = "✓" if s.false_positives_on_chatter_v2 == 0 else "✗"
    lines.append(f"false_positives_on_chatter_v2:    {s.false_positives_on_chatter_v2}   {fp_marker} (must be 0)")
    lines.append("")
    lines.append(f"still_failing_context_dependent:    {s.still_failing_context_dependent}  (informational)")
    lines.append("")
    overall = "PASS" if s.passed else "FAIL"
    lines.append(f"OVERALL: {overall}")
    return "\n".join(lines)


def write_report_json(result: ValidationResult, path: Path) -> None:
    """Serialize ValidationResult to JSON file (overwrite)."""
    data = {
        "summary": asdict(result.summary),
        "regressions": [asdict(d) for d in result.regressions],
        "recoveries": [asdict(d) for d in result.recoveries],
        "still_failing_non_context": [asdict(d) for d in result.still_failing_non_context],
        "still_failing_context_dependent": [asdict(d) for d in result.still_failing_context_dependent],
        "false_positives_on_chatter_v2": [asdict(d) for d in result.false_positives_on_chatter_v2],
    }
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2))


def main() -> int:
    """CLI entrypoint. Returns process exit code (0 = pass, 1 = fail)."""
    result = run_validation()
    print(format_console_summary(result))
    write_report_json(result, REPORT_PATH_DEFAULT)
    print(f"\nDetail report: {REPORT_PATH_DEFAULT}")
    return 0 if result.summary.passed else 1


if __name__ == "__main__":
    sys.exit(main())
```

Add `import sys` at the top of the file (where other imports live) if not already there.

- [ ] **Step 4: Run the tests to verify they pass**

```bash
cd backend && .venv/bin/python -m pytest tests/scripts/test_validate_parser.py -v
```

Expected: 23 tests PASS (15 matcher + 5 run_validation + 3 CLI).

- [ ] **Step 5: Commit**

```bash
git add backend/scripts/validate_parser.py backend/tests/scripts/test_validate_parser.py
git commit -m "$(cat <<'EOF'
feat(scripts): validate_parser CLI — console summary + JSON report + main()

format_console_summary builds the human-readable block (matches spec
9.4 layout with the alias-exemption marker when recovery_rate is None).
write_report_json serializes summary + per-bucket diff lists to disk
(spec 9.5). main() calls run_validation, prints, writes, and returns
0/1 exit code based on result.summary.passed.

3 new tests cover console output shape, alias-exempt rendering, and
JSON round-trip.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: pytest CI wrapper

**Files:**
- Create: `backend/tests/parser/test_v2_against_golden.py`

The CI wrapper test asserts `run_validation().summary.passed`. If the golden file is missing (e.g., before build_golden has been run), it skips with a clear message instead of failing.

- [ ] **Step 1: Write the test**

Create `backend/tests/parser/test_v2_against_golden.py`:

```python
"""CI gate for parser quality.

Calls the validate_parser harness against the production
data/parser_golden.json and asserts result.summary.passed. While
parser_v2 is still aliased to stock_parser the recovery_rate constraint
is exempt; once B2 lands the constraint becomes load-bearing.

Skips with a clear marker when golden hasn't been built yet (pre-B1
generation pass).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.validate_parser import (
    GOLDEN_PATH_DEFAULT,
    format_console_summary,
    run_validation,
)


def test_v2_meets_quality_bar() -> None:
    if not Path(GOLDEN_PATH_DEFAULT).exists():
        pytest.skip(
            f"golden missing at {GOLDEN_PATH_DEFAULT} — run "
            "`scripts/build_golden.py` to generate before enabling this test"
        )

    result = run_validation()
    assert result.summary.passed, (
        "parser_v2 quality bar failed:\n"
        + format_console_summary(result)
    )
```

- [ ] **Step 2: Run the test**

```bash
cd backend && .venv/bin/python -m pytest tests/parser/test_v2_against_golden.py -v
```

Expected: SKIPPED with "golden missing" message (since `data/parser_golden.json` doesn't exist yet).

Run full suite:

```bash
cd backend && .venv/bin/python -m pytest -q
```

Expected: 491 passed, 3 skipped (was 491 / 2; +1 new skip).

- [ ] **Step 3: Commit**

```bash
git add backend/tests/parser/test_v2_against_golden.py
git commit -m "$(cat <<'EOF'
test(parser): CI wrapper for parser_v2 vs golden

Skips when data/parser_golden.json hasn't been built yet (pre-generation);
once golden exists, asserts run_validation().summary.passed. Currently
also skipped via alias-exemption since parser_v2 == stock_parser; once
B2 lands the recovery_rate constraint engages and this test guards
parser quality on every commit.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: build_golden.py — prepare + merge

**Files:**
- Create: `backend/scripts/build_golden.py`
- Create: `backend/tests/scripts/test_build_golden.py`

This tool has two modes:
- `prepare` — splits `data/stock_origin_message.json` into 10 batches under `data/golden_batches/batch_NN_input.json`, prints the subagent prompt for each batch.
- `merge` — reads `data/golden_batches/batch_NN_output.json` for each batch (produced by subagents), validates every entry's schema, deduplicates by domID, sorts to corpus order, and writes the merged result to `data/parser_golden.json`.

The actual subagent dispatch happens at the controller level (the parent conversation invokes Agent calls and feeds them the batch input + the prompt). build_golden.py owns only the deterministic pieces.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/scripts/test_build_golden.py`:

```python
"""Tests for scripts/build_golden.py — prepare + merge modes."""

import json
from pathlib import Path

import pytest

from scripts.build_golden import (
    build_subagent_prompt,
    merge_batches,
    prepare_batches,
)


def _msg(domid: str, content: str) -> dict:
    return {"domID": domid, "content": content,
            "timestamp": "2025-10-07 00:00:00.000",
            "refer": None, "position": "single", "history": []}


def test_prepare_batches_splits_corpus(tmp_path: Path) -> None:
    corpus = [_msg(f"m{i}", f"content {i}") for i in range(10)]
    corpus_path = tmp_path / "corpus.json"
    corpus_path.write_text(json.dumps(corpus, ensure_ascii=False))
    out_dir = tmp_path / "batches"

    paths = prepare_batches(corpus_path=corpus_path, out_dir=out_dir, batch_size=4)

    assert len(paths) == 3  # 10 / 4 = 3 batches (4 + 4 + 2)
    batch1 = json.loads(paths[0].read_text())
    assert len(batch1) == 4
    assert batch1[0]["domID"] == "m0"
    batch3 = json.loads(paths[2].read_text())
    assert len(batch3) == 2
    assert batch3[0]["domID"] == "m8"


def test_build_subagent_prompt_embeds_few_shot_and_input() -> None:
    batch = [_msg("m1", "TSLL 27.2出一半")]
    prompt = build_subagent_prompt(batch)
    assert "TSLL 27.2出一半" in prompt
    # few-shot embedded
    assert "few_shot_chatter_greeting" in prompt or "大家好" in prompt
    # rules embedded
    assert "trade_signal" in prompt
    assert "ambiguous" in prompt


def test_merge_batches_validates_and_sorts_to_corpus_order(tmp_path: Path) -> None:
    corpus = [_msg("m0", "x0"), _msg("m1", "x1"), _msg("m2", "x2")]
    corpus_path = tmp_path / "corpus.json"
    corpus_path.write_text(json.dumps(corpus, ensure_ascii=False))

    # Two batch outputs, NOT in corpus order
    batch_dir = tmp_path / "batches"
    batch_dir.mkdir()
    batch1 = [
        {"domID": "m2", "content": "x2", "classification": "chatter",
         "expected": None, "requires_context": False, "notes": ""},
    ]
    batch2 = [
        {"domID": "m0", "content": "x0", "classification": "chatter",
         "expected": None, "requires_context": False, "notes": ""},
        {"domID": "m1", "content": "x1", "classification": "chatter",
         "expected": None, "requires_context": False, "notes": ""},
    ]
    (batch_dir / "batch_00_output.json").write_text(json.dumps(batch1, ensure_ascii=False))
    (batch_dir / "batch_01_output.json").write_text(json.dumps(batch2, ensure_ascii=False))

    out_path = tmp_path / "golden.json"
    merge_batches(batch_dir=batch_dir, corpus_path=corpus_path, out_path=out_path)

    merged = json.loads(out_path.read_text())
    assert [g["domID"] for g in merged] == ["m0", "m1", "m2"]


def test_merge_batches_rejects_invalid_entry(tmp_path: Path) -> None:
    corpus = [_msg("m0", "x0")]
    corpus_path = tmp_path / "corpus.json"
    corpus_path.write_text(json.dumps(corpus, ensure_ascii=False))

    batch_dir = tmp_path / "batches"
    batch_dir.mkdir()
    bad_batch = [
        {"domID": "m0", "content": "x0", "classification": "garbage",
         "expected": None, "requires_context": False, "notes": ""},
    ]
    (batch_dir / "batch_00_output.json").write_text(json.dumps(bad_batch, ensure_ascii=False))

    out_path = tmp_path / "golden.json"
    with pytest.raises(ValueError, match="classification"):
        merge_batches(batch_dir=batch_dir, corpus_path=corpus_path, out_path=out_path)


def test_merge_batches_rejects_missing_domid(tmp_path: Path) -> None:
    """If a corpus message has no entry in any batch, merge fails loudly."""
    corpus = [_msg("m0", "x0"), _msg("m1", "x1")]
    corpus_path = tmp_path / "corpus.json"
    corpus_path.write_text(json.dumps(corpus, ensure_ascii=False))

    batch_dir = tmp_path / "batches"
    batch_dir.mkdir()
    incomplete = [
        {"domID": "m0", "content": "x0", "classification": "chatter",
         "expected": None, "requires_context": False, "notes": ""},
        # m1 missing
    ]
    (batch_dir / "batch_00_output.json").write_text(json.dumps(incomplete, ensure_ascii=False))

    out_path = tmp_path / "golden.json"
    with pytest.raises(ValueError, match="m1"):
        merge_batches(batch_dir=batch_dir, corpus_path=corpus_path, out_path=out_path)


def test_merge_batches_rejects_duplicate_domid(tmp_path: Path) -> None:
    """Duplicate entries (same domID across batches) → fail loudly."""
    corpus = [_msg("m0", "x0")]
    corpus_path = tmp_path / "corpus.json"
    corpus_path.write_text(json.dumps(corpus, ensure_ascii=False))

    batch_dir = tmp_path / "batches"
    batch_dir.mkdir()
    dup1 = [{"domID": "m0", "content": "x0", "classification": "chatter",
             "expected": None, "requires_context": False, "notes": ""}]
    dup2 = [{"domID": "m0", "content": "x0", "classification": "chatter",
             "expected": None, "requires_context": False, "notes": ""}]
    (batch_dir / "batch_00_output.json").write_text(json.dumps(dup1, ensure_ascii=False))
    (batch_dir / "batch_01_output.json").write_text(json.dumps(dup2, ensure_ascii=False))

    out_path = tmp_path / "golden.json"
    with pytest.raises(ValueError, match="duplicate"):
        merge_batches(batch_dir=batch_dir, corpus_path=corpus_path, out_path=out_path)
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd backend && .venv/bin/python -m pytest tests/scripts/test_build_golden.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.build_golden'`.

- [ ] **Step 3: Implement build_golden.py**

Create `backend/scripts/build_golden.py`:

```python
"""build_golden — generate data/parser_golden.json from corpus + subagent batches.

Two-phase tool used at the orchestration layer:

  1. `prepare`: split data/stock_origin_message.json into N batches under
     data/golden_batches/batch_NN_input.json. Print the subagent prompt for
     each batch on stdout. The controller (parent conversation) dispatches
     subagents one per batch with that prompt + the batch's input messages,
     and saves each subagent's JSON response to batch_NN_output.json.

  2. `merge`: read all batch_NN_output.json files, validate each entry via
     golden_lib.validate_golden_entry, ensure no duplicate domIDs and full
     corpus coverage, sort to corpus order, write data/parser_golden.json.

Why split into prepare + merge: actual subagent dispatch is a controller
action (the orchestrating LLM in this repo's superpowers stack), not
something this Python script can perform on its own. We keep build_golden
focused on the deterministic, testable pieces (split + validate + merge)
and delegate the LLM calls to the conversation layer.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from scripts.golden_lib import (
    BUILD_PROMPT_TEMPLATE,
    FEW_SHOT_EXAMPLES,
    validate_golden_entry,
)


CORPUS_PATH_DEFAULT = Path(__file__).resolve().parent.parent.parent / "data" / "stock_origin_message.json"
BATCH_DIR_DEFAULT = Path(__file__).resolve().parent.parent.parent / "data" / "golden_batches"
GOLDEN_PATH_DEFAULT = Path(__file__).resolve().parent.parent.parent / "data" / "parser_golden.json"

DEFAULT_BATCH_SIZE = 200


# ---------------------------------------------------------------------------
# prepare — split corpus into batches
# ---------------------------------------------------------------------------


def prepare_batches(
    *,
    corpus_path: Path = CORPUS_PATH_DEFAULT,
    out_dir: Path = BATCH_DIR_DEFAULT,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> list[Path]:
    """Split corpus into batches, write each to out_dir/batch_NN_input.json.

    Returns the list of written paths in batch index order.
    """
    corpus = json.loads(corpus_path.read_text())
    out_dir.mkdir(parents=True, exist_ok=True)

    written: list[Path] = []
    for i in range(0, len(corpus), batch_size):
        batch = corpus[i : i + batch_size]
        idx = len(written)
        path = out_dir / f"batch_{idx:02d}_input.json"
        path.write_text(json.dumps(batch, ensure_ascii=False, indent=2))
        written.append(path)
    return written


def build_subagent_prompt(batch: list[dict]) -> str:
    """Construct the full subagent prompt for one batch."""
    return BUILD_PROMPT_TEMPLATE.format(
        FEW_SHOT_JSON=json.dumps(FEW_SHOT_EXAMPLES, ensure_ascii=False, indent=2),
        INPUT_JSON=json.dumps(batch, ensure_ascii=False, indent=2),
    )


# ---------------------------------------------------------------------------
# merge — combine batch outputs into parser_golden.json
# ---------------------------------------------------------------------------


def merge_batches(
    *,
    batch_dir: Path = BATCH_DIR_DEFAULT,
    corpus_path: Path = CORPUS_PATH_DEFAULT,
    out_path: Path = GOLDEN_PATH_DEFAULT,
) -> None:
    """Validate + merge all batch_NN_output.json into out_path.

    Raises ValueError if:
      - any entry fails schema validation
      - any domID appears in more than one batch
      - the corpus has a domID not covered by any batch
    """
    corpus = json.loads(corpus_path.read_text())
    corpus_domids = [m["domID"] for m in corpus]
    corpus_domid_set = set(corpus_domids)

    seen: dict[str, dict] = {}
    output_files = sorted(batch_dir.glob("batch_*_output.json"))
    for path in output_files:
        entries = json.loads(path.read_text())
        if not isinstance(entries, list):
            raise ValueError(f"{path} is not a JSON array")
        for entry in entries:
            errors = validate_golden_entry(entry)
            if errors:
                raise ValueError(f"{path} entry domID={entry.get('domID')!r}: {errors}")
            domid = entry["domID"]
            if domid in seen:
                raise ValueError(f"duplicate domID across batches: {domid}")
            if domid not in corpus_domid_set:
                raise ValueError(f"{path} entry domID={domid} not in corpus")
            seen[domid] = entry

    missing = corpus_domid_set - seen.keys()
    if missing:
        raise ValueError(f"corpus domIDs missing from batch outputs: {sorted(missing)[:10]}...")

    # Sort to corpus order
    merged = [seen[domid] for domid in corpus_domids]
    out_path.write_text(json.dumps(merged, ensure_ascii=False, indent=2))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _cmd_prepare(args: argparse.Namespace) -> int:
    paths = prepare_batches(
        corpus_path=Path(args.corpus) if args.corpus else CORPUS_PATH_DEFAULT,
        out_dir=Path(args.out_dir) if args.out_dir else BATCH_DIR_DEFAULT,
        batch_size=args.batch_size,
    )
    print(f"Wrote {len(paths)} batches:")
    for p in paths:
        n = len(json.loads(p.read_text()))
        print(f"  {p}  ({n} messages)")
    print()
    print("To run: dispatch one subagent per batch_NN_input.json with the")
    print("prompt printed by --print-prompt, save responses to batch_NN_output.json")
    print("in the same directory, then run `build_golden.py merge`.")
    return 0


def _cmd_print_prompt(args: argparse.Namespace) -> int:
    batch_path = Path(args.batch)
    batch = json.loads(batch_path.read_text())
    print(build_subagent_prompt(batch))
    return 0


def _cmd_merge(args: argparse.Namespace) -> int:
    merge_batches(
        batch_dir=Path(args.batch_dir) if args.batch_dir else BATCH_DIR_DEFAULT,
        corpus_path=Path(args.corpus) if args.corpus else CORPUS_PATH_DEFAULT,
        out_path=Path(args.out) if args.out else GOLDEN_PATH_DEFAULT,
    )
    print(f"Merged → {args.out or GOLDEN_PATH_DEFAULT}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Build parser_golden.json from corpus + subagent batches.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_prepare = sub.add_parser("prepare", help="Split corpus into batches")
    p_prepare.add_argument("--corpus", default=None)
    p_prepare.add_argument("--out-dir", default=None)
    p_prepare.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    p_prepare.set_defaults(func=_cmd_prepare)

    p_prompt = sub.add_parser("print-prompt", help="Print subagent prompt for one batch input")
    p_prompt.add_argument("batch", help="Path to batch_NN_input.json")
    p_prompt.set_defaults(func=_cmd_print_prompt)

    p_merge = sub.add_parser("merge", help="Merge batch outputs into parser_golden.json")
    p_merge.add_argument("--batch-dir", default=None)
    p_merge.add_argument("--corpus", default=None)
    p_merge.add_argument("--out", default=None)
    p_merge.set_defaults(func=_cmd_merge)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    import sys
    sys.exit(main())
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
cd backend && .venv/bin/python -m pytest tests/scripts/test_build_golden.py -v
```

Expected: 6 tests PASS.

Run full suite:

```bash
cd backend && .venv/bin/python -m pytest -q
```

Expected: 497 passed, 3 skipped (was 491 / 3; +6 new).

- [ ] **Step 5: Commit**

```bash
git add backend/scripts/build_golden.py backend/tests/scripts/test_build_golden.py
git commit -m "$(cat <<'EOF'
feat(scripts): build_golden — prepare/merge for parser_golden.json

Two-phase tool. prepare splits data/stock_origin_message.json into
N batches under data/golden_batches/batch_NN_input.json. print-prompt
emits the full subagent prompt for one batch (few-shot examples +
classification rules + batch JSON). merge reads all batch_NN_output.json
files (produced by subagents at the orchestration layer), validates
every entry via golden_lib.validate_golden_entry, deduplicates by
domID, ensures corpus coverage, sorts to corpus order, and writes
data/parser_golden.json.

Why split: subagent dispatch happens in the conversation layer
(controller LLM), not from inside a Python script. build_golden owns
only the deterministic, testable pieces.

6 unit tests cover splitting, prompt embedding, ordering, and the
three rejection paths (invalid entry / missing domID / duplicate).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Final verification

- [ ] **Step 1: Run the full backend test suite**

```bash
cd backend && .venv/bin/python -m pytest -q
```

Expected: 497 passed, 3 skipped (the 2 pre-existing + 1 new for the golden-not-yet-built CI test).

- [ ] **Step 2: Verify CLI runs cleanly**

```bash
cd backend && .venv/bin/python -m scripts.validate_parser
```

Expected: This will fail with FileNotFoundError on `data/parser_golden.json` — that's expected pre-build-golden. Confirms the CLI wires up correctly.

- [ ] **Step 3: Inspect the diff**

```bash
git log --oneline 6575cad..HEAD
git diff 6575cad..HEAD --stat
```

Expected: 7 commits, each task one commit.

---

## Out of scope (intentionally — see spec §3 and §13)

- **B2: parser_v2 implementation** — `app/parser_v2/__init__.py` stays as alias until B2 lands
- **B3: PageSettings parser_version + dispatcher** — separate sub-project
- **stop-loss / take-profit / option validation** — v2 scope is BUY/SELL stock only
- **Running build_golden.py to actually generate `data/parser_golden.json`** — that's an execution activity, not implementation. After this plan ships, the controller dispatches subagents to the prepared batches, captures their JSON outputs, runs `merge`, audits 50 random entries, and commits the final golden file as a separate work session.
