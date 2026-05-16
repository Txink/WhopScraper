# LongBridge 行情接口响应数据 — 按 session 分类

> LongBridge OpenAPI `quote_ctx.quote(symbols)`、`quote_ctx.candlesticks(...)`、`trade_ctx.history_executions(...)` 等接口在不同交易时段返回的数据形态实测笔记。
>
> 用于排查"为什么 TSLL Day P/L 显示 1397 而不是 2146"这类问题——SDK 的 `prev_close` / `last_done` / extended-hours tier 在不同 session 下的语义不同，需要写死才能正确解释。

最后更新：2026-05-16

---

## 表格图例

- **`q`** = `SecurityQuote` 对象（`quote_ctx.quote([symbol])[0]`）
- **`q.X`** = 主对象上的字段
- **`tier`** = `q.pre_market_quote` / `q.post_market_quote` / `q.overnight_quote` 子对象
- 字段下的"周X"指**当前交易日**视角下的某一天，例如周六视角下"周五"=最近一个交易日

---

## 1. 休市（state = "closed"）

**实测场景**：2026-05-16（周六）BJ 16:00+ 时段查询。最近一个美股交易日 = 周五 2026-05-15。

### 1.1 `quote_ctx.quote(["TSLL.US"])` 返回

```python
q.symbol               = "TSLL.US"
q.last_done            = 15.060       # 周五 RTH 收盘价（16:00 ET frozen）
q.prev_close           = 16.650       # 周四 RTH 收盘价 ←  注意：是上一交易日，不是日历昨日
q.open                 = 15.960       # 周五 RTH 开盘
q.high                 = 16.000       # 周五 RTH 高
q.low                  = 15.042       # 周五 RTH 低
q.volume               = 81372383     # 周五全天成交量
q.timestamp            = 2026-05-16 04:00:00   # 最后更新时刻（看起来是 ET 时区，未确认）

q.pre_market_quote.last_done   = 15.960    # 周五盘前最后价（也可能是 close）
q.pre_market_quote.high        = 16.367
q.pre_market_quote.low         = 15.640

q.post_market_quote.last_done  = 14.760    # 周五盘后最后价 ← 现价应该用这个
q.post_market_quote.high       = 15.140
q.post_market_quote.low        = 14.750

q.overnight_quote              = None / 空   # 该 ticker 未开通夜盘或无夜盘活动
```

### 1.2 关键发现

#### `prev_close` = 上一交易日收盘，不是日历昨日

我们曾误以为周六的 `prev_close` 是"周五（calendar yesterday）的 RTH 收盘"。实测：**LongBridge SDK 在 closed 状态下返回的 `prev_close` 是 *上一交易日之前的那一天的 RTH 收盘***（周六视角 = 周四，不是周五）。

这意味着：
- `change = last_done - prev_close` = 周五完整 session 涨跌（含盘后）— 如果 last_done 用了正确的 tier
- 我们之前加的"override `prev_close` from daily bars"逻辑（commit `cb437e8`）实际是 no-op，SDK 就已经给的对值

#### `last_done` 是过时的 RTH 收盘价（重要）

`q.last_done` 在周六返回 `15.060`，但这只是**周五 16:00 ET RTH 收盘价**，被 frozen 下来了。周五盘后的实际最后成交价在 `q.post_market_quote.last_done = 14.760` 里。

**用户在 LongBridge App 看到的"现价"是 `post_market_quote.last_done`**（最新的有效报价），不是 RTH 收盘价。我们之前的 `_quote_to_dict` 在 closed 状态没考虑 tier，直接用 `q.last_done` → 现价偏离用户期望。修复后（commit `1d987fc`）closed 优先取 overnight > post > RTH，对齐 App 行为。

#### Daily 日 K 时间戳格式

```
[0] ts=2026-05-11 12:00:00 O=15.170 H=17.130 L=14.770 C=16.835 V=155128209
[1] ts=2026-05-12 12:00:00 O=16.560 H=17.040 L=15.110 C=15.960 V=111501544
[2] ts=2026-05-13 12:00:00 O=16.200 H=17.415 L=15.710 C=16.840 V=130349077
[3] ts=2026-05-14 12:00:00 O=16.920 H=17.320 L=16.510 C=16.650 V=82263975
[4] ts=2026-05-15 12:00:00 O=15.960 H=16.000 L=15.042 C=15.060 V=81372383
```

