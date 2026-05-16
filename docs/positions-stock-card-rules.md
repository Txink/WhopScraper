# 股票卡片规则总览

> 持仓面板（PositionsPanel）股票 Tab 中的单张正股卡（PositionCard + IntradaySpark）的所有显示规则。期权卡（OptionCard）有重叠但走独立路径，本文不展开。

最后更新：2026-05-16

---

## 1. 卡片整体布局

```
┌─────────────────────────────────────────┐
│ TSLA  美股 盘中  →                      │  ← 顶部：ticker + 市场 pill + session pill
│ Tesla Inc                               │  ← 公司名（HK/CN 数字代码必带，US 可选）
├─────────────────────────────────────────┤
│ $245.500   ▲ +2.29%        +$5,500     │  ← 价格行：现价 / 涨跌幅 chip / 当日盈亏
├─────────────────────────────────────────┤
│ ┌─────────────────────────────────────┐ │
│ │ 盘前 │ 盘中 │ 盘后                  │ │  ← 分时图（SVG）
│ │      .・--/\___/\─── ●(pulse)       │ │
│ └─────────────────────────────────────┘ │
├─────────────────────────────────────────┤
│ 持仓     均价      总市值    浮盈       │  ← 元数据网格（4 列）
│ 240     232.180   $58,920   +$3,200    │
└─────────────────────────────────────────┘
```

源文件：`frontend/src/components/Positions/PositionCard.tsx` + `IntradaySpark.tsx` + `Positions.css`

---

## 2. 顶部 — Ticker / 市场 pill / Session pill

### 2.1 Ticker（左）

显示 `position.ticker`（broker 字段）。`TSLA.US` → `TSLA`，`0700.HK` → `0700`，`600519.SH` → `600519`。

### 2.2 市场 pill（中）

源：`marketBadge(symbol)` → 解析 `.US` / `.HK` / `.SH` / `.SZ` 后缀。

| 后缀 | 显示 | 颜色 |
|---|---|---|
| `.US` | `美股` | 冷蓝 `#6aa9ff` |
| `.HK` | `港股` | 紫 `#d28cff` |
| `.SH` | `沪 A` | 黄 (`--warn`) |
| `.SZ` | `深 A` | 黄 (`--warn`) |

### 2.3 Session pill（右）

源：`effectiveSession(market, quote.trade_session, Date.now())`（前端 weekend guard，不直接用 broker 推送值）。

| effectiveSession | 显示文字 | 配色 |
|---|---|---|
| `pre` | `盘前` | 冷蓝 `#6aa9ff` |
| `regular` | `盘中` | 品牌青 `var(--brand)` *中性，不跟随 colorMode* |
| `post` | `盘后` | 暖橙 `#f0a040` |
| `overnight` | `夜盘` | 紫 `#b388ff` |
| `closed` | `休市` | 灰 (`--fg-3`) |

**为什么用 `effectiveSession` 不用原始 `quote.trade_session`？**
后端 `MarketSchedule` 的缓存窗口是按 time-of-day 匹配，cache miss + 周末时会把"周六 ET 04:00"误匹配为周五的 pre 窗口，推 `trade_session="pre"`。前端做 weekday 守卫：
- US 周六 / 周日 ET 20:00 前 → 强制 `closed`
- HK / CN 周末 → 强制 `closed`
- 工作日 → 透传 broker 值

后端 `MarketSchedule.state_for` 也修了同样的 bug（commit `3b9b319`），但前端的 guard 留作兜底。

---

## 3. 价格行 — 现价 / 涨跌幅 chip / 当日盈亏

### 3.1 现价

显示 `toUsd(symbol, quote.last_done)`，3 位小数 + `$` 前缀。

**Last_done 的语义随 session 变化（后端 `_quote_to_dict` 选择 tier）：**

| State | 选用 tier | 说明 |
|---|---|---|
| `pre` | `q.pre_market_quote.last_done` | 盘前最新 |
| `regular` | `q.last_done` | RTH 实时 |
| `post` | `q.post_market_quote.last_done` | 盘后最新 |
| `overnight` | `q.overnight_quote.last_done` | 夜盘最新 |
| `closed` | **overnight > post > RTH 优先取最新非空** | 见 §3.4 |

`closed` 状态的特殊处理是关键修复（commit `1d987fc`）：周末时 RTH 是周五 16:00 收盘价（过时），但盘后还可能跌/涨；用户看 LongBridge App 显示的"现价"实际是盘后最后一笔，我们必须匹配。

### 3.2 涨跌幅 chip

显示 `quote.change_pct`，带 ▲/▼ 箭头。颜色：
- `change_pct ≥ 0` → `var(--up-color)` + 浅色背景
- `change_pct < 0` → `var(--down-color)` + 浅色背景

