# 设计文档:Confirm / Skip 按钮 + 提交订单参数完备性校验

**日期**:2026-04-26
**分支**:`refactor-v2`
**作者**:txink + Claude

> **修订(2026-04-26 — 设计中调整):**
> 校验位置由 parser 阶段移到 **trader 阶段(订单提交的第一步)**,理由是 parser 的输出契约不包含 `quantity`(stock 多用 `position_size` 关键字,option 完全由 page_settings 决定),把"数量"卡在 parser 出口会和现实架构冲突;但是仍然应该在"展示按钮 / 自动下单"之前把"参数不齐"的信号过滤掉。新设计:trader 收到 `TASK_INSTRUCTION_READY` 后,**第一步**做参数完备性校验,**第二步**才检查 `auto_trade`。

## 1. 背景与动机

当前(`CardExpanded.tsx`)在 `auto_trade=false` 且任务停在 `INSTRUCTION_READY` 时,只渲染一枚单独的 "确认下单" 按钮,样式简陋且没有"取消"动作,紧凑卡片(`CardCompact`)完全没有可操作的入口。用户在关闭自动交易时,缺乏一致、网页风格的确认 / 取消 UI。

同时,parser 只要能产出一个合法的 `Instruction`(ticker + price 或 price_range)就把 task 推到 `INSTRUCTION_READY`。如果消息缺关键字段(BUY/SELL 方向、option strike、expiry 等),trader 阶段的兜底散落在多处条件分支里,且关闭 auto_trade 时缺字段的 task 也会出现确认按钮 — 这是不该出现的可操作 UI。

## 2. 目标

1. **参数完备性校验是订单提交阶段的第一步**,先于 `auto_trade` 检查 — 校验失败的 task 直接 SKIPPED + 中文原因,不会显示按钮。
2. **手动确认 / 取消是订单提交阶段的第二步**,只在 `auto_trade` 关闭且参数已完备时呈现。
3. UI 风格统一为网页化(B 样式 — 26 px 方形图标按钮,SVG 描边图标),紧凑形态与展开形态都支持。

## 3. 非目标

- 不修改 parser 输出契约 — `quantity` 在 stock 上仍可能为 `None`(由 `position_size` 表达),option 上则永远为 `None`(由 page_settings 解析)。
- 不引入二次确认弹窗 — 按钮即确认。
- Trader 阶段已有的兜底校验(白名单、orphan-stock 缺 qty、option 配置开关、价格偏离)保持不动 — 我们只在最前面**加**一道完备性闸门。

## 4. 整体设计

两条修改链路:

**A. 提交订单阶段的两步前置闸门(后端)**

```
parser → INSTRUCTION_READY → 发布 TASK_INSTRUCTION_READY
                                            │
                                trader._handle_instruction_ready
                                            │
                                            ▼
                          ① validate_for_submission(inst)
                                            │
                              ┌─────────────┴─────────────┐
                              ▼                           ▼
                      reason != None              reason is None
                      mark_skipped(reason)        ↓
                      publish STATUS_CHANGED      ② auto_trade?
                      └─→ 终态 SKIPPED              │
                                                   ├── false → reject_reason="…awaiting…"
                                                   │              publish STATUS_CHANGED
                                                   │              停留 INSTRUCTION_READY (前端显示按钮)
                                                   │
                                                   └── true → 继续:白名单 → qty → 偏离 → 下单
```

**B. 手动确认 / 取消(前端 + 一个新端点)**

```
auto_trade=false 且 task.status=INSTRUCTION_READY
   ↓
卡片 (紧凑形态在原状态 pill 列;展开形态在 解析指令 stage 下方) 渲染
<ConfirmActions> = [✓ confirm-icon-btn] [✗ cancel-icon-btn]
   │
   ├─ 点 ✓ → POST /api/tasks/{id}/confirm  (已有端点)
   │         临时翻 auto_trade=true 重发 INSTRUCTION_READY → trader 走通常流程下单
   │
   └─ 点 ✗ → POST /api/tasks/{id}/skip      (新端点)
            task.mark_skipped("用户手动取消") → 状态 SKIPPED
```

