# 图片消息:跳过指令解析,当作图片展示

**Date:** 2026-05-29
**Status:** Design approved, pending spec review

## 目标

当正股(stock)或期权(option)消息带有图片时,**不再走指令解析**,而是把它当作「图片消息」展示。当前这类消息会被当成解析失败,显示红色的「未解析 · 正则未匹配」气泡。

## 当前行为

1. 抓取阶段 `whop/extractor.py` 已经会提取附件里的 whop 图片 URL 并填到领域 `Message.image_url`(stock/option/chat 三种来源都填)。图片消息通常 `content=""`、`image_url="<whop url>"`。
2. `parser/service.py` 的 `_handle_message_received`:对每条 MESSAGE_RECEIVED 都创建 Task、标记 PARSING,然后**无条件**按 source 跑正则解析(`msg.content`)。空 content → 正则失败 → 上下文兜底也失败 → `task.mark_parse_failed("无法解析为交易指令")` → 终态 **PARSE_ERROR**。
3. 前端任务路径(stock/option 消息只通过 Task 到达前端):`StockCard`/`OptionCard` → `SignalBubble` → `layersForTask` 命中 `PARSE_ERROR` → 渲染「未解析 · 正则未匹配」。

### 已有的图片管线(聊天来源)

- 下载:`whop/chat_writer.py::_download_image(msg_id, url, data_dir)` 用 `httpx` 拉取(whop 图片是公开 CDN,**无需鉴权**),按 Content-Type 映射扩展名,存到 `<data_dir>/chat-images/{msg_id}{ext}`,返回文件名;失败返回 `None` 且不阻断流程。
- 存储:`chat_messages` 表有 `image_filename` 列(迁移 `d250c4f32ccf`)。
- 服务:`GET /api/chat-images/{message_id}` 查 `ChatMessageRow` → 校验路径在 chat-images 目录内 → `FileResponse`。
- 前端:`PlainBubble`(仅聊天来源)已能渲染图片 `<img className="chat-group-image" src={authedAssetUrl(imageUrl)}>`,`ChatMessageOut.image_url = "/api/chat-images/{id}"`(有 filename 时)。

### 关键缺口

- stock/option 的 `MessageRow` 表**没有**图片列,领域 `Message.image_url` 持久化时被丢弃。
- 任务路径的 `MessageOut` schema **没有** `image_url` 字段(只有聊天路径的 `ChatMessageOut` 有)。

## 决策(已与用户确认)

- **判定规则**:只要 `msg.image_url` 有值就算图片消息(图文混合也跳过解析)。
- **适用来源**:stock 和 option 都适用。
- **展示**:复用现有图片气泡样式。
- **图片加载**:复用服务端下载/代理(与聊天图片一致),不直连 whop URL。
- **任务状态**:复用 **SKIPPED**(`reason="图片消息"`)。前端靠 `image_url` 识别图片气泡,状态仅用于后端记账。

## 架构 / 数据流

```
抓取 (extractor 设置 msg.image_url)
  → parser/service 收到 MESSAGE_RECEIVED, 创建 Task, mark_parsing
     └─ 若 msg.image_url 不为空:
          • download_image(msg.id, msg.image_url, data_dir) → image_filename
          • msg = replace(msg, image_filename=...)
          • task.mark_skipped("图片消息")   ← 不跑解析, 直接 return
          • 发 TASK skip 事件
  → save_task 持久化 image_filename 到 MessageRow
  → API: MessageOut.image_url = "/api/messages/{id}/image" (有 filename 时)
  → 前端: layersForTask 检测 message.image_url → kind:"image" → SignalBubble 渲染图片气泡
```

## 后端改动

1. **抽出共享下载工具**:把 `_download_image()` 从 `chat_writer.py` 提到共享模块(如 `app/whop/image_store.py`),chat 与 stock/option 共用。沿用 `<data_dir>/chat-images/` 目录与 `{msg_id}{ext}` 命名(避免迁移已有文件)。`chat_writer.py` 改为调用共享函数。
2. **领域 `Message`**(`app/domain/message.py`):新增 `image_filename: str | None = None`。
3. **`MessageRow`**(`app/storage/schema.py`):新增 `image_filename: Mapped[str | None]` 列 + Alembic 迁移(照搬 chat_messages 的迁移)。
4. **`parser/service._handle_message_received`**:在创建 task、`mark_parsing` 之后、按 source 解析之前插入:
   - `if msg.image_url is not None:` → `filename = await download_image(...)`;`msg = dataclasses.replace(msg, image_filename=filename)`;`task.mark_skipped("图片消息")`;发 skip 事件;**return**(不跑解析)。
   - stock 与 option 同一处理(检测与 source 无关)。
