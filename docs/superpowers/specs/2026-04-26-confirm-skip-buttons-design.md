# 设计文档:Confirm / Skip 按钮 + 解析参数完备性校验

**日期**:2026-04-26
**分支**:`refactor-v2`
**作者**:txink + Claude

## 1. 背景与动机

当前(`CardExpanded.tsx`)在 `auto_trade=false` 且任务停在 `INSTRUCTION_READY` 时,只渲染一枚单独的 "确认下单" 按钮,样式简陋且没有"取消"动作,紧凑卡片(`CardCompact`)完全没有可操作的入口。用户在关闭自动交易时,缺乏一致、网页风格的确认 / 取消 UI。

与此同时,parser 现在只要能产出一个合法的 `Instruction`(ticker + price 或 price_range)就把 task 推到 `INSTRUCTION_READY`。`quantity`、`instruction_type`(BUY/SELL/CLOSE/MODIFY)、option 的 strike/expiry 等关键参数即使缺失,也会进入 trader 阶段,由 trader 用各种条件分支兜底。**这是 trader 的职责越界**:解析阶段的输出契约本应保证下游可下单的最小参数集。

## 2. 目标

1. **参数完备性校验是 parser 阶段的最终关卡**,与自动交易完全解耦。校验失败 → 任务 `SKIPPED` + 明确原因。
2. **手动确认 / 取消是订单提交阶段的第一关**,只在 auto_trade 关闭时呈现。
3. UI 风格统一为网页化(B 样式 — 26px 方形图标按钮,SVG 描边图标),紧凑形态与展开形态都支持。

## 3. 非目标

- 不在本次范围内重构 trader 里冗余但无害的兜底校验(symbol/instruction_type/quantity/price 那几条 guard)。
- 不修改 parser 里 stock_parser / option_parser 的解析逻辑 — 只在解析后加一道字段完备性的"出口校验"。
- 不引入二次确认弹窗 — 按钮即确认。

## 4. 整体设计

两条独立的修改链路:

**A. 解析参数完备性(后端为主)**

```
message → parser → Instruction (任意完备性)
                         │
                         ▼
              validate_for_submission(inst)
                         │
            ┌────────────┴────────────┐
            ▼                         ▼
       reason != None           reason is None
       task.mark_skipped(r)     task.attach_instruction(inst)
       publish STATUS_CHANGED   publish TASK_INSTRUCTION_READY
       └─→ 终态 SKIPPED              └─→ 进入 trader 流程
```

**B. 手动确认 / 取消(前端 + 一个新端点)**

```
auto_trade = false 且 task.status = INSTRUCTION_READY
   ↓
卡片(紧凑形态在原状态 pill 列;展开形态在 解析指令 stage 下方)渲染
<ConfirmActions> = [✓ confirm-icon-btn] [✗ cancel-icon-btn]
   │
   ├─ 点 ✓ → POST /api/tasks/{id}/confirm  (已有端点)
   │         临时翻 auto_trade=true 重发 INSTRUCTION_READY → trader 下单
   │
   └─ 点 ✗ → POST /api/tasks/{id}/skip      (新端点)
            task.mark_skipped("用户手动取消") → 状态 SKIPPED
```

两条链都依赖一条新的状态机转换:`PARSING → SKIPPED`。`INSTRUCTION_READY → SKIPPED` 已有,无需修改。

## 5. 后端详细设计

### 5.1 状态机扩展

`backend/app/domain/status.py`:

```python
Status.PARSING: frozenset({Status.PARSE_ERROR, Status.INSTRUCTION_READY, Status.SKIPPED}),
```

仅新增 `SKIPPED` 一个目标,其他转换不动。`SKIPPED` 仍是终态。

### 5.2 Parser 出口校验

新文件 `backend/app/parser/validation.py`:

```python
from app.domain.instruction import (
    Instruction, InstructionType, OptionInstruction, StockInstruction,
)

def validate_for_submission(inst: Instruction) -> str | None:
    """检查 parser 产出的 instruction 是否具备下单所需的最小参数集。

    返回缺失字段的中文说明(便于直接进 reject_reason),完备返回 None。
    """
    missing: list[str] = []

    # 通用必填
    if inst.instruction_type not in (InstructionType.BUY, InstructionType.SELL):
        missing.append(f"方向(BUY/SELL,当前: {inst.instruction_type})")
    if inst.quantity is None or inst.quantity <= 0:
        missing.append("数量")
    if inst.price is None and not inst.price_range:
        missing.append("价格")

    # Stock 子类
    if isinstance(inst, StockInstruction):
        if not inst.ticker:
            missing.append("股票名")
    # Option 子类
    elif isinstance(inst, OptionInstruction):
        if not inst.ticker:
            missing.append("股票")
        if not inst.strike or inst.strike <= 0:
            missing.append("行权价")
        if inst.option_type not in ("CALL", "PUT"):
            missing.append("CALL/PUT")
        if not inst.expiry:
            missing.append("到期日")

    if missing:
        return "参数不齐: " + "、".join(missing)
    return None
```

`backend/app/parser/service.py` 在 `_handle_message_received` 末尾,把:

```python
if resolved is not None:
    task.attach_instruction(resolved)
    await bus.publish(Event(Topics.TASK_INSTRUCTION_READY, TaskPayload(task)))
else:
    task.mark_parse_failed("无法解析为交易指令")
    await bus.publish(Event(Topics.TASK_PARSE_FAILED, TaskPayload(task)))
```

替换为:

```python
if resolved is None:
    task.mark_parse_failed("无法解析为交易指令")
    await bus.publish(Event(Topics.TASK_PARSE_FAILED, TaskPayload(task)))
    return

reason = validate_for_submission(resolved)
if reason is not None:
    # 把已解析的 instruction 仍挂在 task 上,供前端展示部分参数 + reject_reason
    task.instruction = resolved
    if isinstance(resolved, OptionInstruction):
        task.type = "option"
    elif isinstance(resolved, StockInstruction):
        task.type = "stock"
    task.mark_skipped(reason)
    await bus.publish(Event(Topics.TASK_STATUS_CHANGED, TaskPayload(task)))
    return

task.attach_instruction(resolved)
await bus.publish(Event(Topics.TASK_INSTRUCTION_READY, TaskPayload(task)))
```

注意点:
- 校验失败时 task 仍处于 PARSING 状态(没调用 `attach_instruction`),所以转换 `PARSING → SKIPPED` 必须先在状态机里允许(§5.1)。
- 校验失败发 `TASK_STATUS_CHANGED` 而非 `TASK_PARSE_FAILED`,语义上更准 — 我们已经成功解析,只是参数不齐。trader 不订阅 STATUS_CHANGED,因此不会收到这条消息。
- 校验失败时仍把 `instruction` 挂上,这样前端展开卡片可以看到"已解析的部分参数 + 缺什么"的现状。

### 5.3 Skip 端点

`backend/app/api/http.py` 新增:

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

模式与现有 `confirm_task_endpoint` 对齐。现有 `cancel_task_endpoint`(撤销 broker 订单)语义不变。

## 6. 前端详细设计

### 6.1 新组件 `<ConfirmActions>`

`frontend/src/components/Card/ConfirmActions.tsx`:

```tsx
import { useState } from "react";
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
            ? String((e.body as { detail: unknown }).detail) : e.message)
        : (e instanceof Error ? e.message : String(e));
      setError(msg);
    } finally {
      setBusy(null);
    }
  };

  const stop = (e: React.SyntheticEvent) => e.stopPropagation();

  return (
    <span
      className={`confirm-actions ${variant}`}
      onClick={stop}
      onKeyDown={stop}
    >
      <button
        className="ca-btn ca-confirm"
        title="确认下单"
        aria-label="确认下单"
        disabled={busy !== null}
        onClick={() => run("confirm")}
      >
        {busy === "confirm" ? <span className="ca-spinner" /> : (
          <svg viewBox="0 0 16 16" fill="none" stroke="currentColor"
               strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round">
            <polyline points="3 8 7 12 13 4"/>
          </svg>
        )}
      </button>
      <button
        className="ca-btn ca-cancel"
        title="取消"
        aria-label="取消"
        disabled={busy !== null}
        onClick={() => run("skip")}
      >
        {busy === "skip" ? <span className="ca-spinner" /> : (
          <svg viewBox="0 0 16 16" fill="none" stroke="currentColor"
               strokeWidth="2.4" strokeLinecap="round">
            <line x1="4" y1="4" x2="12" y2="12"/>
            <line x1="12" y1="4" x2="4" y2="12"/>
          </svg>
        )}
      </button>
      {error && <span className="ca-err" title={error}>!</span>}
    </span>
  );
}
```

