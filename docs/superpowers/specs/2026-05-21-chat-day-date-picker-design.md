# Chat Board Day-Based Date Picker

## 背景与动机

讨论区 (`ChatBoardPanel`) 目前以 ISO 周为粒度展示消息：`App.tsx` 把 `currentIsoWeek()`
硬编码作为 `week` prop 传入，面板把一整周的消息全部展示出来。
代码里已有 TODO：「Week-navigation for chat pages is not yet implemented」。

用户希望以「日」为单位浏览消息，并在讨论区面板右下角悬浮一个日期控件，支持：

- 左右箭头快速切换上一天 / 下一天
- 中间按钮显示当前选中日期，点击弹出月格日历
- 日历中「有消息的日子」有视觉标记

## 设计原则

- 只读看板，不引入任何「输入」UI
- 不新增第三方依赖（日历自己写，复用 `weekUtils.ts` 风格）
- 后端不动，过滤完全在客户端做，复用现有按周拉取与缓存
- 顶部 `ChatSenderBar` 的发件人筛选 / 高亮模式保持不变，与日筛选正交叠加
- 所有日期计算以 Asia/Shanghai 视角为准，与项目其他模块一致

## 范围

### 包含

- 新增右下角悬浮日期控件（左右箭头 + 中间日期按钮）
- 自写月格日历弹窗
- 把 `ChatBoardPanel` 从「按周展示」改为「按日过滤展示」
- 派生周自动触发现有按周拉取
- 日历首次打开 / 翻月时预取该月覆盖的所有 ISO 周，用于点亮「有消息」小圆点
- 在 `weekUtils.ts` 中追加 6 个日期工具函数
- 删除 `App.tsx` 中硬编码 `week` prop 与对应 TODO

### 不包含

- 后端 API 修改（继续 `?week=YYYY-Www` 拉取）
- 消息发送 / 编辑 / 删除（讨论区仍是只读）
- 选中日期跨会话持久化（每次打开默认「今天」）
- 顶部 `ChatSenderBar` 的功能修改

## UI 设计

### 布局

日期控件以 `position: absolute` 悬浮在 `.chat-board` 滚动区的右下角，
不占据布局空间，不影响顶部 `ChatSenderBar` 与消息列表。

```
┌──────────────────────────────────────────────────────┐
│  [ChatSenderBar - 不动]                              │
├──────────────────────────────────────────────────────┤
│                                                      │
│  消息卡片 1                                          │
│  消息卡片 2                                          │
│  ... (仅显示选中日期的消息)                          │
│                                                      │
│                                                      │
│                              ┌──────────────────┐    │
│                              │  ‹  📅 今天  ›   │    │  ← 右下角悬浮
│                              └──────────────────┘    │
└──────────────────────────────────────────────────────┘
```

- 左箭头 `‹`：跳上一天。无下限。
- 右箭头 `›`：跳下一天。`selectedDate === today` 时置灰禁用。
- 中间按钮：点击切换日历弹窗显示状态。
- 控件背景半透明，避免完全遮挡其下方的消息。

### 日期文案规则

| 条件 | 显示 |
|---|---|
| `dayKey === todayInShanghai()` | `今天` |
| 比今天早 1 天 | `昨天` |
| 同年其他 | `5月18日 周日` |
| 跨年 | `2025年12月31日 周三` |

### 日历弹窗

锚定在中间按钮**上方左侧**（CSS：`bottom: 100%; right: 0`），向上、向左展开，
不会被屏幕底部截断。

布局：

```
┌─────────────────────────────────┐
│  ‹       2026 年 5 月        ›  │  ← 月份导航
├─────────────────────────────────┤
│  一  二  三  四  五  六  日     │  ← 周名
├─────────────────────────────────┤
│              1   2   3   4      │
│  5   6   7   8   9  10  11      │
│ 12  13  14  15  16  17  18      │
│ 19  20 [21] 22  23  24  25      │  ← 21 是今天，边框高亮
│           •           •         │  ← 有消息日子下方小点
│ 26  27  28  29  30  31          │
└─────────────────────────────────┘
```

视觉规则：

- **选中日**：实心背景
- **今天**：边框高亮（与选中互不冲突，两者可叠加）
- **未来日**：置灰，不可点击
- **有消息日**：数字下方一个小圆点
- **当月之外的日**（5 月格中显示的 4 月末或 6 月初的灰日）：可选择灰显，但仍可点击（点击后跳到对应月并选中）
- 点击日期 → 关闭弹窗并切换 `selectedDate`
- 点击弹窗外区域 → 关闭弹窗
- 弹窗打开期间，月份导航箭头改变 `calendarMonth`，触发新月份预取