5. **`storage/repo`**(`_message_to_row` / `save_task`):持久化 `image_filename`(messages 行除 url 外原本不可变,需允许写入 image_filename)。
6. **`MessageOut`**(`app/api/schemas.py`):新增 `image_url: str | None`,值 = `/api/messages/{id}/image`(有 image_filename 时,否则 None),与 `ChatMessageOut` 对称。
   - **必须**在所有 `MessageOut(...)` 构造点补字段:领域转换器 `message_to_out`、REST 列表端点的 row→out 路径、以及测试夹具。实现前先 `grep "MessageOut("` 与 `message_to_out` 全部用例。
   - 领域转换需要 image_filename → 由步骤 2 的 `Message.image_filename` 提供;row→out 路径由步骤 3 的列提供。
7. **新端点 `GET /api/messages/{id}/image`**(`app/api/http.py`):镜像 `/api/chat-images/{id}` —— 查 `MessageRow` → 校验 `image_filename` 非空 → 解析路径并校验在 images 目录内(防路径逃逸)→ 校验文件存在 → `FileResponse(media_type=...)`。复用现有 `_IMAGE_MEDIA_TYPES` 映射。

## 前端改动

8. **重新生成类型**:`npm run gen:types`(获得 `MessageOut.image_url`)。
9. **`signalCardHelpers.layersForTask`**:在最前面(`PARSE_ERROR`/状态判断之前)加:`if (task.message.image_url)` → 返回 `kind: "image"`,携带 `imageUrl` 与 `content`(图文混合时的文字)。`CardLayers.kind` 类型新增 `"image"`。
10. **`SignalBubble`**:当 `kind === "image"` 时渲染图片气泡(复用 `<img className="chat-group-image" src={authedAssetUrl(imageUrl)}>` + 文字 caption),不渲染 sig/ord/解析层。`StockCard` 与 `OptionCard` 都包 `SignalBubble`,自动生效。

## 边界情况

- **下载失败**(网络/超时):`image_filename` 为空 → 仍 `mark_skipped("图片消息")`;前端 `image_url` 为 null,退化为轻量「图片消息」占位或仅显示 caption,**绝不再显示解析报错**。
- **图文混合**:图片 + 文字都显示,不解析。
- **历史消息**(`is_historical`):走同一路径。
- **存量旧数据**:本次改动前已 PARSE_ERROR 的图片消息无 image_filename、状态 PARSE_ERROR,仍显示「未解析」。**不做回填**(YAGNI)。
- **真实 SKIPPED**(人工/规则跳过):无 `image_url`,前端照旧显示「已跳过」,不受影响。

## 测试

- 后端
  - `parser/service`:带 `image_url` 的 stock 与 option 消息 → 不解析、task 为 SKIPPED(reason=图片消息)、`image_filename` 被持久化。
  - 下载失败时仍 SKIPPED、image_filename 为 None、不报 PARSE_ERROR。
  - `MessageOut` 字段转发:列表端点(row→out)与领域转换器都带 `image_url`。
  - serve 端点:正常返回图片;缺 filename / 文件不存在 / 路径逃逸 → 404(照搬 chat-images 测试)。
- 前端
  - `signalCardHelpers`:带 `image_url` 的 task → `kind:"image"`;无图片的 PARSE_ERROR/SKIPPED 行为不变。
  - `SignalBubble`:`kind:"image"` 渲染 `<img>` + caption(更新快照)。

## 不在本次范围

- 旧 PARSE_ERROR 图片消息的回填。
- 图片点击放大 / 灯箱(沿用 PlainBubble 现有交互即可)。
- 复用下载工具时的连接池优化(每次新建 httpx client 即可,与现状一致)。