`stopPropagation` 必要 — 紧凑行整体可点击展开,按钮点击不能冒泡。

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

grid 列宽不变(占 104px),按钮组居中。

### 6.3 `CardExpanded` 替换

删除现有 60–78 行的 `confirming/confirmError` state 和 `handleConfirm`,删除 159–171 行的 `manual-confirm-row`,替换为:

```tsx
{canManualConfirm && (
  <div className="confirm-actions-row">
    <ConfirmActions taskId={task.id} variant="expanded" />
    <span className="confirm-hint">auto_trade 已关闭 · 待人工确认</span>
  </div>
)}
```

`canManualConfirm` 表达式不变。

### 6.4 `Card.tsx`

把 `autoTrade` 透传到 `CardCompact`(原本只透给了 expanded)。

### 6.5 `api/http.ts`

```ts
async skipTask(id: string): Promise<Task> {
  return request<Task>(`/api/tasks/${encodeURIComponent(id)}/skip`, { method: "POST" });
},
```

### 6.6 CSS

`Card.css` 新增,删除旧 `.manual-confirm-*`:

```css
.confirm-actions {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}
.confirm-actions.compact { justify-content: center; }

.ca-btn {
  width: 24px; height: 24px;
  display: inline-flex; align-items: center; justify-content: center;
  border: 1px solid var(--line-strong);
  border-radius: 4px;
  background: var(--bg-1);
  cursor: pointer; padding: 0;
  transition: border-color 120ms, background 120ms, color 120ms;
}
.ca-btn svg { width: 12px; height: 12px; }
.ca-btn:disabled { opacity: 0.5; cursor: default; }

.ca-confirm { color: var(--ok); }
.ca-confirm:hover:not(:disabled) {
  border-color: var(--ok);
  background: rgba(61, 214, 140, 0.10);
}
.ca-cancel { color: var(--err); }
.ca-cancel:hover:not(:disabled) {
  border-color: var(--err);
  background: rgba(239, 91, 91, 0.08);
}

.ca-spinner {
  width: 10px; height: 10px;
  border: 1.5px solid currentColor;
  border-top-color: transparent;
  border-radius: 50%;
  animation: ca-spin 0.7s linear infinite;
}
@keyframes ca-spin { to { transform: rotate(360deg); } }

.ca-err {
  color: var(--err);
  font-family: var(--font-mono);
  font-size: 11px;
  cursor: help;
  margin-left: 2px;
}

.confirm-actions-row {
  margin-top: 8px;
  display: flex; align-items: center; gap: 12px;
}
.confirm-hint {
  color: var(--fg-3);
  font-size: 11px;
}
```

## 7. 数据流与时序

**Confirm 路径**

```
点击 ✓ → ConfirmActions 调 api.confirmTask
        → 后端临时翻 auto_trade=true,重发 TASK_INSTRUCTION_READY
        → trader 收到,正常下单流程,task 状态推进到 SUBMITTING / PENDING …
        → 返回 TaskOut → useTasksStore.upsertTask
        → CardCompact 重渲染:status 不再是 INSTRUCTION_READY,
          showConfirmActions=false → 按钮自动消失,换成 PENDING 状态 pill
        → 后续 WS 推 task.status_changed,upsertTask 幂等覆盖
```

**Skip 路径**

```
点击 ✗ → ConfirmActions 调 api.skipTask
        → 后端 mark_skipped("用户手动取消") + 发 TASK_STATUS_CHANGED
        → 返回 TaskOut → useTasksStore.upsertTask
        → CardCompact 重渲染:status=SKIPPED,
          showConfirmActions=false → 按钮消失,换成 SKIPPED 状态 pill
          (compact 行 details 列已有现成的 reject_reason 渲染)
```

