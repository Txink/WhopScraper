# 讨论区按天懒加载 — 设计说明

**日期**：2026-05-23
**范围**：`/api/whop/pages/{page_id}/chat-messages` 接口、新增 `chat-message-counts` 接口、`chatStore`、`ChatBoardPanel`、WS `chat.message_stored` 处理、相关测试与生成的 OpenAPI 类型。

## 背景

当前进入 ChatBoardPanel（讨论区）时，前端会一次性拉取「选中日期所在 ISO 周」的全部消息（最多 7 天），缓存 key 是 `(pageId, week)`。打开 DayPicker 日历时还会预取整月覆盖的所有周。一个用户可能只是想看今天的内容，但每次进入页面都要把整周（甚至打开日历后整月）下载下来。

随着 Whop 监控的 chat 页消息量上升，这个一次性大窗口的初始加载体感越来越差，而绝大多数会话只关心最近一两天的信息。

参考最近的相关 commit：
- `c2aba18 fix(chat): correctly bin messages by Beijing calendar day` — 客户端按北京日历日 `dayKeyOf` 切分消息。后端目前按 UTC 周边界查询，新接口必须按北京日切。
- `de8310f refactor(dashboard): drop Whop 管理 view, single default 讨论区` — 讨论区已成为默认入口。

## 目标

1. 进入讨论区时只下载「今天」+「昨天」两天的消息（北京日历日）。
2. 切到更早的日期时按需拉取那一天，不是那一周。
3. 日历小圆点（哪些天有消息）通过一个**单独的、轻量**的月度计数接口取得，初始进入和翻月时拉取，与消息正文解耦。
4. 不破坏 WS `chat.message_stored` 的实时追加体验。

## 非目标

- 日内「下拉加载更早」类型的二次分页：一个北京日就是最小渲染单元。
- `senders=` 过滤器的语义变化：仍只作用于消息接口（且当前前端调用都传空数组，沿用既有形态）。
- 浏览器侧迁移：`chatStore` 是 zustand 内存缓存，没有 localStorage 持久化，刷新即重新加载。

## 改造前后对比

| 场景 | 改前 | 改后 |
|---|---|---|
| 首次进入 chat page | 1 次请求拉整周（≤7 天）消息；圆点要等用户打开日历后再预取整月各周才出 | 2 次并行请求拉今天 + 昨天；1 次请求拉当月计数；圆点即可显示 |
| 用户在 DayPicker 中选了一个未缓存的日期 | 若跨周则重新拉整周；同周内不发请求 | 拉那一天；命中缓存则不发请求 |
| 用户翻日历月份 | 打开日历时一次性预取整月覆盖的多个周 | 拉那一月的计数（一次）；不拉消息正文 |
| 收到 `chat.message_stored` WS 事件 | 重拉该 page 下所有已缓存的周 | 重拉今天那一天 + 当月计数（仅当二者已缓存） |
| 进入 page 但 page.id 不变（重渲染） | 命中缓存，不重拉 | 命中缓存，不重拉 |

## 后端设计

### 1. 修改 `GET /api/whop/pages/{page_id}/chat-messages`

新增 `day=YYYY-MM-DD` 查询参数，同时**移除** `week=` 参数（这次改动一起删，前端不再用它）。

- 必须传 `day`，缺失返回 `400 missing 'day'`。
- `day` 解析为 `[day 00:00 +08:00, 次日 00:00 +08:00)`，转换为 UTC 后传给 `repo.list_chat_messages`（repo 是区间查询，不需要改）。
- `senders` 行为不变（可选、逗号分隔、为空 → 不过滤）。
- `authors` 现在表示**该天**的作者计数（不含过滤），仍按 `count DESC` 排序。
- 响应字段：
  ```json
  {
    "messages": [...],
    "authors": [{"name": "...", "count": N}, ...],
    "day": {"start": "2026-05-23T00:00:00+08:00", "end": "2026-05-24T00:00:00+08:00"}
  }
  ```
  `week` 字段从响应中删除。

新增辅助函数 `_beijing_day_bounds(day: str) -> tuple[datetime, datetime]`（与 `_iso_week_bounds` 同位置，`backend/app/api/http.py`），返回带 UTC tzinfo 的 `(start, end)` 半开区间。无效格式 → `HTTPException(400, "invalid day: <input>")`。

### 2. 新增 `GET /api/whop/pages/{page_id}/chat-message-counts`

- 查询参数：`month=YYYY-MM`（必填，缺失 → `400 missing 'month'`）。
- 响应：
  ```json
  {
    "month": "2026-05",
    "counts": {"2026-05-22": 14, "2026-05-23": 3}
  }
  ```
- 仅返回 `count > 0` 的天；客户端读不到的 key 即视为 0。
- 月份边界为 `[month-01 00:00 +08:00, (month+1)-01 00:00 +08:00)`。
- 不接 `senders` 过滤。

