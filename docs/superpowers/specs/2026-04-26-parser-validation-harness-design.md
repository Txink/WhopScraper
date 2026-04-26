# 设计文档：Parser 验证 harness（B1）

**日期**：2026-04-26
**分支**：`refactor-v2`
**作者**：txink + Claude

## 1. 背景与动机

`backend/app/parser/stock_parser.py` 的正股解析器是手写正则规则集合（1700+ 行），过去靠少量 unit test 验收。最近 4 月 23 日批量 PARSE_ERROR 暴露了规则覆盖不足；Item 2A 加了 4 条 fallback 正则把 6 条已知失败案例救回，但**没有手段衡量"补丁是否引入回归"或"覆盖率改善多少"**——`tests/parser/test_stock_parser.py` 只盯 9 条精挑细选的样例。

接下来要做 parser_v2（独立 token-based slot-filling 解析器，B2），更需要一个**长期、可复用、可量化**的验证 harness：

- 1899 条历史 stock 消息（`data/stock_origin_message.json`）是天然的语料库
- 每条消息标一个"应当解析成什么"的 ground truth → 形成 golden 数据集
- v1 / v2 / 未来任何 parser 改动都跑这个 golden，输出 PASS/FAIL 报告

本设计是 B1（验证 harness 子项目），不实现 parser_v2 本身（B2）也不接生产 dispatch（B3）。

## 2. 目标

1. 产出 `data/parser_golden.json` —— 1899 条手工 curate 的 ground truth
2. 产出 `scripts/validate_parser.py` —— 跑 v1 / v2，diff golden，输出 console summary + JSON 报告
3. 产出 `scripts/build_golden.py` —— 一次性生成 golden 的 subagent 批处理工具（可重跑用于 corpus 扩充）
4. CI 集成：pytest 包一层调 `validate_parser`，断言通过；初始状态豁免（v2 未实现时也能绿）
5. v2 通过标准明确量化：`regressions == 0` AND `recovery_rate ≥ 20%` AND `false_positives_on_chatter_v2 == 0`

## 3. 非目标

- **不实现 parser_v2**（B2 子项目）
- **不接生产 dispatch / PageSettings 切换**（B3 子项目）
- **不验证 stop-loss / take-profit / option**（v2 范围只覆盖 stock BUY / SELL）
- **不模拟 context_resolver / DB**：harness 只喂 `content` 给 parser，上下文依赖的消息单独统计
- **不在 harness 里跑全管线 service.py**：只比较单条 `stock_parser.parse(content)` 输出

## 4. 决策汇总

设计阶段确认的 7 个核心决策：

| # | 决策点 | 选择 | 理由 |
|---|---|---|---|
| 1 | golden 起源 | β：1899 条全部手工 curate from scratch | v1 输出有错也不当真值，要真正的 ground truth |
| 2 | golden schema | B：rich（content + classification + expected + notes + requires_context） | 自包含可读，未来回看不用反查原始消息 |
| 3 | 生成方式 | B：并行 subagent 批处理（5 并发，10 batch，每 batch 200 条）+ 抽样审计 50 条 | 不堵塞主对话，可重跑 |
| 4 | 通过判定 | X：严格三约束（regression=0 + recovery≥20% + chatter false_positive=0） | 三个数线性可解释，最易 CI 化 |
| 5 | 分类边界 | 三档 chatter / trade_signal / ambiguous（含 stop-loss、条件、多指令） | ambiguous 跳过 diff，避免永久 regression |
| 6 | 报告格式 | A：console summary + 独立 JSON 报告（CI 跑） | 人机两用 |
| 7 | 上下文处理 | golden curate 时人看完整 history；harness 只喂 content 给 parser；context 依赖标 `requires_context: true` 单独统计 | 衡量 v2 单条改进的纯粹度 |

## 5. 架构 & 文件布局

```
data/
├── stock_origin_message.json      # 现有 1899 条原始消息（输入；不动）
├── parser_golden.json             # 新增：1899 条 hand-curated ground truth（B1 产物，git 跟踪）
└── parser_validation_report.json  # validate_parser.py 产物（gitignore，每次跑覆盖）

backend/app/parser_v2/
└── __init__.py                    # 占位：B2 落地前直接 alias 到 stock_parser.parse
                                   # （harness 通过 `is` 检测身份判断 v2 是否未实现）

backend/scripts/
├── __init__.py                    # 空文件，使 scripts 成为可 import 包（pytest 用）
├── build_golden.py                # 一次性：subagent 批处理生成 parser_golden.json
└── validate_parser.py             # 主 harness：消费 stock_origin_message + parser_golden,
                                   # 跑 v1 / v2，diff，输出 console summary + JSON 报告

backend/tests/parser/
└── test_v2_against_golden.py      # CI wrapper：调 validate_parser.run_validation(),
                                   # 断言 result.passed == True
```

