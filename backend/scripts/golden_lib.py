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
# Placeholders: {FEW_SHOT_JSON}, {INPUT_JSON}
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