`up-color` / `down-color` 跟随用户的 `colorMode` 偏好翻转（US 模式绿涨 / CN 模式红涨）。

### 3.3 当日盈亏（Day P/L）

显示美元金额（无小数），大字号，靠右对齐。颜色同涨跌幅 chip。

**公式（统一）：**
```
Day P/L = last × qty_now
        + Σ sellsProceeds_today
        - Σ buysCost_today
        - dayBaseline × qty_start_today

where qty_start_today = qty_now - Σ buysQty_today + Σ sellsQty_today
```

### 3.4 dayBaseline 的解析（session-aware）

| Session | dayBaseline | 数据源 |
|---|---|---|
| `pre` | 昨日 RTH 收 | `quote.prev_close` |
| `regular` | 昨日 RTH 收 | `quote.prev_close` |
| `post` | 今日 RTH 收 (16:00 ET) | `quote.today_close` |
| `overnight` | 今日 RTH 收 (16:00 ET) | `quote.today_close` |
| `closed` | 上一交易日的 RTH 收（不是日历昨日）| `quote.prev_close` *（LongBridge SDK 在 closed 状态已返回上一交易日收盘）* |

后端做了一层 override（commit `cb437e8`）：closed 状态时再 fetch 一次日 K 拿 `bars[-2].close` 作为兜底，但实测 LongBridge SDK 本身就返回正确值，override 实际是 no-op，留作 broker 语义万一变化时的安全网。

### 3.5 今日交易过滤（`tradingDayOfET` + `currentOrLastTradingDay`）

`executions` 进入 Day P/L 公式前的过滤：
```ts
if (tradingDayOfET(e.ts) !== currentOrLastTradingDay()) continue;
```

- **`tradingDayOfET(iso)`** — 把执行时间映射到所属交易日（ET 04:00 切日；00:00-04:00 ET 归入前一交易日的夜盘尾）
- **`currentOrLastTradingDay()`** — 周末/节假日步退到最近一个工作日。周六视角下返回"周五"，周五的交易才能正确被吸纳进 Day P/L 调整（commit `8db45b4`）

---

## 4. 分时图（IntradaySpark）

### 4.1 整体结构

- **SVG**：`viewBox="0 0 100 100" preserveAspectRatio="none"` —— 视觉上拉伸到容器尺寸（高 60px，宽自适应），曲线用 `vector-effect: non-scaling-stroke` 保持 1.8px 宽
- **背景水印**：HTML overlay（不在 SVG 内，避免 preserveAspectRatio 把字压扁），每个 session 区段中点一个中文标签
- **虚线分隔**：consecutive region 之间 1px dashed
- **Pulse dot**：DOM `<span>`，CSS 关键帧动画

源文件：`IntradaySpark.tsx` + `sessionWindow.ts` + `Positions.css`

### 4.2 X 轴窗口（按市场切分）

| 市场 | Anchor | 时长 | slotCount | Regions（左→右） |
|---|---|---|---|---|
| US | ET 04:00 chartDay | 16h | 960 | 盘前 [0,330) + 盘中 [330,720) + 盘后 [720,960) |
| HK | HKT 09:30 chartDay | 5.5h | 330 | 盘中 [0,330)；午休 12:00-13:00 压缩 |
| CN | CST 09:30 chartDay | 4h | 240 | 盘中 [0,240)；午休 11:30-13:00 压缩 |

**夜盘已从 US 视图移除**（commit `325d7fe`）：仅保留 16h 盘前+盘中+盘后。

**HK 午休压缩**：slot 0..149 = 上午 09:30-11:59，slot 150..329 = 下午 13:00-15:59。`msToSlot(12:00-13:00 期间)` 返回 -1，bar 被丢弃。CN 类似。

### 4.3 chartDay 解析

**US：**
- `getEtHour(now) ≥ 4` → chartDay = ET 今天（盘前/盘中/盘后/夜盘起始）
- `getEtHour(now) < 4` → chartDay = ET 昨天（夜盘尾巴，但显示昨天的完整 pre+regular+post）
- `closed` 状态 → chartDay = `lastTradingDateKey(now, "US")`（步退到最近工作日，例如周六→周五）

**HK / CN：**
- 工作日 → chartDay = 当前市场时区的日期
- `closed` 状态 → chartDay = 步退到最近工作日

### 4.4 Bar 投影规则

`points = bars.map(b => { slot: msToSlot(parseAsBJ(b.timestamp)), close: b.close }).filter(...)` 后：
- **过滤条件**：slot < 0（窗口外或午休段）、close ≤ 0（后端把"无成交分钟"序列化成 `close: 0.0`，会污染 y 轴范围）
- **`parseAsBJ`**：将 broker 的 naive timestamp 当 BJ 墙钟解析为 UTC ms