## 状态与数据流

### 状态（位于 `ChatBoardPanel`）

```ts
const [selectedDate, setSelectedDate] = useState<string>(todayInShanghai());
// "YYYY-MM-DD"，Asia/Shanghai 视角

const [calendarOpen, setCalendarOpen] = useState<boolean>(false);

const [calendarMonth, setCalendarMonth] = useState<string>(monthOf(selectedDate));
// "YYYY-MM"
```

### 派生值

- `selectedWeek = weekKeyOf(selectedDate)` → 喂给现有按周缓存 hook
- 取代 `App.tsx` 里硬编码的 `currentIsoWeek()`；`week` prop 从 `<ChatBoardPanel>` 上移除
- `dayLabel = formatDayLabel(selectedDate)` → 中间按钮文案
- `isAtToday = selectedDate === todayInShanghai()` → 右箭头是否禁用
- `monthDays = daysInMonth(calendarMonth)` → 日历格子
- `monthWeeks = weeksCoveringMonth(calendarMonth)` → 预取目标

### 消息过滤管线

在 `ChatBoardPanel` 渲染时按以下顺序处理：

```
chatStore[selectedWeek].messages
   ↓ filter(msg => dayKeyOf(msg.posted_at) === selectedDate)   ← 本次新增
   ↓ groupIntoCards(messages, { senderFilter, mode })          ← 既有逻辑，内部已含
   ↓                                                              发件人筛选 / 高亮
   ↓ render
```

发件人筛选 / 高亮模式的实现入口在 `groupIntoCards` 内部，本次不动；
日过滤作为它的前置步骤，仅缩小输入集合。

### 跨周切换

- 点 `‹` / `›` 跨越周边界时，`selectedWeek` 派生值变化，现有 `useChatMessages(selectedWeek)` 自动触发新周拉取
- 拉取期间 `.chat-board` 显示已有的 loading skeleton（不新增），DayPicker 与日历仍可交互
- 不缓存任何「过去看过的天」状态，纯派生

### 预取小圆点数据

`calendarOpen` 从 `false` → `true` 时：

```ts
useEffect(() => {
  if (!calendarOpen) return;
  weeksCoveringMonth(calendarMonth).forEach(week => {
    chatStore.fetch(pageId, week, []); // 若该周已缓存则 no-op
  });
}, [calendarOpen, calendarMonth, pageId]);
```

`hasMessagesOnDay(day)` 实现：

```ts
function hasMessagesOnDay(day: string): boolean {
  const week = weekKeyOf(day);
  const cached = chatStore.weeks[week];
  if (!cached || cached.status !== 'loaded') return false;
  return cached.messages.some(msg => dayKeyOf(msg.posted_at) === day);
}
```

未加载的周返回 `false`：日历会显示「该日子没小点」直到预取完成。
预取完成后 React 会重新渲染，小点点亮，无需手动通知。

## 组件结构

### 新增文件

1. **`frontend/src/components/Chat/DayPicker.tsx`**（~80 行）
   - Props：`{ selectedDate, maxDate, hasMessagesOnDay, onChange, onCalendarOpenChange, calendarMonth, onCalendarMonthChange }`
   - 渲染右下角悬浮的 `‹ [日期按钮] ›` 三元素与日历弹窗
   - 内部管 `calendarOpen` 状态，向父透出 `onCalendarOpenChange`

2. **`frontend/src/components/Chat/CalendarPopover.tsx`**（~120 行）
   - Props：`{ visibleMonth, selectedDate, maxDate, hasMessagesOnDay, onPickDay, onMonthChange, onClose }`
   - 渲染月格日历 + 月份导航
   - 监听 `document.mousedown` 实现点外面关闭

3. **`frontend/src/components/Chat/DayPicker.css`**
   - 控件 + 弹窗样式，与项目现有 chat 样式风格一致

### 修改文件

4. **`frontend/src/components/Chat/ChatBoardPanel.tsx`**
   - 引入 `selectedDate`、`calendarOpen`、`calendarMonth` 三个 state
   - 移除 `week` prop，改为 `selectedWeek = weekKeyOf(selectedDate)` 派生
   - 在 `groupIntoCards` 调用前对 messages 做日过滤
   - 在面板内挂载 `<DayPicker />` 悬浮在 `.chat-board` 上
   - 注册预取 effect
   - 空状态：过滤后无消息时显示「这一天还没有消息」

5. **`frontend/src/components/Chat/ChatBoardPanel.css`**
   - 给 `.chat-panel` 加 `position: relative`（确保 DayPicker 的 `absolute` 锚定到面板）

6. **`frontend/src/App.tsx`**
   - 删除 `currentIsoWeek()` 调用与 `week` prop 传递
   - 删除关联的 TODO 注释

