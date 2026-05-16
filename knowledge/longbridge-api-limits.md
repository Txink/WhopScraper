# LongBridge OpenAPI 已知接口限制

> 调用 LongBridge OpenAPI（`longbridge` Python SDK 包，4.1.0 实测）时容易踩到的、文档里没写或写得不显眼的硬限制。每一条都附排查路径和我们在代码里的应对策略。

最后更新：2026-05-17

---

## 1. `trade_ctx.history_executions` / `trade_ctx.history_orders` — 单次窗口 ≤ 90 天

**限制内容**：`start_at` 与 `end_at` 跨度超过 90 天时，SDK 抛异常（C-extension 内部抛，调用层 `try/except` 兜底拿到的是空列表）。

**症状**：
- 调用一次返回 0 条，但同账号当窗口内真的有大量成交
- 日志里出现 `history_executions fetch failed: ...` 或 `history_orders fetch failed: ...`
- 业务上的现象：清空 `broker_executions` 表后打开某只股票的详情面板，"交易记录"只显示极少几条，且都是最近几天的（最近几天那几条其实是 `/api/broker/today_executions` 2 天窗口 sync 顺手写进来的）

**踩坑历史**：`backend/app/broker/executions_sync.py` 一开始的"首次回填"是单次 730 天宽窗口调用，期望 SDK 把 2 年成交一次性返回，实测全部失败。

**应对策略**：所有走 `history_executions` / `history_orders` 的代码都必须在调用层把目标时间区间切成 **≤ 90 天** 的块，逐块调用、逐块 upsert。

代码入口：
- `backend/app/broker/executions_sync._sync_chunked` — 通用分块循环
- `backend/app/broker/executions_sync.sync_broker_executions(days=N)` — `today_executions` (2 天) 和增量补齐都走这里
- `backend/app/broker/executions_sync.sync_broker_executions_incremental` — 首次回填默认 `fallback_days=730`，切 9 块；空窗口提前终止（账户开户晚于 fallback_days 的情形）

**测试守护**：`tests/broker/_fakes.FakeBrokerClient.history_executions` 在 `(end_at - start_at) > 90d` 或 `days > 90` 时主动抛 `ValueError`，防止后续重构者再次写成单次宽调用。代表性测试：
- `tests/api/test_http.py::test_history_executions_endpoint_backfills_across_windows`
- `tests/api/test_http.py::test_history_executions_endpoint_incremental_gap_over_90d_chunks`
- `tests/api/test_http.py::test_history_executions_endpoint_full_backfill_even_with_narrow_sync_residue`

**配套陷阱：`MAX(ts)` 不能当作"已完整 backfill"的标志**

`/api/broker/today_executions`（dashboard 加载 Day P/L 时跑）只拉 **2 天** 窗口、不带 ticker 过滤，会把每个 ticker 写 0–1 条最近成交进 `broker_executions`。如果详情页 sync 用 `MAX(ts)` 推断"是不是已经回填过历史"，就会被这条窄窗口残余误导，把 730 天回填降级成 1 天 gap，结果只能拿到 1 条。

应对：用 `positions.history_synced` 这个**显式**布尔位作锚点，**只在完整分块回填成功后**才置 True。详情页 sync 入口先查这个位决定走 full backfill 还是 gap-from-MAX：

- 代码入口：`sync_broker_executions_incremental` 检查 `repo.is_position_history_synced(account_id, ticker)`
- 写位入口：full backfill 走完后 `repo.mark_position_history_synced(account_id, ticker)`，把同 ticker 下所有 symbol row（股票 + 期权合约）一起标
- 持仓 row 在用户卖空后**不删，只置 quantity=0**，让 `history_synced` 跨"清仓 → 复购"周期存活，避免不必要的二次回填

代表性测试：`test_history_executions_endpoint_full_backfill_even_with_narrow_sync_residue`

**注意**：`_fetch_executions_window`（`longport_client.py`）的调用方必须保证传入的 `start`/`end` 已经 ≤ 90 天 —— 这个函数同时调用 `history_orders` 和 `history_executions`，两者用同一窗口，违反限制时两边都会失败，导致 `side_by_order` 为空进而过滤掉所有 execution。

---

## 2. `trade_ctx.today_executions` — 用 HK/BJ 自然日，不是 ET 交易日

**限制内容**：SDK 的 `today_executions()` 用 **UTC+8（HK/BJ）零点** 切分"今天"。

**症状**：美股 RTH 阶段（BJ 23:30+）的成交，SDK 视角下属于"明天"；BJ 凌晨拿到的"今天"反而是空。