两条链都依赖一条状态机转换 `INSTRUCTION_READY → SKIPPED` — 已经存在,无需新增。

> Task 1 提前在状态机里也开放了 `PARSING → SKIPPED`(commit `30007c8`)。本次方案不再走 PARSING→SKIPPED;保留它属于"基础设施性"的小幅扩展,无副作用,后续若有 parser 阶段的硬错误想直接 SKIP 可以复用。

## 5. 后端详细设计

### 5.1 状态机

`backend/app/domain/status.py` 已在 Task 1 加入 `PARSING → SKIPPED`,本次设计不再使用,保留即可。`INSTRUCTION_READY → SKIPPED` 一直存在,trader 校验失败和手动取消都用这条边。

### 5.2 提交订单参数校验(在 trader 内)

新文件 `backend/app/broker/validation.py`:

```python
"""Pre-submission parameter completeness gate.

Runs as the FIRST step of trader._handle_instruction_ready, before the
auto_trade decision. Returns a Chinese reason string when *inst* lacks
the parser-level fields needed to make a sensible order, or None when
the instruction is OK to proceed.

This gate intentionally does NOT check `quantity`:
  - Stock: parser typically only emits position_size; concrete qty is
    resolved by trader using page_settings.tickers[ticker].trade_quantity.
  - Option: parser never emits quantity; it is fully derived from
    page_settings (option_buy_quantity / option_total_price_limit).

Stock instead requires either explicit `quantity > 0` OR a non-empty
`position_size` — evidence that the user expressed *some* quantity
intent. Option only requires the per-option-contract specifics; qty
resolution stays the trader's job.
"""
from __future__ import annotations

from app.domain.instruction import (
    Instruction,
    InstructionType,
    OptionInstruction,
    StockInstruction,
)


def validate_for_submission(inst: Instruction) -> str | None:
    missing: list[str] = []

    if inst.instruction_type not in (InstructionType.BUY, InstructionType.SELL):
        missing.append(f"方向(BUY/SELL,当前: {inst.instruction_type})")
    if inst.price is None and not inst.price_range:
        missing.append("价格")

    if isinstance(inst, StockInstruction):
        if not inst.ticker:
            missing.append("股票名")
        has_qty = inst.quantity is not None and inst.quantity > 0
        has_size = bool(inst.position_size)
        if not has_qty and not has_size:
            missing.append("数量(qty 或 position_size)")
    elif isinstance(inst, OptionInstruction):
        if not inst.ticker:
            missing.append("股票")
        if not inst.strike or inst.strike <= 0:
            missing.append("行权价")
        if inst.option_type not in ("CALL", "PUT"):
            missing.append("CALL/PUT")
        if not inst.expiry:
            missing.append("到期日")
        # NOTE: no quantity check for option — derived from page_settings.

    if missing:
        return "参数不齐: " + "、".join(missing)
    return None
```

### 5.3 接入 `trader.py`

`backend/app/broker/trader.py` 的 `_handle_instruction_ready` 在最开头(`payload` / `inst is None` 检查之后,在 auto_trade 检查之前)加:

```python
from app.broker.validation import validate_for_submission

# ...

async def _handle_instruction_ready(event: Event) -> None:
    payload = event.payload
    if not isinstance(payload, TaskPayload):
        return
    task: Task = payload.task
    inst: Instruction | None = task.instruction
    if inst is None:
        return

    # ① Parameter completeness gate — first step of order submission.
    reason = validate_for_submission(inst)
    if reason is not None:
        await _publish_skip(task, reason)
        return

    # ② auto_trade gate — second step.
    auto_trade_enabled = (
        auto_trade_getter() if auto_trade_getter is not None else config.auto_trade
    )
    if not auto_trade_enabled:
        task.reject_reason = "auto_trade disabled in config; awaiting manual confirmation"
        await bus.publish(Event(Topics.TASK_STATUS_CHANGED, TaskPayload(task)))
        return

    # ③ existing logic — symbol guard, type guard, page_settings, qty calc, deviation, submit.
    if not getattr(inst, "symbol", None):
        await _publish_skip(task, "instruction missing symbol")
        return
    # ... rest unchanged ...
```

