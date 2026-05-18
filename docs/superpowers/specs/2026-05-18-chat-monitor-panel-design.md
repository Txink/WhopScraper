# Chat 监控面板设计

## 背景

现有 Dashboard 监控的页面只有 `source ∈ {"stock", "option"}` 两种，消息流经解析管线变成 `tasks`。希望新增 `source = "chat"` 类型的页面，**只监听、不解析**：抓到的聊天消息原样落到一张新表 `chat_messages`，前端用"卡片流"形式展示，并支持按发送者过滤 + 导出。

数据源：**复用现有 whop 抓取流水线**（`backend/app/whop/extractor.py` 已经提取 `author / posted_at / quoted` 三件套），仅在 `listener` 层按 `page.source` 分流，不写新 scraper。

UI 形态：单列卡片流（在 brainstorming 阶段已通过 `/.design/chat-monitor-variants.html` 变体 C 确认）。

## 设计原则

- **范围最小**：listener 一个 if 分支 + 一张新表 + 一个新订阅者 + 一个新 GET endpoint。**不**引入抽象的 message dispatcher / 通用页面类型框架。
- **抓取/extractor/浏览器层 0 改动**：chat 与 stock/option 共享同一个 scraper 会话与调度。
- **卡片分组只在前端做一次**：导出 JSON 也走前端 Blob 下载，后端不实现分组逻辑。
- **过滤持久化**：发送者白名单 (`watched_senders`) 像现有 ticker 白名单一样存进 `page.settings`，刷新后保留。
- **复用现有 UI 组件**：`PageTabs / PageInfoBar / PageActionBar / WeekPaginator` 全部沿用；新组件仅限 `Chat/` 目录。

## 数据模型

### 新表 `chat_messages`

```
id                  TEXT PRIMARY KEY              -- whop 消息原生 ID
page_id             TEXT NOT NULL                 -- WhopPageEntry.id
                     REFERENCES whop_pages(id) ON DELETE CASCADE
author              TEXT NOT NULL                 -- 原始发送者名（scraper extract 一致）
content             TEXT NOT NULL
raw_content         TEXT NOT NULL
posted_at           TIMESTAMP NOT NULL            -- UTC
received_at         TIMESTAMP NOT NULL            -- UTC
url                 TEXT NULL                     -- 页面 URL，留作 trace
quoted_message_id   TEXT NULL                     -- 软 FK（无 FK 约束，可指空）
quoted_author       TEXT NULL                     -- 引用永远 denorm（防 FK 指空 / 跨周）
quoted_content      TEXT NULL
quoted_posted_at    TIMESTAMP NULL
created_at          TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
```

**索引**：
- `idx_chat_messages_page_posted` on `(page_id, posted_at DESC)` —— 周视图主路径
- `idx_chat_messages_page_author_posted` on `(page_id, author, posted_at DESC)` —— 发送者过滤

**引用全部 denorm 的理由**：被引用消息可能在抓取起点之前、来自非 watched sender、或跨周不在当前查询窗内。`quoted_message_id` 仅作软 FK，前端有就高亮跳转、没有也能渲染。

### `WhopPageEntry.settings` 新增字段

存进现有 `data/whop_pages.json` 的 settings JSON blob，无 schema 变更：

```python
watched_senders: list[str]      # 持久化发送者白名单；空表示不过滤
chat_card_max_msgs: int         # batch 卡片消息条数上限，默认 5
```

两者经现有 `PATCH /api/whop/pages/{page_id}/settings` 的 merge 流程更新。

### 与现有 `messages` 表的关系

**完全独立**。`source="chat"` 的页面消息只进 `chat_messages`，不进 `messages`、不进 `tasks`。`messages` 表保持现状（解析后交易指令的证据行）。

## 抓取与写入路径

### listener 分流（`backend/app/whop/listener.py`）

当前位置 `listener.py:273-284` 给每条消息发 `Topics.MESSAGE_RECEIVED`。改造为按 `self._page.source` 分流：

```python
tagged = dataclasses.replace(msg, url=self._url)
if self._page.source == "chat":
    publish(Event(Topics.CHAT_MESSAGE_RECEIVED, ChatMessagePayload(
        page_id=self._page.id,
        message=tagged,
        is_historical=is_historical,
    )))
else:
    publish(Event(Topics.MESSAGE_RECEIVED, MessagePayload(
        message=tagged, is_historical=is_historical,
    )))   # 现有路径完全不动
```

