# Chat 组件拆分 + UI 快照测试基础设施

**Date:** 2026-05-21
**Status:** Brainstormed · pending plan
**Scope:** `frontend/src/components/Chat/*`, `frontend/src/test/*`

## 背景

1. 项目缺乏"让单个 UI 组件能被独立 render + 用 mock 数据填充 + 验证生成的 HTML 是否符合预期"的测试基础设施。组件改动时只能依赖人眼回归，导致样式劣化没有自动信号。
2. `feat(chat): embed stock/option signal cards in chat list` (commit `bf38c1c`) 后，highlight 模式的 `StreamView` 把普通聊天消息样式从 `.chat-group-bubble`（pre-卡片）改成了 `.stream-bubble`（字体偏小、`max-width:78%`），与早期 `GroupChatView` 的视觉契约不一致。同时，正股 / 期权信号卡在流里直接以裸 `SignalCard` 渲染，没有共享统一外壳，跟普通消息排版不对齐。

本 spec 同时解决：
- 建一套可复用的"快照式"UI 测试方法 — 后续所有组件都能套用。
- 把 chat 视图拆成三个语义清晰的高层组件，恢复普通消息的 pre-卡片视觉效果。

## 用户视觉契约

普通消息在 chat 流里的契约（恢复 pre-卡片效果）：

```
icon 昵称 时间
   消息气泡          ← .chat-group-bubble (font-size:13px, max-width:600px, width:fit-content)
   消息气泡          ← 同发送者连发时共享 head，气泡堆叠
```

正股 / 期权信号在 chat 流里的契约（外壳与普通消息一致）：

```
icon 昵称 时间
   解析气泡          ← .signal-bubble[.stock|.option] (3 层：MSG/SIG/ORD，左侧色带)
```

差异仅在气泡内部样式。head（avatar + 昵称 + 时间）三行结构完全一致。

## 组件树

新结构定义 6 个组件，按"低层 → 高层"组合：

| 层 | 组件 | 职责 | 渲染 |
| --- | --- | --- | --- |
| 低 | `MessageShell` | 唯一画 head + body 槽位的地方 | `.chat-group` / `.chat-group-head` / `.chat-group-body` (+ `.chat-group--right`) |
| 低 | `PlainBubble` | 单条文本气泡（含 quoted 嵌套） | `.chat-group-bubble` |
| 低 | `SignalBubble` | 3 层 signal 气泡（折叠 / 展开） | `.signal-bubble[.stock\|.option\|.neutral]` |
| 高 | `ChatMessage` | `MessageShell` + N×`PlainBubble`（同发送者连发合并） | — |
| 高 | `StockCard` | `MessageShell` + `SignalBubble[variant=stock]` | — |
| 高 | `OptionCard` | `MessageShell` + `SignalBubble[variant=option]` | — |

### 组件 props

```ts
// MessageShell
interface MessageShellProps {
  sender: string;
  firstAt: string;                          // ISO timestamp; 内部 fmtTime 化为 HH:mm
  avatarColor?: string;                     // 默认走 paletteColorFor(sender)
  align: "left" | "right";                  // 右对齐 = watched 发送者
  senderTone?: "stock" | "option";          // 染色 monitor 名（用 source-stock / source-option）
  children: React.ReactNode;                // body 槽：bubble 或 bubble 列表
}

// PlainBubble
interface PlainBubbleProps {
  content: string;
  quoted?: { author: string; content: string } | null;
}

// SignalBubble
interface SignalBubbleProps {
  task: TaskSummary;
  pushEvents: PushEvent[];
  expanded: boolean;
  onToggle(): void;
  autoTrade: boolean;
  variant: "stock" | "option";              // 控制色带 + 展开态字段显示（strike/expiry 仅 option）
}

// ChatMessage
interface ChatMessageProps {
  sender: string;
  firstAt: string;
  messages: ChatMessageOut[];
  align: "left" | "right";
}

// StockCard
interface StockCardProps {
  monitorName: string;
  task: TaskSummary;
  pushEvents: PushEvent[];
  expanded: boolean;
  onToggle(): void;
  autoTrade: boolean;
  align: "left" | "right";
}

// OptionCard
// 同 StockCard，monitorName + task 一组
```

### 高层组件总是带 head

aggregate 路径（filter 模式）里每条信号也使用完整 `StockCard` / `OptionCard`，不引入 `hideHead` 分支。三个高层组件职责单一，没有条件渲染。

## 测试基础设施

### 目录与文件