旧版 trader 里的"`inst.instruction_type not in (BUY, SELL)`""price 缺失"等冗余兜底**保留**,作为深度防御 — 现在它们是不可达分支,但移除属于另一项工作。

### 5.4 Skip 端点

(不变)`backend/app/api/http.py` 新增 `POST /api/tasks/{id}/skip`:

```python
@router.post("/api/tasks/{task_id}/skip", response_model=TaskOut)
async def skip_task_endpoint(task_id: str) -> TaskOut:
    """Mark an INSTRUCTION_READY task as SKIPPED on user request."""
    async with session_scope(session_factory) as session:
        task = await repo.load_task(session, task_id)
    if task is None:
        raise HTTPException(404, detail="task not found")
    if task.status != Status.INSTRUCTION_READY:
        raise HTTPException(
            400,
            detail=f"task status must be INSTRUCTION_READY for skip, got: {task.status}",
        )
    task.mark_skipped("用户手动取消")
    await bus.publish(Event(Topics.TASK_STATUS_CHANGED, TaskPayload(task)))
    await bus.wait_idle(timeout=3.0)
    async with session_scope(session_factory) as session:
        refreshed = await repo.load_task(session, task_id)
    if refreshed is None:
        raise HTTPException(500, detail="task missing after skip")
    return task_to_out(refreshed)
```

## 6. 前端详细设计

(完全同前 — 不受后端校验位置变动影响。)

### 6.1 新组件 `<ConfirmActions>`

`frontend/src/components/Card/ConfirmActions.tsx`:

```tsx
import { useState } from "react";
import type { SyntheticEvent } from "react";
import { api, HttpError } from "../../api/http";
import { useTasksStore } from "../../stores/tasks";

export interface ConfirmActionsProps {
  taskId: string;
  variant: "compact" | "expanded";
}

export function ConfirmActions({ taskId, variant }: ConfirmActionsProps) {
  const [busy, setBusy] = useState<"confirm" | "skip" | null>(null);
  const [error, setError] = useState<string | null>(null);

  const run = async (kind: "confirm" | "skip") => {
    setBusy(kind);
    setError(null);
    try {
      const updated = kind === "confirm"
        ? await api.confirmTask(taskId)
        : await api.skipTask(taskId);
      useTasksStore.getState().upsertTask(updated);
    } catch (e) {
      const msg = e instanceof HttpError
        ? (typeof e.body === "object" && e.body && "detail" in e.body
            ? String((e.body as { detail: unknown }).detail)
            : e.message)
        : (e instanceof Error ? e.message : String(e));
      setError(msg);
    } finally {
      setBusy(null);
    }
  };

  const stop = (e: SyntheticEvent) => e.stopPropagation();

  return (
    <span
      className={`confirm-actions ${variant}`}
      onClick={stop}
      onKeyDown={stop}
    >
      <button
        type="button"
        className="ca-btn ca-confirm"
        title="确认下单"
        aria-label="确认下单"
        disabled={busy !== null}
        onClick={() => run("confirm")}
      >
        {busy === "confirm" ? <span className="ca-spinner" /> : (
          <svg viewBox="0 0 16 16" fill="none" stroke="currentColor"
               strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round">
            <polyline points="3 8 7 12 13 4" />
          </svg>
        )}
      </button>
      <button
        type="button"
        className="ca-btn ca-cancel"
        title="取消"
        aria-label="取消"
        disabled={busy !== null}
        onClick={() => run("skip")}
      >
        {busy === "skip" ? <span className="ca-spinner" /> : (
          <svg viewBox="0 0 16 16" fill="none" stroke="currentColor"
               strokeWidth="2.4" strokeLinecap="round">
            <line x1="4" y1="4" x2="12" y2="12" />
            <line x1="12" y1="4" x2="4" y2="12" />
          </svg>
        )}
      </button>
      {error && <span className="ca-err" title={error}>!</span>}
    </span>
  );
}
```