新增的 topic / payload 类放在 `backend/app/whop/topics.py` 与 `backend/app/whop/payloads.py`（或现有等价位置，沿用已有 topic/payload 文件）。

### 新订阅者 `backend/app/whop/chat_writer.py`

启动期注册到 event bus（在 `backend/app/main.py` 现有 `register_listeners()` 等价位置）：

```python
def on_chat_message(payload: ChatMessagePayload) -> None:
    row = ChatMessageRow.from_domain(payload.page_id, payload.message)
    repo.upsert_chat_message(row)
    if not payload.is_historical:
        publish(Event(Topics.CHAT_MESSAGE_STORED, ChatMessageStored(
            page_id=payload.page_id, row=row,
        )))
```

- **幂等**：`INSERT INTO chat_messages ... ON CONFLICT(id) DO NOTHING`
- **历史消息不广播**：避免回放刷屏；前端首次进入页面靠 HTTP GET 拉取
- **quote 字段填充**：`row` 构造时从 `message.quoted` 取 `author / content / posted_at`；如果 `quoted.id` 命中 `chat_messages.id` 则一并填 `quoted_message_id`（一次 `SELECT 1 FROM chat_messages WHERE id = ?` 探测；为了避免 N+1 也可改为写入时不查、后续读取时按 author+posted_at 反查 —— **方案定为写入时不查，`quoted_message_id` 仅由 extractor 提供的原始 id 串提供**，避免引入额外 DB round-trip）

### 新 repo 函数（`backend/app/storage/repo.py`）

```python
def upsert_chat_message(row: ChatMessageRow) -> None
def list_chat_messages(
    page_id: str, week_start: datetime, week_end: datetime,
    senders: list[str] | None,
) -> list[ChatMessageRow]
def list_chat_authors(
    page_id: str, week_start: datetime, week_end: datetime,
) -> list[tuple[str, int]]   # (author, count)，供前端 sender chips
```

`list_chat_messages` 返回按 `posted_at ASC` 排序的整周消息流；`senders=None` 或 `[]` 表示不按发送者过滤。

### WebSocket 桥接

`backend/app/api/ws.py` 现有桥接列表里加 `Topics.CHAT_MESSAGE_STORED`。前端 store 拿到广播后 append 到当前页缓存并重跑分组。

### Alembic 迁移

新版本：`xxxxxxx_add_chat_messages.py`，建 `chat_messages` 表 + 两个索引。`page_settings` 的新字段不需要 schema 迁移（JSON blob）。

## API

### 唯一新端点

```
GET /api/whop/pages/{page_id}/chat-messages
       ?week=YYYY-Www              (默认 = 当前 ISO 周)
       &senders=alice,bob          (逗号分隔，空则不过滤)
    → ChatMessagesOut {
        messages: ChatMessageOut[],            # 按 posted_at ASC
        authors:  { name: string, count: number }[],   # 该周该页全部出现过的发送者
        week:     { start: ISO, end: ISO }
      }
```

`ChatMessageOut`：

```ts
{
  id: string
  page_id: string
  author: string
  content: string
  posted_at: string                     // ISO UTC
  quoted?: {
    message_id: string | null
    author: string
    content: string
    posted_at: string | null
  }
}
```

### 复用的现有端点

- `GET /api/whop/pages` —— 已返回所有页，前端按 `source === "chat"` 渲染对应面板
- `POST /api/whop/pages` —— 已接受 `source` 字段，扩展 `Literal["stock", "option"] → Literal["stock", "option", "chat"]`
- `PATCH /api/whop/pages/{page_id}/settings` —— 用来改 `watched_senders` / `chat_card_max_msgs`，merge 行为已有

### 不实现的端点

- `/chat-messages/export` —— 改为前端 Blob 下载（见前端章节）
- `/chat-messages/authors` —— 合并进 `/chat-messages` 的返回

### 鉴权

沿用 `backend/app/api/auth.py` 的现有 session cookie 中间件。

## 前端

### 新文件结构