### 4.5 Y 轴范围

```
yMin = min(closes), yMax = max(closes)
pad  = (yMax - yMin) × 0.2 || |yMin| × 0.005 || 0.5
y    = [yMin - pad, yMax + pad]   // ±20% padding，避免触顶/触底
```

### 4.6 颜色（上涨 / 下跌）

```
isPos = (lastDone ?? lastClose) >= (openPrice ?? firstClose)
```

isPos → 整图 `--up-color`；否则 `--down-color`。两个 token 跟随 colorMode（US 绿涨 / CN 红涨）。

**`is-closed` 状态：** 线变灰 (`--fg-3`)、area 透明度降到 30%、水印更暗、不渲染 pulse、不高亮 active region。

### 4.7 Region 水印 + 分隔

每个 region 在自己 slot 区间中点画一个中文 label。当前活跃 session 对应的 region 加 `.active` 类（更高对比度）。consecutive region 之间画 dashed 竖线分隔。

`closed` 状态：所有 region 都画 label 但都不 active。

### 4.8 Live tip 合并

每条 quote.snapshot 推送进来后：
- **closed / overnight / lastDone null** → bars 原样返回（不做合并，避免污染历史快照）
- **nowSlot < 0**（窗口外或午休）→ bars 原样
- **nowSlot < lastBarSlot**（时钟倒流，罕见）→ 覆写最后一根 close = lastDone
- **nowSlot == lastBarSlot**（同分钟内）→ 覆写 close、刷新 high/low
- **nowSlot > lastBarSlot**（跨分钟边界）→ append 一根新 bar（local 状态，**不回写 store**）

合并产物仅在 `IntradaySpark` 的 useMemo 里，不污染 `useCandlesticksStore`；下一次正常拉数（session 切换 / 账户切换 / mount）会把真实 bar 覆盖回来。

### 4.9 Pulse dot

- **位置**：`x = win.progress(Date.now()) * containerWidth`（注意：x 来自时间进度，不是最后一根 bar 的位置——盘前刚开盘 1h 时 pulse 应在最左 ~1/16 处）
- **y**：`yFor(lastDone)` 在 viewBox 坐标系中的百分比 × containerHeight
- **closed / overnight / containerSize.w === 0** → 不渲染
- 动画：`@keyframes minline-pulse`（1.8s 循环 halo），`prefers-reduced-motion` 时禁用

---

## 5. 数据获取（PositionsPanel 编排）

### 5.1 初始 fetch（mount 时）

`PositionsPanel` 调用 `api.candlesticks(symbol, "today", { granularity: "分时", sessions: resolveSessionParam(market, currentSession) })`：

| Market | sessions 参数 |
|---|---|
| US（任何 session）| `"all"` *（覆盖 pre+regular+post，单次 broker 调用，count=1000）* |
| HK / CN | `"regular"` |

cache key：`${symbol}::today::分时::${sessions}`，存入 `useCandlesticksStore`。

### 5.2 Session 切换重拉

`useSessionTransitionRefetch(stocks)` hook：每条 quote.snapshot 推送都跑 effect，但用 `useRef<Record<string, string>>` 做 per-symbol session-string diff，**只在真的发生变化时**触发一次 refetch。一天最多 4 次（4 个 session 边界），不会被推送频率打爆 broker。

### 5.3 全局订阅管理

订阅由后端 `SubscriptionManager` 维护（每个 broker 一份）：
- `add_quote_listener(fn)` / `add_execution_listener(fn)` 注册回调
- `watch_quotes([symbols])` 增量 diff 后调 broker subscribe/unsubscribe
- WebSocket 推送 → `useQuotesStore.upsertQuote(symbol, patch)` 合并到前端 store

前端无需为每张卡单独订阅；`PositionsPanel.usePositionsData` 在 mount 时一次性 `api.watchQuotes([all_symbols])`，卡片只读 store。

---

## 6. Closed 状态完整规则（核心）

整理散落各处的 closed 行为：

| 维度 | 行为 |
|---|---|
| Session pill | "休市"，灰色 |
| 现价 | overnight > post > RTH 优先，取最新非空 tier |
| 涨跌幅 / Day P/L 基线 | `prev_close`（broker 返回的就是上一交易日 RTH 收）|
| 分时图窗口 | 上一交易日的 16h（US）/ 5.5h（HK）/ 4h（CN）|
| Region 高亮 | 全部 region 都不 active |
| Pulse dot | 不渲染 |
| Live tip 合并 | 不执行（保持历史快照不被污染）|
| 今日交易过滤 | `currentOrLastTradingDay()` 步退到最近工作日 |
| 周末 trade_session 来源 | 前端 `effectiveSession` 强制 closed（不信 broker 推送）|
| 后端 `state_for` | 已修：weekday 校验 + overnight 两端都要交易日 |

