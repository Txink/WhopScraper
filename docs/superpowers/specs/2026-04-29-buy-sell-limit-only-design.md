# 买卖统一使用 LIMIT 单（对称"占便宜"规则）

## 背景

当前 `backend/app/broker/trader.py` 的 `_decide_order_type_and_context` 在现价对自己**更有利**时选择市价单（MO）：

- BUY: `last_done < signal` → MARKET（押注立即成交，但实际成交价不可控，可能高于现价）
- SELL: `last_done > signal` → MARKET（同上，可能低于现价成交）

实际运行中观测到买入走 MARKET 单的情况，存在两点问题：

1. 期权流动性差时，市价单可能以远高于 `last_done` 的价格成交，等于把"占便宜"的优势让渡给对手盘。
2. 缺少价格上限保护；若推送时 quote 已陈旧，市价单的实际成交价可能严重偏离用户预期。

## 目标

买入和卖出**始终**使用限价单。当现价对自己更有利时，限价取**现价**（`last_done`）；否则限价取**信号价**（`signal`）。

## 决策表

| 方向 | 现价 vs 信号价 | 当前行为 | 新行为 |
|---|---|---|---|
| BUY | `last_done < signal` | MARKET | **LIMIT @ last_done** |
| BUY | `last_done >= signal` | LIMIT @ signal | LIMIT @ signal（不变）|
| SELL | `last_done > signal` | MARKET | **LIMIT @ last_done** |
| SELL | `last_done <= signal` | LIMIT @ signal | LIMIT @ signal（不变）|
| 任意 | 取不到现价 | LIMIT @ signal | LIMIT @ signal（不变）|

直觉：永远是 LIMIT 单，限价取"对自己更有利的那一边"——买入取较低价，卖出取较高价。

## 实现范围

**生产代码（一处）：** `backend/app/broker/trader.py` 的 `_decide_order_type_and_context`（第 78-119 行）

替换两个返回 `"MARKET"` 的分支，改为返回 `("LIMIT", last_done, rationale)`，rationale 中文文案对应更新，例如：

- `f"买入：现价 {last_done:.3f} < 信号价 {signal_price:.3f} → 限价单 @ {last_done:.3f}（取更低价）"`
- `f"卖出：现价 {last_done:.3f} > 信号价 {signal_price:.3f} → 限价单 @ {last_done:.3f}（取更高价）"`

**测试改动（4 个文件）：**

每个用例的改动模式一致：

- `assert order["order_type"] == "MARKET"` → `"LIMIT"`
- `assert order["price"] is None` → `pytest.approx(<last_done>)`
- `submitted_task.submit_order_type == "MARKET"` → `"LIMIT"`
- rationale 关键字断言 `"市价"` → `"限价"`

涉及文件：

1. `backend/tests/broker/test_trader.py:115-180` — `test_stock_buy_happy_path` 与 `test_option_buy_happy_path`
2. `backend/tests/broker/test_trader_deviation.py:304-360`
3. `backend/tests/integration/test_broker_lifecycle.py:151` — 行内注释 `< signal 26.5 → BUY MARKET` 改为 `→ BUY LIMIT @ last_done`
4. `backend/tests/integration/test_acceptance.py:213-289` — docstring 描述 + 断言同步

**TDD 顺序：** 先改测试断言（红）→ 改 `_decide_order_type_and_context`（绿）→ 跑 backend 全量回归。

## 不变更

- `OrderType` Literal 仍保留 `"MARKET"`（broker 协议层、SDK 适配层未来可能仍需支持）。
- 数据库 schema 与 API schema 中 `submit_order_type` 字段无需变更。
- `backend/tests/storage/test_schema.py` 与 `backend/tests/api/test_schemas.py` 中以 `"MARKET"` 作为示例值的用例保持不变（仅测 schema 序列化）。
- 旧版交易路径 `broker/auto_trader.py` 不动（refactor-v2 之外的代码已不在主路径上）。

## 风险与权衡

- **成交概率下降：** 现价更优时改用现价做限价，理论上若市场快速反转，可能错过成交。但 LIMIT @ last_done 与 MARKET 在快照瞬间的预期成交价相近，差异主要体现在快速波动时的滑点保护——这正是本次改动想要的保护。
- **取不到 quote 的兜底未变：** 仍 LIMIT @ signal，避免在缺少现价时盲目下单。

## 验收

1. `backend` 测试套件全绿（`pytest backend/tests/`）。
2. UI 上 `submit_order_context` 文案能正确展示新规则。
3. 手动跑一次仿真任务（BUY，现价低于信号价），观察提交订单为 LIMIT 而非 MARKET。