```
frontend/src/components/Chat/
  ChatBoardPanel.tsx        # 主容器，单列卡片流，挂 WeekPaginator
  ChatBoardPanel.css
  ChatSenderBar.tsx         # 顶部发送者 chips（仿 PageWhitelistBar 交互模式）
  ChatCard.tsx              # 单卡组件，按 kind 渲染 quote / batch
  chatCards.ts              # 纯函数 groupIntoCards(msgs, targetSenders, maxN)
  chatCards.test.ts
  chatExport.ts             # buildExportPayload + triggerDownload (Blob)
  chatExport.test.ts

frontend/src/api/chat.ts             # listChatMessages / patchWatchedSenders 薄封装
frontend/src/stores/chatStore.ts     # (page_id, week) 维度缓存 + WS 增量
```

### 主入口分发

在 Dashboard 主区按 `activePage.source` 分发面板：

```tsx
{activePage.source === "chat"
  ? <ChatBoardPanel page={activePage} />
  : <DatabaseRecordsPanel ... />}        /* 现有路径 */
```

`PageInfoBar` 内增加 `if (source === "chat")` 显示 chat 专属元信息（"已抓取 N 条 · 关注 K 位发送者"）。

### `groupIntoCards` 规则

输入：`ChatMessageOut[]`（按 `posted_at` 升序）、`watchedSenders: Set<string>`、`maxN: number`

输出：

```ts
type ChatCard =
  | { kind: "quote";  id: string;   // = target.id
      target: ChatMessageOut; quoted: QuotedRef }
  | { kind: "batch";  id: string;   // = `batch:${msgs[0].id}`
      target_author: string;
      msgs: ChatMessageOut[]; overflow: number }
```

`id` 字段仅供 React key 使用，对消息 id 做最小变形保证唯一。

算法：单次遍历，用一个游标变量记录"当前是否有打开的 batch 卡"。

- `watchedSenders` 为空：视为"全部发送者都关注"
- 遍历到的消息发送者**不在** `watchedSenders`：**跳过整条**（不入卡、**也不打断当前 batch**——这条消息对用户是不可见的，强行打断会让 UI 出现莫名分裂）
- 发送者**在** `watchedSenders`：
  - **有 quote**：close 当前 batch（若有）；push 一张 `kind="quote"` 卡
  - **无 quote**：
    - 满足以下任一时开新 batch 卡：游标无 batch / 上一张是 quote / 上一张 batch 的 `target_author` ≠ 当前作者
    - 当前 batch.msgs.length < maxN：append 进 msgs
    - 当前 batch.msgs.length ≥ maxN：`overflow++`

WS 增量到达时：把新消息插入按 `posted_at` 排序的内存数组，**整体重跑** `groupIntoCards`（量级小 O(n)，可接受）。

### `ChatBoardPanel` 内部数据流

```
WeekPaginator 选周 ─┐
PageSettingsModal  │
里的 watched_senders ├─ chatStore.fetch(page_id, week) ──→ messages[]
chat_card_max_msgs ─┤                                       │
                    │           WS CHAT_MESSAGE_STORED ─────┤
                    │                                       ↓
                    └────────────────── groupIntoCards() → cards[]
                                                            │
                                                            ↓
                                                       <ChatCard />
```

### 导出

`PageActionBar` 在 chat 页面下渲染额外的"导出 JSON"按钮：

```ts
function onExport() {
  const payload = buildExportPayload({
    page, week, watchedSenders,
    messages: cards.flatMap(c => c.kind === "quote"
      ? [c.target]
      : c.msgs).map((m, i) => ({...m, card_index: ...})),
    cards: cards.map((c, i) => ({...c, card_index: i})),
  });
  const blob = new Blob([JSON.stringify(payload, null, 2)],
                       { type: "application/json" });
  const a = Object.assign(document.createElement("a"), {
    href: URL.createObjectURL(blob),
    download: `chat-${page.id}-${week}.json`,
  });
  a.click();
  URL.revokeObjectURL(a.href);
}
```

JSON 结构：

```json
{
  "page_id": "...", "page_name": "...",
  "week": { "start": "...", "end": "..." },
  "watched_senders": ["alice", "bob"],
  "exported_at": "...",
  "cards": [
    { "card_index": 0, "kind": "batch", "target_author": "alice",
      "msg_ids": ["m1","m2","m3"], "overflow": 0 },
    { "card_index": 1, "kind": "quote", "target_msg_id": "m4",
      "quoted": { "author": "bob", "content": "...", "posted_at": "..." } }
  ],
  "messages": [
    { "id": "m1", "author": "alice", "content": "...",
      "posted_at": "...", "card_index": 0 },
    ...
  ]
}
```