```
frontend/src/test/
├── test-setup.ts        // 已存在，不动（jsdom + jest-dom 注册）
├── fixtures.ts          // 新建：工厂函数
└── fixtures.test.ts     // 新建：sanity test，保证默认值稳定

frontend/src/components/Chat/
├── MessageShell.tsx          + .test.tsx
├── PlainBubble.tsx           + .test.tsx
├── SignalBubble.tsx          + .test.tsx        // 合并旧 SignalCard 的渲染逻辑
├── ChatMessage.tsx           + .test.tsx
├── StockCard.tsx             + .test.tsx
└── OptionCard.tsx            + .test.tsx
```

### fixture API

```ts
// 主键自增，默认时间 2026-05-21T01:00:00Z，每次调用 +1 分钟
makeMessage(overrides?: Partial<ChatMessageOut>): ChatMessageOut
makeStockTask(overrides?: DeepPartial<TaskSummary>): TaskSummary
makeOptionTask(overrides?: DeepPartial<TaskSummary>): TaskSummary
makePushEvent(overrides?: Partial<PushEvent>): PushEvent

// 组合场景
makeConsecutiveMessages(sender: string, contents: string[]): ChatMessageOut[]
makeQuotedMessage(
  author: string,
  content: string,
  quoted: { author: string; content: string },
): ChatMessageOut
makeFilledStockTask(overrides?): TaskSummary        // status=FILLED + cum_qty + push events
makeFailedParseTask(overrides?): TaskSummary        // instruction=null
```

**确定性约束：**
- 工厂内部用一个模块级单调计数器生成 id / 时间，每次 `import` 重置（vitest 模块隔离自动满足）。
- 不引用 `Date.now()` 或 `Math.random()`。
- `fixtures.test.ts` 锁定首次调用默认值的 ID / 时间，防止 fixture 默认值漂移让所有快照同时翻车。

### 快照测试约定

所有组件统一：

```ts
const { container } = render(<Component {...props} />);
expect(container.innerHTML).toMatchSnapshot();
```

- 不用 `prettyDOM`，不用 inline snapshot。
- 一个 `it()` = 一个场景 = 一个快照（颗粒度可控、diff 集中）。
- 测试名描述场景名（如 `"folded · filled order"`），快照文件按 it() 名自动落到 `__snapshots__/`。
- fixture 永远走 `makeXxx()`，不内联硬编码 ChatMessageOut / TaskSummary。

### 首批快照矩阵

| 组件 | 场景 |
| --- | --- |
| `MessageShell` | `left` · `right` · `monitor-stock-tone` · `monitor-option-tone` |
| `PlainBubble` | `short` · `long` · `with-quoted` |
| `SignalBubble` | `stock-folded` · `stock-expanded` · `option-folded` · `option-expanded` · `parse-error` |
| `ChatMessage` | `single` · `consecutive-3-msgs` · `right-aligned` |
| `StockCard` | `folded` · `expanded` · `parse-error` · `order-pending` |
| `OptionCard` | `folded` · `expanded` |

合计 ~20 个快照；vitest jsdom 单测一次跑完毫秒级。

## StreamView / ChatBoardPanel 重写

### 新 `StreamView.tsx`

外部 API 不变（保持 `groups / watched / pushEventsByTask / expandedTaskId / onToggleTask / autoTrade` props），内部重写为薄路由：

```tsx
return (
  <div className="stream-view">
    {groups.map((g, i) => {
      const align = watched.has(g.sender) ? "right" : "left";
      if (g.kind === "msgs") {
        return (
          <ChatMessage
            key={i}
            sender={g.sender}
            firstAt={g.entries[0].posted_at}
            messages={g.entries}
            align={align}
          />
        );
      }
      const Card = g.task.type === "option" ? OptionCard : StockCard;
      return (
        <Card
          key={i}
          monitorName={g.sender}
          task={g.task}
          pushEvents={pushEventsByTask[g.task.id] ?? []}
          expanded={expandedTaskId === g.task.id}
          onToggle={() => onToggleTask(g.task.id)}
          autoTrade={autoTrade}
          align={align}
        />
      );
    })}
  </div>
);
```

`.stream-view` 仅作为外层 flex column 容器（gap:14px）保留；`.stream-group / .chat-stream-head / .stream-bubble / .stream-body` 全部删除。

### `ChatBoardPanel.tsx` 路径

| 旧路径 | 新路径 |
| --- | --- |
| pure-chat → `<GroupChatView messages={messages} />` | `buildStreamGroups(timeline)` → `<StreamView>` |
| pure-chat + watched (highlight) → `<GroupChatView messages watched />` | `buildStreamGroups(timeline)` → `<StreamView>` |
| mixed → `<StreamView>` | （不变） |
| filter mode + watched → 自拼 chat-card.aggregate（内含 SignalCard） | 自拼 chat-card.aggregate（内含 `StockCard` / `OptionCard`） |