- **排序**：oldest first，索引 `[-1]` = 最近一个交易日（周五），索引 `[-2]` = 上一交易日（周四）
- **时间字段**：`YYYY-MM-DD 12:00:00`（看起来固定 noon 占位，无实际意义；日期才是关键）
- **`bars[-1].close` == `q.last_done`** = 15.060（周五 RTH 收盘）✓
- **`bars[-2].close` == `q.prev_close`** = 16.650（周四 RTH 收盘）✓ — 验证了 `prev_close` 就是上一交易日

#### `q.timestamp` 字段

```python
q.timestamp = 2026-05-16 04:00:00
```

具体含义不完全确定。可能是"周一夜盘开始时刻 (Sun 20:00 ET = Mon 00:00 UTC = Mon 08:00 BJ)"或"最后一笔报价的时间"或"close + 8h"。**实际使用中我们没读这个字段**，只用 last_done + prev_close 等数值。如需精确语义参考 LongBridge 官方文档。

### 1.3 `trade_ctx.history_executions(...)` — 周末查近 14 天

字段示例（账号 `3aa61c21`，TSLL.US，截至周六查询）：

```
trade_done_at         side  qty    price    order_id
2026-05-04 23:24:02   BUY   613   12.80    ...
2026-05-04 23:24:02   BUY   1387  12.80    ...   ← 同一笔订单分多次成交
2026-05-05 03:36:10   SELL  636   13.21    ...
...
2026-05-15 22:01:30   BUY   2000  15.36    ...   ← 周五 10:01 ET 唯一交易
```

**关键**：
- `trade_done_at` 是 **BJ 墙钟**（北京时间），不是 UTC。例如 `2026-05-15 22:01:30` 对应 UTC `14:01:30` = ET `10:01:30`。
- 一笔订单可能分成多次成交（不同 order_id 子事件，价格相同）。每次都是独立 row。
- 周末查询能正常返回工作日的所有交易；不会被 broker block。

### 1.4 `trade_ctx.stock_positions()` — 当前持仓

```python
position.symbol     = "TSLL.US"
position.quantity   = 2501           # 当前持股数
position.cost_price = 13.470         # 平均成本
position.currency   = "USD"
```

**注意**：position quantity 反映 broker 当前真实持仓（含所有 fills 后）。`qty_now` ≠ 周五开盘前的持仓（qty_start），需用 `qty_start = qty_now - Σ(today_buys) + Σ(today_sells)` 反推。

### 1.5 完整对账（TSLL Day P/L 实测）

| 数据 | 来源 | 值 |
|---|---|---|
| `last_done` | `q.post_market_quote.last_done` | 14.760 |
| `prev_close` | `q.prev_close` | 16.650 |
| `qty_now` | `position.quantity` | 2501 |
| 周五 BUY | `history_executions` | 2000 @ 15.36 |
| `qty_start` | `qty_now - buysQty + sellsQty` | 501 |
| `buysCost` | `2000 × 15.36` | 30720 |
| `sellsProceeds` | (none Friday) | 0 |

```
Day P/L = last × qty_now + sellsProceeds - buysCost - prev_close × qty_start
       = 14.760 × 2501 + 0 - 30720 - 16.650 × 501
       = 36914.76 - 30720 - 8341.65
       = -$2146.89
```

✓ 匹配用户在 LongBridge App 看到的 `-$2146`。

如果错用 `q.last_done = 15.060`（RTH 收盘），得到 `-$1396.59` — 我们之前的 bug 数。

---

## 2. 盘前（state = "pre"）— 待补

实测数据待补。预期：
- `q.last_done`：盘前实时（或 frozen 在 09:30 ET 时刻）
- `q.prev_close`：昨日 RTH 收
- `q.pre_market_quote.last_done`：当前盘前实时（与 q.last_done 应一致或同步）

---