7. **`frontend/src/components/Dashboard/weekUtils.ts`**
   - 追加工具函数（见下）

### `weekUtils.ts` 新增 API

```ts
// "2026-05-21" in Asia/Shanghai
export function dayKeyOf(isoTs: string): string;

// "2026-05-21"
export function todayInShanghai(): string;

// addDays("2026-05-21", -1) === "2026-05-20"
export function addDays(dayKey: string, n: number): string;

// monthOf("2026-05-21") === "2026-05"
export function monthOf(dayKey: string): string;

// daysInMonth("2026-05") 返回该月所有日子（用于日历网格）
// 形如 ["2026-05-01", ..., "2026-05-31"]
export function daysInMonth(monthKey: string): string[];

// 该月覆盖的所有 ISO 周（一般 5 个，偶尔 4 或 6 个）
export function weeksCoveringMonth(monthKey: string): string[];

// "今天" / "昨天" / "5月18日 周日" / "2025年12月31日 周三"
export function formatDayLabel(dayKey: string): string;
```

## 边界与失效模式

| 情况 | 处理 |
|---|---|
| 默认进入今天还没消息 | 显示空状态文案；左箭头可点 |
| 一直按左箭头跨周 | 派生周变化，自动触发新周拉取 |
| 一直按左箭头到远古日期 | 不设硬下限；空数据周显示空状态 |
| 选中今天后右箭头 | 禁用，置灰 |
| 日历翻到未来月 | 月份导航箭头允许去未来月份；具体未来日格子置灰不可点 |
| 日历预取期间 | 日历底部显示 `加载中...`，已载入周的小点先点亮 |
| 同周内切日 | 零延迟，纯客户端过滤 |
| 跨周切日 | `.chat-board` 闪一下 loading skeleton（复用现有），DayPicker 保持可点 |
| 顶部发件人筛选与日筛选叠加 | 日过滤 → 发件人过滤，AND 关系 |
| 顶部高亮模式 | 日过滤先做，高亮再叠加；语义为「这一天里高亮某些发件人」 |
| 时区临界（北京时间 0:30 消息） | `dayKeyOf` 使用 Asia/Shanghai 视角，归到当天 |
| 切换 page 再切回 | `selectedDate` 重置为今天（组件 unmount） |

## 测试

### 手工测试清单

1. 打开讨论区 → 默认选中今天
2. 点 `‹` → 跳到昨天，按钮文案变「昨天」
3. 连续点 `‹` 7 次 → 跨周，正确触发新周拉取
4. 点 `›` → 回今天，右箭头禁用
5. 点中间按钮 → 日历弹出，今天有边框，已缓存周的小点显示
6. 等 ~1 秒预取完 → 整月有消息日子的小点全部点亮
7. 点某天 → 弹窗关闭，主区切换
8. 翻下个月 → 未来日格子置灰
9. 选完日期后顶部点某个发件人 → 显示「该天 ∩ 该发件人」
10. 点日历外区域 → 关闭
11. 缩窄面板宽度 → 日历不溢出
12. 切走再切回 → `selectedDate` 重置为今天

### 自动化测试

若项目已有 `weekUtils.test.ts` 或同类测试基建（实现阶段确认），在其中补充新函数单测，
重点覆盖：

- 时区临界：UTC 时间 2026-05-20T16:30:00Z（北京 5-21 00:30）应归到 `2026-05-21`
- 月底跨月：`addDays("2026-05-31", 1) === "2026-06-01"`
- 年底跨年：`addDays("2025-12-31", 1) === "2026-01-01"`
- `weeksCoveringMonth("2026-02")` 在闰年 / 非闰年的边界

若无现成测试基建，则不在本次设计中新建——以手工测试清单为准。

## 实现顺序建议

1. 在 `weekUtils.ts` 中实现 6 个新工具函数并写单测
2. 实现 `CalendarPopover.tsx`（纯展示，先用假的 `hasMessagesOnDay`）
3. 实现 `DayPicker.tsx`，把 `CalendarPopover` 嵌入
4. 改造 `ChatBoardPanel.tsx`：引入状态、日过滤、挂载 DayPicker
5. 实现预取 effect 与真实 `hasMessagesOnDay`
6. 改造 `App.tsx`：移除 `week` prop 与 TODO
7. 手工跑测试清单

## 不引入的项目

- 不引入 dayjs / date-fns / react-day-picker
- 不缓存「曾经选过的日期」
- 不为「有消息」小点单独搭后端聚合接口（直接复用周缓存）
- 不修改 `ChatSenderBar`
- 不修改后端 schema / endpoint