---

## 7. 时区 / DST

- **broker 时间戳**：naive ISO 字符串，按 BJ 墙钟解析（`parseAsBJ` 在 `IntradaySpark.tsx`、`sessionSlots.ts`）
- **ET 时区**：所有 US session 边界用 `Intl.DateTimeFormat({ timeZone: "America/New_York" })` 解析，DST-safe
- **HKT / CST**：年中无 DST，固定 UTC+8
- **trading day key**：US 按 ET 04:00 切日（夜盘 00:00-04:00 ET 归入前一交易日尾）
- **DST 转换**：3 月第 2 周日 / 11 月第 1 周日。`localToUtcMs` 用 2-pass 迭代修正，自动处理春进秋出

---

## 8. 主要源文件索引

| 文件 | 责任 |
|---|---|
| `frontend/src/components/Positions/PositionCard.tsx` | 卡片主组件，组合所有数据/计算 |
| `frontend/src/components/Positions/IntradaySpark.tsx` | SVG 分时图组件 |
| `frontend/src/components/Positions/sessionWindow.ts` | 窗口解析器 + `effectiveSession` weekend guard |
| `frontend/src/components/Positions/resolveSessionParam.ts` | 解析 broker sessions 参数（US→"all"，HK/CN→"regular"）|
| `frontend/src/components/Positions/SparkDefs.tsx` | 全局 SVG `<defs>`（up/down 渐变）|
| `frontend/src/components/Positions/PositionsPanel.tsx` | 持仓面板，数据编排（初始 fetch + 转 session refetch）|
| `frontend/src/components/Positions/timeFmt.ts` | BJ/ET 时区格式化 + `tradingDayOfET` + `currentOrLastTradingDay` |
| `frontend/src/components/Card/cardHelpers.ts` | `marketOf(symbol)` 等共享 helper |
| `frontend/src/stores/quotes.ts` | 全局 quote 缓存（store） |
| `frontend/src/stores/candlesticks.ts` | 全局 candlestick 缓存（store）|
| `backend/app/broker/longport_client.py` | `_quote_to_dict` tier 选择、`_apply_closed_state_baseline` 等 |
| `backend/app/broker/market_schedule.py` | `state_for` weekday 校验 + holiday-aware `is_trading` |
| `backend/app/broker/subscription_manager.py` | 全局订阅管理器 |
| `backend/app/api/http.py` | `/api/candlesticks`、`/api/quotes` 等 HTTP 端点 |

---

## 9. 关键 commit 索引

| Commit | 主题 |
|---|---|
| `d758832` | 统一 24h 窗口 + 每个 session 一个 region label |
| `9f75959` | 夜盘移到最前 + 周末 effective session 守卫 |
| `a998fb4` | 过滤 close=0 bar + 后端 count bump |
| `325d7fe` | 取消夜盘 region，回到 16h 窗口（pre+regular+post）|
| `8db45b4` | `currentOrLastTradingDay` 周末步退 → Day P/L 含周五交易 |
| `cb437e8` | 后端 closed 状态 prev_close override（兜底）|
| `3b9b319` | 后端 `MarketSchedule.state_for` 周末校验 |
| `1d987fc` | **closed 状态 last_done 取盘后最新 tier**（修正 TSLL Day P/L 1397→2146）|

---

## 10. 已知 follow-up

1. **后端 `_BARS_PER_DAY_ALL["min_1"] = 1000`** — LongBridge `candlesticks` API 上限。完整一天 24h 需要 1440 bars，目前只覆盖 pre+regular+post (16h = 960 bars) + ~40min 夜盘 buffer。如需完整夜盘，得切到 `history_candlesticks_by_offset` 或多次调用。
2. **CN A 股的 ET-based `tradingDayOfET` 反向归类** — `tradingDayOfET` 用 ET 04:00 切日，HK / CN 交易的执行时间（HKT/CST）映射回 ET 时可能落到错误日。当前对周末过滤够用，但跨时区 holiday 边界可能漂。
3. **节假日日历** — `lastTradingDateKey` 只跳周末，不查节假日。Monday 是 holiday 时（如 Memorial Day），closed 状态下窗口会锚到 Monday 而非 Friday。可以接 `MarketSchedule._trading_days` cache 但需要前端能拿到这个数据。
4. **Pulse 平盘漂移** — pulse x 坐标基于 `win.progress(Date.now())`，但 useMemo 依赖只包含 prop。若 `lastDone` 长时间不变（盘中平盘），re-render 不触发，pulse 视觉上"停住"。可以加 RAF + interval 但代价 vs 收益不大。
