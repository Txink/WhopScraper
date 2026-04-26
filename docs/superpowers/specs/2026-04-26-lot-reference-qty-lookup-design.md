# 设计文档：基于历史 task 的 lot 引用数量查找

**日期**：2026-04-26
**分支**：`refactor-v2`
**作者**：txink + Claude

## 1. 背景与动机

stock 信号常见的"减仓 / 加仓 / 兑现"消息会**用价格回指上一笔交易**，而不显式给数量：

| 消息 | 解释 |
|---|---|
| `12.87减一半12.42的tsll` | 12.87 卖出 TSLL，数量 = 12.42 那笔买入的一半 |
| `12.32加了12.87卖出的tsll那部分` | 12.32 买回 TSLL，数量 = 12.87 那笔卖出的全部 |
| `87.4出一半夜盘85.65的hood` | 87.4 卖出 HOOD，数量 = 85.65 那笔买入的一半 |

当前 trader 的 stock 数量计算（`backend/app/broker/trader.py:184`）只看两条路径：

1. 白名单 stock：`base_qty = page_settings.tickers[ticker].trade_quantity`，再乘 `position_size_to_fraction(inst.position_size)`。
2. Orphan stock：用 `inst.quantity`，缺则 SKIPPED。

历史 lot 引用走不通这两条 —— 即便 parser 已经在 `StockInstruction.sell_quantity` 上写了 `"1/2"` / `"全部"` 等修饰语（见 `app/parser/stock_parser.py:1119+`），`sell_quantity` 字段**今天没有任何下游消费方**。结果就是 4 月 23 日一批"减仓"消息被当作"按默认仓位 × 1.0 / × 1/2"下单，数量错误（详见 issue 列表 `post_1CaKfh / 1CaL2H / 1CaLhN / 1CaLu8 / 1CaLyF`）。

## 2. 目标

1. trader 在算 stock 数量时，新增一条"lot 引用"路径：当 instruction 同时带 `referenced_lot_price` 和 `sell_quantity` 时，去 DB 找历史反向交易并以其 `tasks.quantity` 为基数。
2. lot 引用未命中时，**完全保留现有兜底**（默认仓位 × `position_size`），不破坏现状。
3. trader 仍是事件驱动纯逻辑，DB 查询通过显式注入的 `TaskQueryRepo` 完成，便于测试。

## 3. 非目标

- **不动 parser**。本设计假设 parser 后续会在 `Instruction` 上正确填 `referenced_lot_price`；parser 改造另起一条线（PARSE_ERROR 类与修饰语提取 bug 单独治理）。
- **不动 option 路径**。当前没有"出 X 那批 option"的引用形态，YAGNI。
- **不引入实际持仓 / 成交累计追踪**。lot 数量取自 `tasks.quantity`（计划量），不查 push_events。
- **不显式追踪 lot 消耗**。`"剩下一半"` 等同 `"1/2"` 处理，不做"原 lot 减去已卖部分"的累计推算。

## 4. 决策汇总

设计时确认的 7 个核心决策，按顺序记录以便日后回溯：

| # | 决策点 | 选择 | 理由 |
|---|---|---|---|
| 1 | lot 数量的真值来源 | A：`tasks.quantity`（计划量） | 单次查询，不依赖 push 时序 |
| 2 | 方向过滤 | A：严格反向（SELL 引用 BUY、BUY 引用 SELL） | 语义清晰，避免误匹配同向单 |
| 3 | 时间窗口 | B：硬编码 7 天，未来挪到 `PageSettings` | 跨日覆盖足够，YAGNI 暂不放配置 |
| 4 | 状态过滤 | A：`order_id IS NOT NULL`（含 CANCELLED） | 与"计划量"语义同源，最广 |
| 5 | 分数语义 | A：`"剩下一半"` 当作 `0.5` | 不做 lot 消耗追踪，简单 |
| 6 | 未命中兜底 | B：回退默认仓位（当前行为） | 保底不卡死，不会比今天更差 |
| 7 | 价格匹配 | A：精确（±0.0001）+ 最近一笔 | 简单可预测；用户简写无法匹配时走兜底 |

## 5. 数据流与模块边界

### 5.1 domain 层：`Instruction` 字段扩展

`backend/app/domain/instruction.py`：

```python
@dataclass
class Instruction:
    instruction_type: InstructionType
    price: float | None
    price_range: tuple[float, float] | None
    quantity: int | None
    position_size: str | None
    stop_loss_price: float | None
    take_profit_price: float | None
    context_source: ContextSource | None
    parser_notes: list[str] = field(default_factory=list)
    referenced_lot_price: float | None = None  # ← 新增
```

`StockInstruction.sell_quantity` 保持不变，但**首次被 trader 消费**。

API schemas 层（`app/api/schemas.py:61` 等）相应同步加字段；存储层（`payload_json`）天然兼容（已是 JSON blob）。

### 5.2 helper：`sell_quantity_to_fraction`