四条路径统一为两条：highlight / pure-chat → `<StreamView>`，filter → aggregate 卡片但内部用新组件。

### 清理清单（一次性 PR 完成）

| 动作 | 对象 |
| --- | --- |
| 删 | `frontend/src/components/Chat/SignalCard.tsx` + `SignalCard.test.tsx`（逻辑迁入 `SignalBubble`） |
| 删 | `frontend/src/components/Chat/GroupChatView.tsx`（逻辑被 `buildStreamGroups` + `ChatMessage` 取代） |
| 删 | `ChatBoardPanel.css` 中 `.stream-group / .chat-stream-head / .stream-bubble / .stream-body / .stream-group.watched.*`（约 60 行） |
| 改 | `ChatBoardPanel.tsx`：去掉 GroupChatView 分支；filter 路径中 `<SignalCard>` 换成 `<StockCard>` / `<OptionCard>` |
| 改 | `StreamView.tsx`：重写为薄路由 |
| 新 | 6 个组件 + 6 个测试文件 + `frontend/src/test/fixtures.ts` + `fixtures.test.ts` |

### 已有测试的处理

- `SignalCard.test.tsx` 删除，覆盖被 `SignalBubble.test.tsx` + `StockCard.test.tsx` + `OptionCard.test.tsx` 吸收。
- `StreamView.test.tsx` 改为只验证"路由正确"（msg group → ChatMessage / signal stock → StockCard / signal option → OptionCard），不验证 head / bubble 的样式细节 — 那些归子组件管。
- `signalCardHelpers.test.ts` 不动（pure logic）。
- `chatTimeline.test.ts` 不动（pure logic）。

## 验收

- [ ] 普通消息在 chat 流里恢复 `.chat-group-bubble` 样式（font-size:13px / max-width:600px / width:fit-content）。
- [ ] watched 发送者的消息右对齐（`.chat-group--right`），跟 pre-卡片一致。
- [ ] 正股 / 期权信号在流里与普通消息共享 head 三连（avatar + 昵称 + 时间），仅 bubble 是 `.signal-bubble`。
- [ ] filter 模式 aggregate 卡片内每条信号是 `StockCard` / `OptionCard`，不是裸 SignalCard。
- [ ] `frontend/src/test/fixtures.ts` 工厂可用，被 6 个组件测试消费。
- [ ] `frontend/__snapshots__/` 共 ~20 个稳定快照；`npm run test` 全绿。
- [ ] `npm run typecheck` 全绿；旧 `SignalCard.tsx` / `GroupChatView.tsx` 已删除。
- [ ] `ChatBoardPanel.css` 中 `.stream-bubble` / `.chat-stream-head` 等死代码已清。

## 非目标

- 不引入 Playwright 或 Storybook（保留全 vitest + jsdom 链路）。
- 不改变 `chat-card.aggregate` 卡片的外观或 ∑ 头逻辑，仅替换内部子项的组件类型。
- 不调整 `.signal-bubble` 3 层布局（MSG/SIG/ORD），只是把它放到 `SignalBubble.tsx` 这个文件里。
- 不重构 `chatTimeline.ts` 的分组算法（仅消费它的输出）。

## 风险与缓解

| 风险 | 缓解 |
| --- | --- |
| 旧 `SignalCard` 的 `.signal-bubble` 行为在迁移到 `SignalBubble` 时遗漏（如 confirm-pair 阻止冒泡的 onClick 守卫） | 迁移前对照 `SignalCard.tsx` 逐字段映射；保留原 `signalCardHelpers.test.ts` 验证 layersForTask 不变；新 `SignalBubble.test.tsx` 显式覆盖 `parse-error` / `order-pending`。 |
| 快照首次落地后，未来 className / DOM 微调会引发噪声 diff | 测试名贴场景化（不是 "snapshot 1"），评审者能从快照文件名一眼判断是否符合预期；fixture 单一来源使得"故意 + 一次性"的更新成本可控。 |
| 同发送者连发的"head 合并"逻辑在 `ChatMessage` 里实现错位（如把 stock card 错误合并进上一条 chat msg） | `buildStreamGroups` 已经把 `kind:"signal"` 强制独立成组，flush 逻辑保证不会跨类型合并；`StreamView.test.tsx` 显式覆盖"chat msg 后紧跟 signal"场景。 |