**`.gitignore` 加一条**：`data/parser_validation_report.json`（每次跑覆盖，不进 git）。

**数据流**：

```
                            ┌──> v1 (stock_parser.parse) ──┐
stock_origin_message.json ──┤                              ├──> diff (per-message)
                            └──> v2 (stock_parser.parse)*  ──┘     │
                                  *初始与 v1 相同，B2 完成后切到     │
                                   stock_parser_v2.parse           │
                                                                    ▼
parser_golden.json ─────────────────────────────────────────> validate_parser.py
                                                                    │
                                                                    ├─> stdout summary
                                                                    └─> parser_validation_report.json
```

**两个工具的边界**：

- `build_golden.py`：一次性。可重跑（corpus 扩充时增量更新），不在 CI 跑。
- `validate_parser.py`：频繁跑（CI、本地开发、parser 改动后）。读取 `parser_golden.json`，所以必须先有 golden。

## 6. golden 文件格式

`data/parser_golden.json` 是一个 JSON 数组，1899 条 entry。

### 6.1 entry 结构

```json
{
  "domID": "post_1CTrFjrJVYEpGejKxFqmuU",
  "content": "大家好",
  "classification": "chatter",
  "expected": null,
  "requires_context": false,
  "notes": "纯打招呼"
}
```

```json
{
  "domID": "post_1CaJw9e9yEBTGL1cdmsiDV",
  "content": "23.32出了bmnr21.5剩下一半",
  "classification": "trade_signal",
  "expected": {
    "instruction_type": "SELL",
    "ticker": "BMNR",
    "price": 23.32,
    "price_range": null,
    "referenced_lot_price": 21.5,
    "sell_quantity": "剩下一半",
    "position_size": null
  },
  "requires_context": false,
  "notes": ""
}
```

```json
{
  "domID": "post_xxx",
  "content": "15.2 全出",
  "classification": "trade_signal",
  "expected": {
    "instruction_type": "SELL",
    "ticker": "TSLL",
    "price": 15.2,
    "price_range": null,
    "referenced_lot_price": null,
    "sell_quantity": "全部",
    "position_size": null
  },
  "requires_context": true,
  "notes": "ticker 来自 history 上一条 'tsll 14.6 买入'"
}
```

```json
{
  "domID": "post_xxx",
  "content": "hims剩下一半设置下跌破54.4都出",
  "classification": "ambiguous",
  "expected": null,
  "requires_context": false,
  "notes": "止损条件，v2 范围外"
}
```

### 6.2 字段约定

| 字段 | 类型 | 约定 |
|---|---|---|
| `domID` | string | 与 stock_origin_message.json 的 `domID` 一一对应 |
| `content` | string | 完整复制 stock_origin_message.json 的 `content` |
| `classification` | `"chatter" \| "trade_signal" \| "ambiguous"` | 必填 |
| `expected` | object \| null | trade_signal 必为 object（含 7 字段，缺省填 null）；chatter / ambiguous 必为 null |
| `requires_context` | bool | 仅 trade_signal 有意义；当 ticker / price 来自 history 或 refer 时为 true，否则 false。chatter / ambiguous 一律 false |
| `notes` | string | 自由文本。chatter 简标原因；ambiguous 必填说明；trade_signal 一般留空 |

### 6.3 expected object 七字段

| 字段 | 类型 | 比对方式 |
|---|---|---|
| `instruction_type` | `"BUY" \| "SELL"` | 严格相等 |
| `ticker` | string (uppercase) | 严格相等 |
| `price` | float \| null | ±0.001 容差 |
| `price_range` | `[low, high] \| null` | 两端各 ±0.001 容差 |
| `referenced_lot_price` | float \| null | ±0.001 容差 |
| `sell_quantity` | string \| null | 严格相等 |
| `position_size` | string \| null | 严格相等 |

**忽略字段**（既不进 expected 也不进 diff）：`parser_notes / context_source / symbol / quantity / raw_message / message_id / stop_loss_price / take_profit_price`。

## 7. 分类规则

### 7.1 trade_signal

同时满足三条：