实现层面新增 repo 函数：
```python
async def count_chat_messages_per_day(
    session: AsyncSession,
    page_id: str,
    range_start_utc: datetime,
    range_end_utc: datetime,
) -> list[tuple[str, int]]:
    """按北京日 (YYYY-MM-DD) 聚合返回 (day, count)，仅 count > 0。"""
```
SQLite 用 `func.strftime("%Y-%m-%d", func.datetime(ChatMessageRow.posted_at, "+8 hours"))` 作为分组键。函数返回字符串日键（已是北京日历日），让 endpoint 层无需再做时区转换。

注：项目用 SQLite。若未来切到 Postgres，相应 SQL 需替换为 `to_char(posted_at AT TIME ZONE 'Asia/Shanghai', 'YYYY-MM-DD')` —— 不在本次改动范围。

### 3. Schemas 调整（`backend/app/api/schemas.py`）

- `ChatWeekWindowOut` → `ChatDayWindowOut`（保留 `start: datetime, end: datetime` 两字段；命名沿用现有约定）。
- `ChatMessagesOut`：`week: ChatWeekWindowOut` → `day: ChatDayWindowOut`。
- 新增 `ChatMessageCountsOut { month: str, counts: dict[str, int] }`。

## 前端设计

### 4. `chatStore` 重塑（`frontend/src/stores/chatStore.ts`）

```ts
interface ChatDayCache {
  messages: ChatMessageOut[];
  authors: { name: string; count: number }[];
  day: { start: string; end: string };
  fetchedAt: number;
}

interface ChatMonthCounts {
  month: string;
  counts: Record<string, number>;  // dayKey -> count, only > 0
  fetchedAt: number;
}

interface ChatStore {
  /** key: `${pageId}|${day}` (day = YYYY-MM-DD Beijing) */
  caches: Record<string, ChatDayCache>;
  /** key: `${pageId}|${month}` (month = YYYY-MM Beijing) */
  counts: Record<string, ChatMonthCounts>;
  fetchDay: (pageId: string, day: string, senders: string[]) => Promise<void>;
  fetchCounts: (pageId: string, month: string) => Promise<void>;
  applyStoredMessage: (pageId: string, day: string, message: ChatMessageOut) => void;
}
```

- 删除原 `fetch(pageId, week, senders)`。
- `applyStoredMessage` 仍然 dedupe by id + 按 `posted_at` 升序排序，只对已缓存 key 生效；语义与现在相同，参数从 `week` 改为 `day`。

### 5. `frontend/src/api/chat.ts`

- 把现有 `listChatMessages(pageId, week, senders)` 改成 `listChatMessagesForDay(pageId, day, senders)`（必传 `day`，删除 `week`）。
- 新增 `listChatMessageCounts(pageId, month) -> { month, counts }`。

### 6. `ChatBoardPanel.tsx` 触发逻辑

替换现有的两个 `useEffect`：

```tsx
// page 变化：并行拉今天 + 昨天 + 当月计数
useEffect(() => {
  const t = todayInShanghai();
  const y = addDays(t, -1);
  fetchDay(page.id, t, []);
  fetchDay(page.id, y, []);
  fetchCounts(page.id, monthOf(t));
}, [page.id, fetchDay, fetchCounts]);

// selectedDate 变化：缺失则拉那一天，跨月则拉新月计数
useEffect(() => {
  const dayKey = `${page.id}|${selectedDate}`;
  if (!allCaches[dayKey]) fetchDay(page.id, selectedDate, []);
  const monthKey = `${page.id}|${monthOf(selectedDate)}`;
  if (!allCounts[monthKey]) fetchCounts(page.id, monthOf(selectedDate));
}, [page.id, selectedDate, allCaches, allCounts, fetchDay, fetchCounts]);
```

读取消息时直接取 `allCaches[`${page.id}|${selectedDate}`]`；由于服务端已经按天切，前端就不需要再 `filter(m => dayKeyOf(m.posted_at) === selectedDate)`，删掉那个 `useMemo`。

**`hasMessagesOnDay`**：
```ts
const hasMessagesOnDay = useCallback((d: string) => {
  const counts = allCounts[`${page.id}|${monthOf(d)}`]?.counts;
  return counts ? (counts[d] ?? 0) > 0 : false;
}, [allCounts, page.id]);
```

**日历翻月**：在现有 `onVisibleMonthChange={setCalendarMonth}` 之后挂一个 `useEffect`，若 `calendarMonth` 对应 counts 未缓存则触发 `fetchCounts`。删除原 `weeksCoveringMonth` 整月预取循环和相关的 `prefetching` 显示逻辑（或将 `prefetching` 改为 `!allCounts[…]`，让 picker 在 counts 未到时还有 loading 提示 —— 视觉上保留指示器）。