## 8. 边界情况

| 场景 | 行为 |
|------|------|
| auto_trade ON,parser 校验失败 | 任务 SKIPPED,trader 不收到 INSTRUCTION_READY,不下单 |
| auto_trade OFF,parser 校验失败 | 任务 SKIPPED,卡片不显示按钮(条件不满足) |
| auto_trade OFF,parser 校验通过 | INSTRUCTION_READY,显示 confirm/skip |
| 用户先点 confirm 再点 skip | confirm in-flight 时 skip 按钮 disabled,不会并发 |
| confirm 后端报错 | 任务保留在 INSTRUCTION_READY,UI `.ca-err` 显示 detail,可重试 |
| skip 时 task 已被并发推进(例如恰好被 trader 拿走) | 后端 400,`.ca-err` 显示原因 |
| WS 推送和 HTTP 返回竞态 | upsertTask 幂等,React 渲染最新 state |
| 紧凑行点按钮触发卡片展开 | `stopPropagation` 阻止冒泡 |

## 9. 测试计划

### 后端

- `tests/domain/test_status.py`:`PARSING → SKIPPED` 合法
- `tests/parser/test_validation.py`(**新**):各字段单独缺失 / 全齐的全排列覆盖
- `tests/parser/test_service.py`:补"缺数量 → SKIPPED + 不发 INSTRUCTION_READY"用例(spy `bus.publish`)
- `tests/parser/test_snapshot_regression.py`:跑一次,如果挂了同步快照
- `tests/api/test_http.py`:`test_skip_task_*` — 200 / 400(状态不对)/ 404

### 前端

- `ConfirmActions.test.tsx`(**新**):点击调对应 API、loading 显示 spinner、错误显示、stopPropagation 验证
- `CardCompact.test.tsx`:autoTrade=false + READY → 按钮替代 pill;其他情况 pill
- `CardExpanded.test.tsx`:把原 "确认下单" 测试改成测 ConfirmActions

### 端到端验证

`make dev` 起本地:

1. 关闭 auto_trade
2. 贴**完整**股票信号 → 紧凑行右侧出现 ✓✗ → 点 ✓ → PENDING
3. 再贴一条 → 点 ✗ → SKIPPED + reason="用户手动取消"
4. 贴**缺数量**的股票信号 → 卡片直接 SKIPPED + reject_reason="参数不齐: 数量"(不显示按钮)
5. 期权同样跑一遍(完整 / 缺 strike / 缺 expiry 各一次)

## 10. 提交计划

按依赖关系拆 4 个 commit 便于 review:

1. **chore(domain): allow PARSING → SKIPPED transition**
   `status.py` + `test_status.py`
2. **feat(parser): validate required fields before INSTRUCTION_READY**
   `validation.py` + `service.py` 调用 + parser 测试
3. **feat(api): POST /api/tasks/{id}/skip — manual cancel pre-submit**
   后端端点 + 测试
4. **feat(card): confirm/skip icon buttons with web style**
   前端组件 + 接入 + CSS + 测试 + `.gitignore` 加 `.superpowers/`

依赖:1 → 2;3、4 独立。

## 11. 文件清单

**新增**
- `backend/app/parser/validation.py`
- `backend/tests/parser/test_validation.py`
- `frontend/src/components/Card/ConfirmActions.tsx`
- `frontend/src/components/Card/ConfirmActions.test.tsx`

**修改**
- `backend/app/domain/status.py`
- `backend/app/parser/service.py`
- `backend/app/api/http.py`
- `backend/tests/domain/test_status.py`
- `backend/tests/parser/test_service.py`
- `backend/tests/parser/test_snapshot_regression.py`(如挂)
- `backend/tests/api/test_http.py`
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

- 清理 trader 中已被 parser 校验覆盖的冗余 guard
- confirm 端点目前依赖"临时翻 auto_trade=true 重发 event"的实现策略,虽 work 但有点 hacky;改为直接调用 trader 内部函数是另一项独立改动
- 二次确认(对话框 / 长按等)不在本期范围