1. 明确动作动词：`买/卖/出/开/加/减/吸/兑现/建仓/平仓` 等
2. 引用 ticker：大写字母 2-5 位 OR 中文别名能映射到 ticker（含通过 history / refer 间接得到，标 `requires_context: true`）
3. 至少有一个具体价格

**例**：`TSLL 27.2出一半`、`23.32出了bmnr21.5剩下一半`、`12.32加了12.87卖出的tsll那部分`

### 7.2 chatter

不满足上述任一条：纯打招呼、纯观察、提问、emoji。

**例**：`大家好`、`今天看起来要回调`、`👍`

### 7.3 ambiguous

边界场景，diff 工具完全跳过：

1. **条件 / 假设性指令**："如果跌破 X 就出"、"看情况减仓"、"X 下方都出"
2. **止损 / 止盈**：`hims 剩下一半设置下跌破 54.4 都出`（v2 范围外）
3. **观察夹带半提示**：`Tsll 剩下仓位要注意发布会...`（有 ticker 但无明确动作动词）
4. **多指令并列**：`21.7 也减仓点 tsll 剩下原始持仓的一半博弈下发布会 发布会边拉升边出 跌破 21.3 都出`（即时指令 + 计划 + 止损混合）

## 8. golden 生成工作流（`scripts/build_golden.py`）

### 8.1 步骤

1. 读 `data/stock_origin_message.json`（1899 条）
2. 切成 10 batch，每 batch 200 条
3. 起 5 个 subagent **并行**跑前 5 batch
4. 等回来 → 起后 5 batch
5. 合并 JSON → 写入 `data/parser_golden.json`
6. **审计阶段**：随机抽 50 条，主对话里逐条对比 expected，发现错误直接 patch golden 文件（人工 + AI 协作）
7. 审计通过后 commit `data/parser_golden.json`

### 8.2 subagent prompt 模板

```
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

### Few-shot 示例（10 条覆盖典型边界）

```json
[
  {"content": "大家好", "classification": "chatter", "expected": null,
   "requires_context": false, "notes": "纯打招呼"},

  {"content": "今天大盘看起来要回调", "classification": "chatter", "expected": null,
   "requires_context": false, "notes": "市场观察，无 ticker / 无动作"},

  {"content": "TSLL 27.2出一半", "classification": "trade_signal",
   "expected": {"instruction_type": "SELL", "ticker": "TSLL", "price": 27.2,
                "price_range": null, "referenced_lot_price": null,
                "sell_quantity": "1/2", "position_size": null},
   "requires_context": false, "notes": ""},

  {"content": "12.87减一半12.42的tsll", "classification": "trade_signal",
   "expected": {"instruction_type": "SELL", "ticker": "TSLL", "price": 12.87,
                "price_range": null, "referenced_lot_price": 12.42,
                "sell_quantity": "1/2", "position_size": null},
   "requires_context": false, "notes": ""},

  {"content": "tsll 11.5 附近建仓常规仓的一半", "classification": "trade_signal",
   "expected": {"instruction_type": "BUY", "ticker": "TSLL", "price": 11.5,
                "price_range": null, "referenced_lot_price": null,
                "sell_quantity": null, "position_size": "常规仓的一半"},
   "requires_context": false, "notes": ""},

  {"content": "TSLL 27-27.5 区间出一半", "classification": "trade_signal",
   "expected": {"instruction_type": "SELL", "ticker": "TSLL", "price": null,
                "price_range": [27.0, 27.5], "referenced_lot_price": null,
                "sell_quantity": "1/2", "position_size": null},
   "requires_context": false, "notes": ""},

  // history 上一条是 "tsll 14.6 买入"
  {"content": "15.2 全出", "classification": "trade_signal",
   "expected": {"instruction_type": "SELL", "ticker": "TSLL", "price": 15.2,
                "price_range": null, "referenced_lot_price": null,
                "sell_quantity": "全部", "position_size": null},
   "requires_context": true, "notes": "ticker 来自 history"},

  {"content": "hims剩下一半设置下跌破54.4都出", "classification": "ambiguous",
   "expected": null, "requires_context": false, "notes": "止损条件，v2 范围外"},

  {"content": "TSLL 跌破 11 都出", "classification": "ambiguous",
   "expected": null, "requires_context": false, "notes": "条件性触发，非即时指令"},

  {"content": "21.7 也减仓点 tsll 剩下原始持仓的一半博弈下发布会 发布会边拉升边出 跌破 21.3 都出",
   "classification": "ambiguous", "expected": null, "requires_context": false,
   "notes": "首句即时指令 + 计划 + 止损条件混合，整体不可机器化"}
]
```

### 输入

[200 条 raw message 数组：{domID, content, history, refer, position}]

### 输出

纯 JSON 数组，N 条 entry，顺序与输入一致。每条含 6 字段：
  domID, content, classification, expected, requires_context, notes

不要其他文字。
```