## 3. 盘中（state = "regular"）— 待补

实测数据待补。预期：
- `q.last_done`：RTH 实时
- `q.prev_close`：昨日 RTH 收
- `q.pre_market_quote`：当日盘前 frozen（last_done = 盘前最后一笔）
- `q.post_market_quote`：None / 空
- `q.overnight_quote`：None / 空

---

## 4. 盘后（state = "post"）— 待补

实测数据待补。预期：
- `q.last_done`：今日 RTH 收（frozen 在 16:00 ET）— 这是 `today_close` 的来源
- `q.prev_close`：昨日 RTH 收
- `q.pre_market_quote`：今日盘前 frozen
- `q.post_market_quote.last_done`：盘后实时
- `q.overnight_quote`：None（还没开始）

---

## 5. 夜盘（state = "overnight"）— 待补

实测数据待补。预期：
- `q.last_done`：今日 RTH 收（继续 frozen）
- `q.prev_close`：昨日 RTH 收
- `q.post_market_quote`：当日盘后 frozen（last_done = 20:00 ET 时刻）
- `q.overnight_quote.last_done`：夜盘实时

---

## 6. 调用 SDK 的最简代码片段（供调试参考）

```python
"""Probe a symbol's full quote state."""
import sys
sys.path.insert(0, 'backend')
from longbridge.openapi import OAuthBuilder, Config, QuoteContext, Period, AdjustType, TradeSessions

CLIENT_ID = "..."  # ~/.longbridge/openapi/tokens/ 下的目录名
SYMBOL = "TSLL.US"

oauth = OAuthBuilder(CLIENT_ID).build(lambda url: None)
config = Config.from_oauth(oauth, enable_overnight=True)
ctx = QuoteContext(config)

q = ctx.quote([SYMBOL])[0]
print(f"symbol={q.symbol}")
print(f"last_done={q.last_done}")
print(f"prev_close={q.prev_close}")
print(f"open={q.open} high={q.high} low={q.low}")
print(f"timestamp={q.timestamp}")
for tier_name in ("pre_market_quote", "post_market_quote", "overnight_quote"):
    tier = getattr(q, tier_name, None)
    if tier is not None:
        print(f"{tier_name}: last_done={tier.last_done} high={tier.high} low={tier.low}")

bars = ctx.candlesticks(SYMBOL, Period.Day, 5, AdjustType.NoAdjust,
                       trade_sessions=TradeSessions.Intraday)
for i, b in enumerate(bars):
    print(f"day[{i}] ts={b.timestamp} O={b.open} C={b.close}")
print(f"bars[-2].close (上一交易日) = {bars[-2].close}")
print(f"bars[-1].close (最近交易日) = {bars[-1].close}")
```

---

## 7. 已知细节

### 7.1 多账户隔离

LongBridge 账户彼此独立：position / executions / quote 都是按 OAuth client_id 隔离。同一个 symbol 在不同账户下可能 quantity / avg_cost 完全不同。signal-station 的 DB 通常只存"主账户"的 executions（`account_id` 字段索引），但 broker SDK 可以分别拉。

### 7.2 `enable_overnight` 鉴权位

`Config.from_oauth(oauth, enable_overnight=True)` 才能拿到 US 夜盘数据。FAQ Q6：需要先在 LongBridge App 行情商店购买"LV1 实时行情 (OpenAPI)"卡。HK 不支持夜盘，flag 对 HK 是 no-op。

### 7.3 `candlesticks` count 上限 = 1000

SDK 文档明确："count: Count of candlestick (Maximum is `1000`)"。单次最多返回 1000 根。全天 24h 1m bars = 1440 根超限。

```
HTTP /api/candlesticks?period=today&granularity=分时&sessions=all
  → backend get_candlesticks count=1000 → 覆盖 pre+regular+post (960 bars) + ~40min 夜盘
```

完整夜盘需用 `history_candlesticks_by_offset(forward=False, count=N, time=anchor)`（待实现）。

### 7.4 Daily 日 K 排序

`candlesticks(symbol, Period.Day, N, ...)` 返回**oldest first**，即 `bars[-1]` 是最近一个交易日。
