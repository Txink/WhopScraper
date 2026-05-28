# 信号卡片解析标注按钮 — 设计文档

- 日期：2026-05-29
- 状态：已通过设计评审，待写实现计划

## 目标

给正股/期权/解析失败的消息卡片右下角加一排标注按钮，用于人工标注解析器的输出质量：

1. **✓ 解析正确**：标记这条消息的解析结果正确；可重复点击取消。
2. **✎ 校正**：标记解析错误，点击弹窗输入正确的指令信息（ticker / price / quantity / action，期权另加 strike / expiry / option_type）。

**用途：纯标注 / 评测数据。** 标注只用于以后评估和改进解析器，**不影响**已下的单、持仓追踪或任何交易逻辑。

## 关键约束

- **解析失败卡（PARSE_ERROR）有 `tasks` 行但没有 `instructions` 行**——解析失败就不产生 instruction。因此标注数据不能存进 `instructions` 表，必须以 `task_id` 为键独立存储，三种卡片才能统一处理。
- 每条消息 1:1 对应一个 task（`messages` 与 `tasks` 共享主键），所以 `task_id` 是稳定可用的标注键。

## 标注状态模型（互斥三态）

一条消息只有一个标注状态：

| 状态 | 存储表现 |
|---|---|
| 未标注 | `instruction_labels` 无该 task_id 行 |
| 解析正确 | 行存在，`verdict = "correct"`，无 corrected_payload |
| 已校正 | 行存在，`verdict = "corrected"`，有 corrected_payload |

状态转移：

- 未标注 → 点「解析正确」→ correct（PUT）
- 未标注 → 「校正」填写保存 → corrected（PUT）
- correct → 再点「解析正确」→ 未标注（DELETE）
- correct → 「校正」保存 → corrected（PUT，覆盖）
- corrected → 点「解析正确」→ correct（PUT，清除 corrected_payload）
- corrected → 「校正」→ 用现有 corrected_payload 预填后编辑

## 后端

### 新表 `instruction_labels`（`backend/app/storage/schema.py`）

| 列 | 类型 | 说明 |
|---|---|---|
| `task_id` | String | PK + FK → `tasks.id`，`ON DELETE CASCADE`（删 task 时一起删标注）|
| `verdict` | String | `"correct"` \| `"corrected"` |
| `corrected_payload` | JSON, nullable | 仅 corrected 时有，结构见下 |
| `updated_at` | DateTime(tz) | 最后标注时间 |

`corrected_payload` 结构：

```json
{
  "type": "stock" | "option",
  "ticker": "AAPL",
  "price": 188.0,
  "quantity": 50,
  "action": "BUY",          // BUY | SELL | CLOSE | MODIFY
  "strike": 190.0,          // 仅 option
  "expiry": "2026-06-19",   // 仅 option
  "option_type": "CALL"     // 仅 option：CALL | PUT
}
```

### Pydantic schema

- `InstructionLabelOut`：`verdict` / `corrected_payload` / `updated_at`。
- 输入：`PUT` 端点接收 `{ verdict, corrected_payload? }`。corrected_payload 用结构化 schema 校验上面的字段集合。

### 嵌进 `TaskSummaryOut`

- 给 `TaskSummaryOut`（以及 `TaskOut`，如端点返回完整 task）加 `label: InstructionLabelOut | None`，让列表加载后卡片直接能显示当前三态，无需额外请求。
- repo 的 task 列表 / 详情查询需 `LEFT JOIN instruction_labels`。
- **字段转发注意**：新增 `*Out` 字段后必须 grep 所有手工构造 `TaskSummaryOut(...)` / `TaskOut(...)` 的地方补上该字段，而不只是 `model_validate` 路径。

### API 端点（沿用 confirm/skip「返回更新后 TaskOut」风格）

- `PUT /api/tasks/{task_id}/label`，body `{ verdict, corrected_payload? }` — upsert，返回更新后的 `TaskOut`。
- `DELETE /api/tasks/{task_id}/label` — 清除该 task 的标注（回到未标注），返回更新后的 `TaskOut`。

### repo 方法