### 8.3 审计策略

- 从 1899 中随机抽 50 条
- 跨 batch 边界检查（避免不同 subagent 口径漂移）
- 人工 review，发现错误直接修 `parser_golden.json`
- 抽样错误率 > 5% → 整个 batch 重跑

## 9. validate_parser.py 设计

### 9.1 输入 / 输出

**输入**：
- `data/stock_origin_message.json`
- `data/parser_golden.json`

**输出**：
- stdout console summary
- `data/parser_validation_report.json`

**返回值**（CLI 退出码 + Python API）：
- exit 0 / `result.passed = True`：所有约束满足
- exit 1 / `result.passed = False`：任一约束违反

### 9.2 算法

```python
def run_validation() -> ValidationResult:
    messages = load_corpus()         # 1899 条
    golden   = load_golden()         # 1899 条 keyed by domID

    # 单独统计的桶
    by_classification = Counter()
    regressions: list[Diff] = []
    recoveries: list[Diff] = []
    still_failing_non_context: list[Diff] = []
    still_failing_context_dependent: list[Diff] = []
    false_positives_on_chatter_v2: list[Diff] = []

    for msg in messages:
        gold = golden[msg["domID"]]
        by_classification[gold["classification"]] += 1

        # v2 输入只是 content（决策 7）
        v1_out = stock_parser.parse(msg["content"], message_id=msg["domID"])
        v2_out = stock_parser_v2.parse(msg["content"], message_id=msg["domID"])
        # 注：v2 模块在 B2 完成前是 stock_parser 的 alias，所以 v1_out == v2_out

        if gold["classification"] == "ambiguous":
            continue

        if gold["classification"] == "chatter":
            if v2_out is not None:
                false_positives_on_chatter_v2.append(diff_entry(msg, v1_out, v2_out, gold))
            continue

        # trade_signal 桶
        v1_pass = matches(v1_out, gold["expected"])
        v2_pass = matches(v2_out, gold["expected"])

        if gold["requires_context"]:
            if not v2_pass:
                still_failing_context_dependent.append(diff_entry(...))
            continue

        # single-msg solvable trade_signal
        if v1_pass and not v2_pass:
            regressions.append(diff_entry(...))
        elif not v1_pass and v2_pass:
            recoveries.append(diff_entry(...))
        elif not v1_pass and not v2_pass:
            still_failing_non_context.append(diff_entry(...))
        # else (v1_pass and v2_pass): maintained, 不入任何桶

    return compute_summary(...)
```

### 9.3 通过判定

`passed = True` 必须三条全满足：

```python
v2_is_alias_of_v1 = (stock_parser_v2.parse is stock_parser.parse)

if v2_is_alias_of_v1:
    # v2 还没实现：跳过 recovery 约束（不可能产生 recovery，但也不算失败）
    passed = (
        len(regressions) == 0
        and len(false_positives_on_chatter_v2) == 0
    )
else:
    # v2 实现后：三条全要满足
    denom = len(recoveries) + len(still_failing_non_context)
    recovery_rate = (len(recoveries) / denom) if denom > 0 else 1.0
    passed = (
        len(regressions) == 0
        and recovery_rate >= 0.20
        and len(false_positives_on_chatter_v2) == 0
    )
```

**关键豁免逻辑**：v2 还没实现时（B2 没动），`stock_parser_v2.parse` 直接 alias 到 `stock_parser.parse`，所以两者**函数对象身份相同**。harness 检测到 `is` 相等即跳过 recovery 约束。等 B2 实现独立 `stock_parser_v2` 模块，`is` 不再成立，自动启用 recovery_rate 检查。

**B2 落地前的 alias 实现**：在 `app/parser_v2/__init__.py` 暂时写 `from app.parser.stock_parser import parse`（直接复用），harness 测到身份相同就豁免。B2 真正实现 token-based parser 后改写这个文件，alias 自动失效。

### 9.4 console 输出格式