### Tweaks

变体已定（C 单列流），不再做面板内布局切换。`chat_card_max_msgs` 在 `PageSettingsModal` 中作为整数步进器编辑，复用现有 PageSettings 模态。

## 错误与边界

| 场景 | 行为 |
|---|---|
| 被引用消息来自更早周 / 非 watched sender | 用 denorm 三字段渲染，`quoted_message_id` 为空就为空 |
| `watched_senders` 为空 | 视为"不过滤"，所有发送者的消息都入卡（quote/batch 规则相同） |
| 该周该页无任何 chat 消息 | 复用 `Dashboard/EmptyState.tsx`，文案"本周无聊天消息 · 切换周或调整发送者过滤" |
| 历史回放 + 实时重复推送 | repo 层 `INSERT ... ON CONFLICT(id) DO NOTHING`；前端 store 用 `id` 去重 |
| target 在 maxN 之后又连续发了 K 条 | 当前 batch 卡显示 maxN 条 + `+K 更多`，不展开为第二张 batch 卡；直到出现 quote / 别人插话切断该段后，下一条 target 消息才开第二张 batch 卡 |
| author 字符串带 emoji / 不可见字符 | 原样存原样展示；`watched_senders` 全字符串等值匹配（不规范化）以避免假阴性 |
| 误改现有 stock/option 页的 source 为 chat | 后端拒绝 `PATCH` 修改 `source`；前端 PageSettingsModal 对已存在页面 disable `source` 字段 |
| 删除 chat 页面 | `ON DELETE CASCADE` 自动清 `chat_messages` |
| WS 断线重连 | 重连后前端拉一次 `GET /chat-messages?week=...` 重建当前周缓存 |

## 测试

### 后端

- `tests/whop/test_listener_chat_branch.py` —— `source="chat"` 页收到消息后发 `CHAT_MESSAGE_RECEIVED`、不进 task 管线；`source="stock"` 仍发 `MESSAGE_RECEIVED`
- `tests/whop/test_chat_writer.py` —— quote denorm 字段填充正确；重复 id 不双写；`is_historical=True` 不广播 `CHAT_MESSAGE_STORED`
- `tests/storage/test_chat_repo.py` —— `list_chat_messages` 周边界 + senders 过滤；`list_chat_authors` 计数正确；`senders=[]` 与 `senders=None` 同义
- `tests/api/test_chat_messages_endpoint.py` —— 返回 shape；未知 page_id → 404；非 chat 类型 page_id → 404 或空（选 404）

### 前端

- `chatCards.test.ts` —— fixture：
  - 纯 batch（M 条同作者无引用）
  - 纯 quote（1 对引用回复）
  - 混合：4 batch + 1 quote + 3 batch → 期望 3 张卡（4 / 1对 / 3）
  - 超过 maxN：N=5 但 7 条 → 1 张卡 + overflow=2
  - 空 watchedSenders（全部入卡）
  - 同一作者中间被 quote 打断 → 拆成两张 batch
  - 同一作者中间被非 watched sender 插话 → 仍是 1 张 batch（插话被跳过、不打断）
  - watched sender A 与 watched sender B 交替无 quote 消息 → A/B/A/B 拆成 4 张 batch（每张 1 条）
- `chatExport.test.ts` —— 同 fixture：`card_index` 单调；`messages` 顺序保持；引用卡的 `target_msg_id` 正确
- `ChatBoardPanel.test.tsx` —— mock API + 渲染快照 + sender chip 切换重渲染
- `ChatSenderBar.test.tsx` —— 添加 / 删除 sender 触发 `PATCH /pages/{id}/settings`

### 端到端

如项目已有 e2e 框架：1 个 happy-path（创 chat 页 → 喂模拟消息 → 看到卡 → 导出 JSON）。否则跳过。

## 不做的事

- 不做 chat 消息全文搜索
- 不做按时间范围（小时/分钟级）的精细过滤
- 不做 quoted 链路的递归展开（quoted of quoted）
- 不做卡片的手动合并/拆分
- 不做发送者改名 / 别名映射
- 不在后端做卡片分组或导出渲染