- `set_label(task_id, verdict, corrected_payload)` — upsert。
- `clear_label(task_id)` — 删除行。
- task 查询中 join 并填充 `label`。

## 前端

### domain-types / api

- `domain-types.ts`：`export type InstructionLabel = components["schemas"]["InstructionLabelOut"];`
- `api/http.ts`：`setTaskLabel(id, body)` → PUT；`clearTaskLabel(id)` → DELETE。两者返回更新后的 `Task`。

### `LabelActions.tsx`（放 `frontend/src/components/Card/`，与 `ConfirmActions` 并列）

右下角按钮排，渲染在卡片展开详情底部：

- **✓ 解析正确**：`verdict === "correct"` 时实心高亮。点击逻辑：
  - 未标注 / corrected → `setTaskLabel(id, { verdict: "correct" })`
  - 已是 correct → `clearTaskLabel(id)`（取消）
- **✎ 校正**：打开 `LabelCorrectionDialog`；`verdict === "corrected"` 时高亮提示已有校正。
- 按钮排自身的点击需 `stopPropagation`，避免触发卡片折叠（参照 `ConfirmActions` 的 `confirm-pair` 处理）。

> **实现决策（plan 阶段补充）**：label 显示状态放进 tasks store 的 `labelsByTask: Record<task_id, InstructionLabel>` map（与现有 `pushEventsByTask` 同构），`LabelActions` 从该 map 读取，**不直接读 task 对象上的 `label`**。原因：WS 广播走 `task_to_out(内存 task)`，其 `label` 恒为 `null`，而前端 `upsertTask` 是整条替换——若直接读 task.label，一次 WS 推送就会清掉已显示的标注。`labelsByTask` 由 REST（列表/详情/标注接口）填充，WS 永不写入（`upsertTask` 仅在 `task.label != null` 时合并、绝不删除；`setInitialTasks` 全量重建；标注接口成功后用显式 `setLabel` 写/删）。

### `LabelCorrectionDialog.tsx`

弹窗表单：

- **type 选择器**（stock / option）：
  - 正股卡默认 `stock`，期权卡默认 `option`
  - **PARSE_ERROR 卡默认 `stock`**，用户可切换
  - 切到 option 时显示 strike / expiry / option_type 字段
- 字段：`ticker`、`price`、`quantity`、`action`（下拉 BUY / SELL / CLOSE / MODIFY）；option 追加 `strike`、`expiry`、`option_type`（下拉 CALL / PUT）。
- 预填顺序：优先已有 `corrected_payload`（再次编辑场景），否则用 `task.instruction` 的解析值（PARSE_ERROR 无 instruction 时留空）。
- 取消 / 保存。保存 → `setTaskLabel(id, { verdict: "corrected", corrected_payload })`。

### 接入 `SignalBubble.tsx`

- 在 `signal-detail` 块底部渲染 `<LabelActions task={task} variant={variant} />`，**只在 `expanded` 时出现**。
- 三种卡片（stock / option / parse_error）都走非图片分支，因此统一在此处接入。
- **图片卡（`isImage` 分支）不加**按钮排。

### 样式

- 在 `SignalCard.css`（及/或新增局部样式）加按钮排和弹窗样式，沿用现有暗色卡片视觉。

## 不在本次范围内（YAGNI）

- 标注数据的导出 / 批量查看界面。以后需要时单加一个导出端点 / 查询即可，不影响本次表结构。
- 校正不回写、不重跑交易（用途明确为纯评测数据）。

## 测试

### 后端
- repo：`set_label` 新建与覆盖、`clear_label` 删除、task 查询正确 join 出 `label`。
- 端点：`PUT` verdict=correct、`PUT` verdict=corrected（带 payload）、`DELETE` 清除；标注正确出现在 task 列表与详情响应中。

### 前端
- `LabelActions`：三态切换（未标注↔correct↔corrected）调用正确的 api 并更新 store。
- `LabelCorrectionDialog`：从 `task.instruction` 预填、从已有 `corrected_payload` 预填、type 切换显隐 option 字段、保存提交正确 payload。
- `SignalBubble`：按钮排仅在展开时显示；仅 stock / option / parse_error 三类卡显示，图片卡不显示。