新增到 `backend/app/whop/page_settings.py`（紧邻 `position_size_to_fraction`）：

```python
_SELL_FRACTION_MAP: dict[str, float] = {
    "1/2": 0.5,
    "1/3": 1 / 3,
    "1/4": 0.25,
    "2/3": 2 / 3,
    "3/4": 0.75,
    "全部": 1.0,
    "剩下": 1.0,
    "剩下一半": 0.5,  # 决策 5：等同 1/2
}


def sell_quantity_to_fraction(s: str | None) -> float:
    """parser 解出的 sell_quantity → 数量倍数。
    未识别 → 1.0 + warning（与 position_size_to_fraction 一致）。
    """
```

### 5.3 storage 层：`TaskQueryRepo` 接口（async）

`backend/app/storage/repo.py` 旁新增 `Protocol`。注意 storage 层全部是 `AsyncSession`（参见 `storage/listeners.py` 的 `async_sessionmaker[AsyncSession]` 模式），所以 repo 也是 async 的：

```python
class TaskQueryRepo(Protocol):
    async def find_recent_task_by_ref(
        self,
        *,
        ticker: str,
        side: InstructionType,         # 反向：SELL 引用时传 BUY
        price: float,
        before: datetime,              # 一般是当前 task.created_at
        window_hours: int = 24 * 7,
    ) -> int | None:
        """命中返回 tasks.quantity；未命中 None。"""
```

具体实现是绑定到 `async_sessionmaker[AsyncSession]` 的小类，每次调用开/关一个 session：

```python
class SqlTaskQueryRepo:
    def __init__(self, factory: async_sessionmaker[AsyncSession]) -> None:
        self._factory = factory

    async def find_recent_task_by_ref(self, **kw: Any) -> int | None:
        async with self._factory() as session:
            return await _find_recent_task_by_ref(session, **kw)
```

底层模块函数 `_find_recent_task_by_ref(session, ...)` 跟现有 `load_task / list_tasks` 同风格放在 `app/storage/repo.py`。SQL 语义：

```sql
SELECT quantity FROM tasks
WHERE ticker = :ticker
  AND side = :side
  AND ABS(price - :price) < 0.0001
  AND order_id IS NOT NULL
  AND created_at <  :before
  AND created_at >= :before - :window_hours hours
ORDER BY created_at DESC
LIMIT 1;
```

注：`tasks.side` 列存字符串（`"BUY"` / `"SELL"`），实现内部用 `side.value` 绑定。

### 5.4 trader 接线

`register_trader(...)` 增加可选参数 `task_query_repo: TaskQueryRepo | None = None`。`app/main.py` 启动时构造 `SqlTaskQueryRepo(session_factory)` 注入；测试可注入 fake 或 None（None 时直接走兜底）。

## 6. trader 内的数量决策树

替换 `trader.py:184-196` 的 stock 分支（注意调用是 `await`，`task.created_at` 一律 UTC）：

```python
if isinstance(inst, StockInstruction):
    ticker_upper = (inst.ticker or "").upper()
    if page_settings is not None and page_settings.tickers is not None:
        computed_qty = await _qty_for_whitelisted_stock(
            inst, ticker_upper, page_settings,
            task_query_repo=task_query_repo,
            now=task.created_at,
        )
    else:
        computed_qty = inst.quantity or 0
        if computed_qty <= 0:
            await _publish_skip(task, "orphan stock task missing instruction.quantity")
            return
```

新拆出的 helper（async）：

```python
async def _qty_for_whitelisted_stock(
    inst: StockInstruction,
    ticker_upper: str,
    page_settings: PageSettings,
    *,
    task_query_repo: TaskQueryRepo | None,
    now: datetime,
) -> int:
    # ① lot 引用路径：三个前提全满足才走
    if (
        inst.referenced_lot_price is not None
        and inst.sell_quantity is not None
        and task_query_repo is not None
    ):
        opposite = (
            InstructionType.BUY if inst.instruction_type == InstructionType.SELL
            else InstructionType.SELL
        )
        prior_qty = await task_query_repo.find_recent_task_by_ref(
            ticker=ticker_upper,
            side=opposite,
            price=inst.referenced_lot_price,
            before=now,
            window_hours=24 * 7,
        )
        if prior_qty is not None:
            fraction = sell_quantity_to_fraction(inst.sell_quantity)
            qty = max(int(prior_qty * fraction), 1)
            logger.info(
                "Trader: lot ref @%.4f qty=%d × %s → %d (ticker=%s)",
                inst.referenced_lot_price, prior_qty, inst.sell_quantity, qty, ticker_upper,
            )
            return qty
        logger.info(
            "Trader: no prior %s within 7d for %s @%.4f, falling back to default qty",
            opposite.value, ticker_upper, inst.referenced_lot_price,
        )

    # ② 兜底路径：当前白名单 × position_size 行为，不变
    base_qty = page_settings.tickers[ticker_upper].trade_quantity
    fraction = position_size_to_fraction(inst.position_size)
    return max(int(base_qty * fraction), 1)
```