```
==== Parser Validation Report ====
total messages: 1899
  · chatter:                706
  · ambiguous:              193  (skipped)
  · trade_signal:           1000
      ├─ requires_context:    50  (excluded from recovery/regression counts)
      └─ single-msg solvable: 950

v1 vs golden (single-msg solvable trade_signals only):
  pass=856  fail=94
v2 vs golden (single-msg solvable trade_signals only):
  pass=918  fail=32

regressions:           0   ✓ (must be 0)
recoveries:           62   ✓
recovery_rate:    62/94 = 65.96%   ✓ (must be ≥ 20%)
false_positives_on_chatter_v2:    0   ✓ (must be 0)

still_failing_context_dependent:    50  (informational)

OVERALL: PASS

Detail report: data/parser_validation_report.json
```

数字仅为示意。

### 9.5 JSON 报告结构

```json
{
  "summary": {
    "total": 1899,
    "by_classification": {"chatter": 706, "ambiguous": 193, "trade_signal": 1000},
    "trade_signals": {"single_msg_solvable": 950, "requires_context": 50},
    "v1_vs_golden_single_msg": {"pass": 856, "fail": 94},
    "v2_vs_golden_single_msg": {"pass": 918, "fail": 32},
    "regressions": 0,
    "recoveries": 62,
    "recovery_rate": 0.6596,
    "false_positives_on_chatter_v2": 0,
    "still_failing_context_dependent": 50,
    "passed": true
  },
  "regressions":                      [{"domID": "...", "content": "...", "v1": {...}, "v2": {...}, "expected": {...}}],
  "recoveries":                       [...],
  "still_failing_non_context":        [...],
  "still_failing_context_dependent":  [...],
  "false_positives_on_chatter_v2":    [...]
}
```

每个 `Diff` entry 含：`domID`, `content`, `v1`（StockInstruction 字典 \| null）, `v2`（同）, `expected`（同 golden）。

### 9.6 match 实现

```python
def matches(out: StockInstruction | None, expected: dict | None) -> bool:
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

def _float_eq(a: float | None, b: float | None, tol: float = 0.001) -> bool:
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    return abs(a - b) <= tol
```

## 10. CI 集成

`backend/tests/parser/test_v2_against_golden.py`：

```python
"""
CI gate for parser quality. Calls the validate_parser harness and asserts
the v2 quality bar is met. Initially v2 == v1 so the harness's exemption
clause for empty denominator keeps this green; once parser_v2 lands, the
recovery_rate constraint becomes load-bearing.
"""

import pytest
from scripts.validate_parser import run_validation


def test_v2_meets_quality_bar() -> None:
    result = run_validation()
    assert result.passed, (
        f"Parser v2 quality bar failed:\n"
        f"  regressions: {len(result.regressions)} (must be 0)\n"
        f"  recoveries: {len(result.recoveries)}\n"
        f"  recovery_rate: {result.recovery_rate:.2%} (must be >= 20%)\n"
        f"  false_positives_on_chatter_v2: {len(result.false_positives_on_chatter_v2)} (must be 0)\n"
        f"See data/parser_validation_report.json for details."
    )
```

`backend/scripts/__init__.py`（空文件）必须存在以便 pytest 可以从 `scripts.validate_parser` 导入。`backend/app/parser_v2/__init__.py` 在 B1 落地时只写 `from app.parser.stock_parser import parse`（alias），harness 据此触发豁免。

## 11. 测试策略（B1 自身）

B1 工具的内部测试：

| 测试文件 | 覆盖 |
|---|---|
| `tests/scripts/test_validate_parser.py` | match 函数（float 容差、None 处理、字段比对）；compute_summary 正确分桶；豁免分子分母=0 时 PASS |
| `tests/scripts/test_build_golden.py` | golden entry schema 校验（用合成的少量数据，不真起 subagent）；输出文件格式合法 |

## 12. 兼容性 & 滚动落地

- **golden 数据是 git 跟踪的资产**：所有人共享一份 ground truth；后续 corpus 扩充走 incremental update（`build_golden.py` 接受 "只跑新 domID" 选项）
- **harness 不影响生产**：纯验证工具；不接事件总线、不改 service.py 的 dispatch
- **B2 / B3 都在此 harness 下迭代**：B2 实现 stock_parser_v2，先把它接进 validate_parser.py（替换 v2 alias），开始能跑出真实 recovery 数。B3 再把生产开关接上。

## 13. 后续工作（不在本 spec 内）

- **B2**：parser_v2 token-based 实现（独立 `app/parser_v2/` 子包）
- **B3**：`PageSettings.parser_version: "v1" | "v2"` + service.py dispatcher 切换 + 前端 page settings 表单加切换控件
- **harness 扩展**：未来加 option 验证、stop-loss / take-profit 验证（独立 golden 文件）
- **corpus 扩充**：`build_golden.py` 加 `--only-new` 模式，按 domID 增量补 golden