**作者 chip 列表形状**：
当前用「当前周缓存的 authors」当作 chip 列表的基底，再用「当天」的计数覆盖。新逻辑：
```ts
const baseAuthors = useMemo(() => {
  const seen = new Set<string>();
  const out: { name: string; count: number }[] = [];
  // 聚合 page 下所有已缓存天的 authors，保持顺序按当前选中日 → 其它日
  const orderedDays = [selectedDate, ...Object.keys(allCaches)
    .filter(k => k.startsWith(`${page.id}|`) && k !== `${page.id}|${selectedDate}`)
    .map(k => k.slice(page.id.length + 1))];
  for (const d of orderedDays) {
    const c = allCaches[`${page.id}|${d}`];
    if (!c) continue;
    for (const a of c.authors) {
      if (!seen.has(a.name)) { out.push({ name: a.name, count: 0 }); seen.add(a.name); }
    }
  }
  return out;
}, [allCaches, page.id, selectedDate]);
```
然后用 `dayScopedAuthors`（基于当前 `messages`）覆盖 chip 上的 `count`，与现有 `authorsWithMonitors` 拼装逻辑一致。

### 7. WS 处理（`frontend/src/App.tsx` `chat.message_stored` 分支）

WS 事件的消息必然是「当下产生的」，所以只需要刷新今天那一天的视图和当月圆点：

- 用 `todayInShanghai()` 算出当前北京日 `t` 与月 `m = monthOf(t)`。
- 如果 `caches[`${pid}|${t}`]` 已缓存，调一次 `fetchDay(pid, t, [])`。
- 如果 `counts[`${pid}|${m}`]` 已缓存，调一次 `fetchCounts(pid, m)`。

不再遍历该 page 下「所有已缓存的天」做全量刷新 —— 这样即便用户翻看过 30 天历史，WS 事件也只会触发最多 2 个请求。前提是事件确实只反映「新增的当下消息」（与现有 `chat_writer` 写入路径一致）。

### 8. OpenAPI 类型

后端改完后跑 `npm run gen:types`（与 `frontend/src/api/types.ts` 现状一致的脚本）。`listChatMessagesForDay` 的入参/出参类型来自再生成的 schema；新接口同样有类型。

## 测试

### 后端

- `backend/tests/api/test_chat_messages_endpoint.py`：
  - 改造现有用例：把所有 `?week=` 调用改成 `?day=`，断言响应里 `day.start/end` 是北京 00:00 → 次日北京 00:00；不再断言 `week` 字段。
  - 新增 `day+week` 同传 → 不存在（因为 `week` 已删除），但要保留 `?day=` 缺失 → 400 的用例。
  - 新增**北京日边界**用例：插入一条 `posted_at = "2026-05-23T16:30:00Z"`（即 `2026-05-24 00:30 +08:00`）的消息，`?day=2026-05-24` 命中，`?day=2026-05-23` 不命中。
- 新建 `backend/tests/api/test_chat_message_counts_endpoint.py`：
  - 0 消息的天不出现在 `counts` 里。
  - 月初/月末边界：跨月的消息按北京日归属正确的月。
  - 与 `senders` 解耦：即便接口忽略 sender，结果应基于全部消息。
- `backend/tests/storage/test_chat_repo.py`：为新 `count_chat_messages_per_day` 加一组单测（多天、空天跳过、Beijing 偏移）。

### 前端

- 轻量 Vitest 加在 `frontend/src/stores/chatStore.test.ts`（新建）：
  - `fetchDay` 写入 `caches[pid|day]`。
  - `fetchCounts` 写入 `counts[pid|month]`，0 值不出现。
  - `applyStoredMessage`：未缓存的天直接丢弃；已缓存的天 dedupe + 排序。

## 风险与权衡

- **作者 chip 在「只看今天 + 昨天」时可能比之前少**：以前是整周的作者并集，现在是已缓存天的并集。如果用户切到一个未缓存日，chip bar 形状会在 fetch 返回后变化。可以接受 —— 与「按需加载」一致；切换到该天后 chip 立即扩展，不需要额外预取。
- **WS 重拉收窄到「今天 + 当月计数」**：基于「`chat.message_stored` 事件描述的是当下消息」这一假设。如果未来后端开始为历史回填/补抓也发同名事件，这里的视图就不会自动同步该历史日；需要时再扩为「事件 payload 带 day」并按 day 路由刷新。
- **SQLite 的 `+8 hours` 时区写法**：与 `repo.py` 现有北京日聚合查询的写法一致；切换数据库需要重写。已在新 repo 函数的 docstring 中标注。

## 不在本次范围

- 日内分页（懒加载某一天的更多消息）。
- `senders=` 过滤参数的语义变化。
- 浏览器持久化缓存。
- 同时显示多天（如「今天 + 昨天合并视图」）—— 一次只渲染一个 `selectedDate`。
- Postgres 兼容性。