### 6.2 `CardCompact` 接入

新增 prop `autoTrade: boolean`。第 7 个 grid cell(原 `<StatusPill>`)条件渲染:

```tsx
const showConfirmActions =
  !autoTrade && status === "INSTRUCTION_READY" && instruction != null;

// ...
{showConfirmActions
  ? <ConfirmActions taskId={task.id} variant="compact" />
  : <StatusPill status={status} />
}
```

### 6.3 `CardExpanded` 替换

把现有的 `manual-confirm-row` 整段(60–78、159–171 行)替换为:

```tsx
{canManualConfirm && (
  <div className="confirm-actions-row">
    <ConfirmActions taskId={task.id} variant="expanded" />
    <span className="confirm-hint">auto_trade 已关闭 · 待人工确认</span>
  </div>
)}
```

### 6.4 `Card.tsx`

把 `autoTrade` 透传到 `CardCompact`。

### 6.5 `api/http.ts`

```ts
async skipTask(id: string): Promise<Task> {
  return request<Task>(`/api/tasks/${encodeURIComponent(id)}/skip`, { method: "POST" });
},
```

### 6.6 CSS

`Card.css` 新增,删除旧 `.manual-confirm-*`:(完整 CSS 见 plan 文档 Step 4E)

## 7. 数据流与时序

**Confirm 路径**

```
点击 ✓ → ConfirmActions 调 api.confirmTask
        → 后端临时翻 auto_trade=true,重发 TASK_INSTRUCTION_READY
        → trader: validate_for_submission ✓ → auto_trade=true → 走下单
        → 任务推进到 SUBMITTING / PENDING …
        → 返回 TaskOut → useTasksStore.upsertTask
        → CardCompact 重渲染:status 不再是 INSTRUCTION_READY,
          showConfirmActions=false → 按钮自动消失,换成 PENDING 状态 pill
```

**Skip 路径**

```
点击 ✗ → ConfirmActions 调 api.skipTask
        → 后端 mark_skipped("用户手动取消") + 发 TASK_STATUS_CHANGED
        → 返回 TaskOut → useTasksStore.upsertTask
        → CardCompact 重渲染:SKIPPED + reject_reason 已有现成渲染
```

**Validation-fail 路径**

```
parser → INSTRUCTION_READY → trader.validate_for_submission 失败
        → mark_skipped("参数不齐: …") + STATUS_CHANGED
        → 卡片直接终态 SKIPPED,不显示按钮(因为状态已不是 INSTRUCTION_READY)
```

## 8. 边界情况

| 场景 | 行为 |
|------|------|
| auto_trade ON,参数不齐 | trader 第一步直接 SKIPPED,不下单 — `validate` 在 `auto_trade` 之前 |
| auto_trade OFF,参数不齐 | trader 第一步直接 SKIPPED,卡片不显示按钮(状态非 INSTRUCTION_READY) |
| auto_trade OFF,参数完备 | trader 第一步过 → 第二步发现 auto_trade=off → 设 reject_reason + STATUS_CHANGED → 留在 INSTRUCTION_READY → 显示按钮 |
| 用户先点 confirm 再点 skip | confirm in-flight 时 skip 按钮 disabled,不并发 |
| confirm 后端报错 | 任务保留在 INSTRUCTION_READY,UI `.ca-err` 显示 detail,可重试 |
| skip 时 task 已被并发推进 | 后端 400,`.ca-err` 显示原因 |
| WS 推送和 HTTP 返回竞态 | upsertTask 幂等 |
| 紧凑行点按钮触发卡片展开 | `stopPropagation` 阻止冒泡 |

## 9. 测试计划

### 后端

- `tests/domain/test_status.py`:`PARSING → SKIPPED` 已加(Task 1 已完成)
- `tests/broker/test_validation.py`(**新**):`validate_for_submission` 各字段穷举
   - Stock 完备(qty)、stock 完备(position_size)、stock 缺 ticker / 缺 side / 缺 qty 和 size、stock 缺 price
   - Option 完备、option 缺 strike / 缺 expiry / 缺 CP / 缺 side / 缺 ticker / 缺 price
   - 注意:**不测**期权缺 quantity(本设计不卡 option qty)