要点：

1. **三前提**（`referenced_lot_price` / `sell_quantity` / `task_query_repo` 全非 None）才进 lot 路径；任一缺失走兜底，行为不变。
2. **未命中也走兜底**，不阻塞下单 —— 决策 6。
3. **下限 1 股**，与兜底一致。
4. **观测性**：命中和未命中分别打 INFO 日志，复用现有 trader 日志风格（参见近期 `9e5e7ec` 的 push 重试 INFO）。
5. **option 分支不动**。

## 7. 测试策略

### 7.1 trader 集成测试 — `backend/tests/broker/test_trader_lot_lookup.py`（新文件）

`tests/broker/_fakes.py` 新增 `FakeTaskQueryRepo`：实现 async `find_recent_task_by_ref`，按 `(ticker, side, price)` 元组键返回预置 qty。测试用 `FakeBrokerClient` + `FakeTaskQueryRepo` 通过事件总线驱动，断言 `submitted_orders[0]["quantity"]`。

| 用例 | 输入 | 预置 | 期望下单 qty |
|---|---|---|---|
| happy: 减一半 | SELL TSLL @12.87，ref=12.42，sq=`"1/2"` | BUY TSLL @12.42 qty=4000 | **2000** |
| happy: 加回那部分 | BUY TSLL @12.32，ref=12.87，sq=`"全部"` | SELL TSLL @12.87 qty=2000 | **2000** |
| 未命中 → 兜底 | SELL HOOD @87.4，ref=85.65，sq=`"1/2"` | repo 无匹配 | `default_qty × position_size_to_fraction(None)` |
| 同向被忽略 | SELL @12.87，ref=12.42 | 12.42 是 SELL（同向） | 兜底 |
| 窗口外 | ref=12.42 | 12.42 BUY 在 8 天前 | 兜底 |
| 价格非精确 | ref=12.4 | 实际 BUY @12.42 | 兜底 |
| `task_query_repo=None` | 任何带引用的指令 | — | 兜底，不报错 |
| `sell_quantity=None` | 只有 ref，无 fraction | — | 兜底 |
| 多匹配取最近 | ref=12.42 | 旧 BUY qty=2000 + 新 BUY qty=4000 | × 1/2 = **2000** |
| `sell_quantity="剩下一半"` | sq=`"剩下一半"` | BUY @11.73 qty=4000 | **2000**（决策 5） |
| 未识别 sell_quantity | sq=`"一点点"` | BUY qty=2000 | 2000（fraction=1.0 + warning） |

### 7.2 lot_lookup repo 单元测试 — `backend/tests/storage/test_task_query_repo.py`（新文件）

打到现有 in-memory SQLite fixture（与 `tests/storage/test_repo.py` 同源），覆盖：

- 多笔同价、不同方向 → 取反向最近一笔
- `order_id IS NULL`（PARSE_ERROR / SKIPPED / SUBMIT_FAILED）不计入
- 跨窗口边界（恰好 7 天 vs 7 天 1 秒）
- `before` 严格 `<`：自身不会被自己匹配

### 7.3 helper 单元测试 — `backend/tests/whop/test_page_settings.py`

向现有文件追加 `sell_quantity_to_fraction` 表驱动测试：所有 `_SELL_FRACTION_MAP` 键、None、未识别字符串。

## 8. 兼容性与滚动落地

- **schema 兼容**：`Instruction.referenced_lot_price` 默认 `None`，不影响存量 task 的 `payload_json` 反序列化（dataclass 字段缺失时回落默认）。
- **API 契约**：`app/api/schemas.py` 的 Pydantic 模型新增同名 optional 字段；前端无强制改动需求（`OrderSubmit` 卡片不展示该字段；可后续在展开卡片里加一行 `引用 @12.42` 提示，本设计不强制）。
- **没有 parser 改造之前**，trader 行为与今天**完全等价** —— `referenced_lot_price` 永远是 None，三前提不全，走兜底。这意味着这次 PR **可以独立合入 main 而不改变任何用户行为**，作为后续 parser 改造的基础设施。
- **回滚**：trader 路径完全开关化（取决于 `referenced_lot_price` 是否非 None），无需 feature flag；如发现 lot 路径误判可直接在 parser 层不写该字段即可全局禁用。

## 9. 后续工作（不在本 spec 内）

- parser 改造：从消息中正确抽出 `referenced_lot_price` 与修饰语，覆盖 4 月 23 日 issue 列表里的 4 条 PARSE_ERROR 和 2 条修饰语解析 bug。
- `PageSettings.lot_lookup_window_hours`：把 7 天阈值挪到 page 配置。
- `LotReference` 结构化对象（替换 `referenced_lot_price` + `sell_quantity` 两字段）：等遇到 option 引用或多 lot 复合引用再说。
- UI 展示：在展开卡片的"提交订单"行展示 `引用 @12.42 × 1/2 → 2000` 提示，便于用户核验。