**应对策略**：不直接用 `today_executions()`。改成 `history_executions(start_at=now-30h, end_at=now)`，覆盖一个完整 ET 交易日的窗口，前端再按 ET 交易日过滤。

代码入口：`backend/app/broker/longport_client.LongPortClient.today_executions`（注释里有详细说明）。

---

## 3. `quote_ctx.quote(symbols)` — 不同 session 下字段语义会变

**限制内容**：同一个 `SecurityQuote` 对象，`last_done` / `prev_close` / `open` / `high` / `low` 等字段在盘前 / 盘中 / 盘后 / 夜盘 / 休市这五种 session 下指向的"哪一天"会变。子对象 `pre_market_quote` / `post_market_quote` / `overnight_quote` 同样不一致。

**应对策略**：详见独立的 [`longbridge-quote-response-by-session.md`](./longbridge-quote-response-by-session.md)，里头按 session 写了每个字段的实测语义。

---

## 4. C-extension 对象的字段读取要小心

**限制内容**：LongBridge SDK 的核心对象（`PushOrderChanged`、`Execution`、`Order`、`OrderStatus` 等）是 Rust 编出来的 C-extension，**不是普通 Python 对象**：
- `vars(obj)` 可能不抛异常但返回的不是 dict（拿到的是 `__dict__` property 本身），直接迭代会出错
- `obj.__dict__` 不存在
- 枚举值（如 `OrderStatus`）没有 `.name` / `.value`，`repr(obj)` 形如 `"OrderStatus.Filled"`，必须 `repr(...).split(".")[-1]` 才能拿到字符串
- `Decimal` 字段（价格、数量）`repr` 形如 `"Decimal('7.29')"` —— 用通用的"按点号 split"路径会把它劈成 `"29')"` 之类的垃圾

**应对策略**：
- 序列化先做 `isinstance` 类型分支（`Decimal` / `Enum` / `datetime` 分别处理），最后再用通用 `repr` 兜底
- 拆字段时优先用 `getattr(obj, name)` 而不是 `vars(obj)` / `obj.__dict__`
- 枚举值的字符串提取用 `_extract_status_label`（`push_listener.py`）这种集中处理

代码入口：`backend/app/broker/push_listener._serialise_value` / `_to_payload_dict` / `_extract_status_label`。

---

## 5. `trade_ctx.history_orders` 的 `side` 来自 `order_id` join，不在 execution 上

**限制内容**：`Execution` 对象本身**不携带** `side` 字段。要知道某笔成交是 BUY 还是 SELL，必须同窗口先拉 `history_orders`，再按 `order_id` join 回去。

**应对策略**：`_fetch_executions_window` 同窗口先调 `history_orders` 拿 `{order_id: side}` 映射，再把 `history_executions` 的每条记录按 `order_id` 查表填上 `side`；查不到（或 side 不是 BUY/SELL）的直接丢弃。

**副作用**：90 天限制对两个 SDK 调用同时生效，一旦窗口宽到导致 `history_orders` 失败，**所有** execution 都会被过滤（side 查不到），症状是"全空"而不是"少几条"。这正是上面 §1 切块的原因之一。

---

## 6. `trade_done_at` / `submitted_at` 等时间字段是 HK 本地裸 datetime

**限制内容**：SDK 返回的时间字段都是 **不带 tzinfo 的 naive datetime**，而且时区是 **HK 本地（UTC+8）**，不是 UTC。

**应对策略**：所有从 SDK 拿到的 naive datetime 一律加上 `tzinfo=timezone(timedelta(hours=8))` 再做下游处理，DB 落盘时再 `astimezone(UTC).replace(tzinfo=None)` 转回 UTC naive。

代码入口：`backend/app/broker/longport_client._fetch_executions_window`（`ts = ts.replace(tzinfo=timezone(timedelta(hours=8)))`）。

---

## 7. 账号切换：`is_paper` / `account_id` 在 broker 实例上是只读 property

**限制内容**：切换主/副账号或者切换实盘/模拟盘需要**重新构造 `LongPortClient`** —— 同一个 `_trade_ctx` 不能改账号。

**应对策略**：`main.py` 里把 broker 构造闭包化（`_build_broker()`），切账号走 `POST /api/longport/broker/reload`，整个推流监听 + trader 一起重建。

---

## 维护约定

新踩到的 LongBridge 限制 → 在这里加一节，附**最小复现条件**、**症状**、**应对策略**、**代码入口**、**测试守护**（如果加了 fake 限制就提一下，方便未来重构者别误删）。