- `tests/broker/test_trader.py`:补
   - 参数不齐(缺 side)→ task=SKIPPED + reject_reason 含 "参数不齐"
   - 参数齐 + auto_trade=false → task 留 INSTRUCTION_READY,reject_reason="auto_trade disabled..."
   - 参数齐 + auto_trade=true → 走原有下单流程
- `tests/api/test_http.py`:`test_skip_task_*` — 200 / 400 / 404

### 前端

(同前 — `ConfirmActions.test.tsx`、`CardCompact.test.tsx`、`CardExpanded.test.tsx`、`http.test.ts`)

### 端到端验证

`make dev` 起本地:

1. 关闭 auto_trade
2. 贴**完整**股票信号(带 position_size 关键字,如 `TSLL 26.5 加一半`,TSLL 在白名单)→ 紧凑行右侧出现 ✓✗ → 点 ✓ → PENDING
3. 再贴一条 → 点 ✗ → SKIPPED + reason="用户手动取消"
4. 贴**缺方向词**的股票信号(如 `TSLL 26.5`,只是观望)→ task SKIPPED + reject_reason="参数不齐: 方向…"(不显示按钮)
5. 期权同样跑一遍(完整:`AAPL 240C 0822 2.15 买` + 期权页设了 option_buy_quantity;缺 strike 等)

## 10. 提交计划

按依赖关系仍是 4 个 commit:

1. **chore(domain): allow PARSING → SKIPPED transition** ✅ 已完成 (`30007c8`)
2. **feat(broker): validate required fields before order submission** — 新文件 `app/broker/validation.py` + `trader.py` 接入 + 测试
3. **feat(api): POST /api/tasks/{id}/skip — manual cancel pre-submit** — 后端端点 + 测试 + OpenAPI 重生
4. **feat(card): confirm/skip icon buttons with web style** — 前端组件 + 接入 + CSS + .gitignore

## 11. 文件清单

**新增**
- ~~`backend/app/parser/validation.py`~~ → `backend/app/broker/validation.py`
- ~~`backend/tests/parser/test_validation.py`~~ → `backend/tests/broker/test_validation.py`
- `frontend/src/components/Card/ConfirmActions.tsx`
- `frontend/src/components/Card/ConfirmActions.test.tsx`

**修改**
- `backend/app/domain/status.py` ✅(Task 1 已完成)
- ~~`backend/app/parser/service.py`~~(本次方案不动 parser)
- `backend/app/broker/trader.py`(在 `_handle_instruction_ready` 顶部加 validation 闸门)
- `backend/app/api/http.py`(加 `/skip` 路由)
- `backend/tests/domain/test_status.py` ✅(Task 1 已完成)
- ~~`backend/tests/parser/test_service.py`~~(parser 不动,测试不需改)
- `backend/tests/broker/test_trader.py`(加 3 个用例)
- `backend/tests/api/test_http.py`(加 3 个 skip 用例)
- `frontend/src/components/Card/Card.tsx`
- `frontend/src/components/Card/CardCompact.tsx`
- `frontend/src/components/Card/CardCompact.test.tsx`
- `frontend/src/components/Card/CardExpanded.tsx`
- `frontend/src/components/Card/CardExpanded.test.tsx`
- `frontend/src/components/Card/Card.css`
- `frontend/src/api/http.ts`
- `frontend/src/api/http.test.ts`
- `.gitignore`

## 12. Out of scope / 后续

- 清理 trader 中已被新闸门覆盖的冗余兜底(symbol/instruction_type/price 那几条)
- confirm 端点目前依赖"临时翻 auto_trade=true 重发 event"的实现,虽 work 但有点 hacky;直接调用 trader 内部下单函数是另一项独立改动
- 二次确认(对话框 / 长按等)不在本期范围
