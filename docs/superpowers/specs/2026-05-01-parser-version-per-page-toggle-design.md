---
date: 2026-05-01
topic: parser-version per-page toggle
status: design
---

# parser_version per-page toggle — Design

## Goal

让运营方在前端 `PageSettingsModal` 给每个 whop page 单独勾选是否走 `parser_v2`，**实时生效，无需重启 backend、也无需重启 listener**。默认 v1，opt-in v2。

## Non-Goals

- 不改 option parser（v2 只覆盖 stock；option page 上即便存了 `parser_version="v2"` 也不会生效）。
- 不在本次改动里 flip `app/parser_v2/__init__.py` 的 alias。alias flip 由 plan `2026-04-27-parser-v2-token-based-plan.md` 的最后一个 task 完成；本设计的 toggle 在 alias flip 前是 no-op，flip 后自动生效。
- 不增加任何"哪条消息用了哪个 parser"的运维 UI（telemetry 走结构化日志即可）。
- 不引入全局 / per-trader 粒度（已在 brainstorming 阶段否决）。

## Architecture

`PageSettings` 增加字段 `parser_version: Literal["v1", "v2"] = "v1"`。

`parser/service.py` 已经在每条 stock 消息进入时调用 `registry.get_settings_for_url(msg.url)`（`service.py:82-85`）。把这次查找的结果向上提到 try 块外层公用，然后在解析分支按 `page_settings.parser_version` 选 `stock_parser.parse` 或 `parser_v2.parse`。

`registry.update_settings`（`registry.py:329`）走 `page_settings_from_dict` 容忍合并 + `_save_entries` 落盘，无需新增持久化路径。容忍 `from_dict` 让历史 settings 文件无 `parser_version` 字段时自动 fallback 到 `"v1"`，向后兼容。

实时性：service 每条消息都重读 settings；PATCH 完成后下一条消息就走新 parser。零延迟、零重启、零 WebSocket 推送。

## Data Flow

```
[FE] PageSettingsModal 勾选 "使用 parser v2"
  → PATCH /api/whop/pages/{id}/settings { parser_version: "v2" }
[BE] http.py:542 patch_whop_page_settings 把 body 转成 patch_dict
  → registry.update_settings(page_id, {"parser_version": "v2"})
  → page_settings_from_dict 容忍合并入 entry.settings
  → registry._save_entries 持久化到 JSON
  → 发布 settings_updated 事件
[BE] 下一条 stock 消息进 parser/service._handle_message_received
  → registry.get_settings_for_url(msg.url) 返回 settings.parser_version="v2"
  → 走 parser_v2.parse(msg.content, message_id=msg.id)
  → log.info("parsed", extra={"parser_version": "v2", "message_id": ..., "elapsed_ms": ...})
```

## File Map

### Backend

#### Modify: `backend/app/whop/page_settings.py`

1. `PageSettings` dataclass 加字段：
   ```python
   parser_version: Literal["v1", "v2"] = "v1"
   ```
2. `DEFAULT_STOCK_SETTINGS` / `DEFAULT_OPTION_SETTINGS` 显式 `parser_version="v1"`（与 default 一致，但显式更清晰）。
3. `default_settings_for("stock"|"option")` 各自传 `parser_version=...DEFAULT.parser_version`。
4. `page_settings_to_dict` 加 `"parser_version": s.parser_version`。
5. `page_settings_from_dict` 加：
   ```python
   pv_raw = d.get("parser_version", base.parser_version)
   parser_version: Literal["v1", "v2"] = "v2" if pv_raw == "v2" else "v1"
   ```
   未知字符串 fallback 到 `"v1"`，避免脏数据导致解析失败。

#### Modify: `backend/app/parser/service.py`

把现有 `service.py:82-85` 的 page_settings 查找上提到 try 之外、`watched` 之前。结构（pseudo）：

```python
page_settings: PageSettings | None = None
watched: set[str] = set()
if msg.source == "stock" and registry is not None:
    page_settings = registry.get_settings_for_url(msg.url)
    if page_settings is not None and page_settings.tickers:
        watched = set(page_settings.tickers.keys())

started = time.perf_counter()

try:
    parsed: Instruction | None
    if msg.source == "stock":
        if page_settings is not None and page_settings.parser_version == "v2":
            from app.parser_v2 import parse as parser_v2_parse
            parsed = parser_v2_parse(msg.content, message_id=msg.id)
            parser_version_used = "v2"
        else:
            parsed = stock_parser.parse(msg.content, message_id=msg.id)
            parser_version_used = "v1"
    else:
        parsed = option_parser.parse(...)
        parser_version_used = None  # option 无此概念
```

成功 / 失败 / 异常三个分支的日志都加 `extra={"parser_version": parser_version_used}`（用 `logger.info(..., extra=...)` 模式）。具体行号在实现 plan 里挑。

#### Modify: `backend/app/api/schemas.py`

```python
# WhopPageSettingsOut
parser_version: Literal["v1", "v2"] = "v1"

# WhopPageSettingsPatch
parser_version: Literal["v1", "v2"] | None = None
```

#### Modify: `backend/app/api/http.py`

1. `whop_settings_defaults` (`http.py:515-540`) 在 `WhopPageSettingsOut(...)` 构造里加一行 `parser_version=s.parser_version`。
2. `patch_whop_page_settings` (`http.py:542+`) 在 patch_dict 收集块加：
   ```python
   if body.parser_version is not None:
       patch_dict["parser_version"] = body.parser_version
   ```
3. `whop_page_to_out`（`schemas.py:510-532` 的 helper）—— 在 `WhopPageSettingsOut(...)` 构造里加一行 `parser_version=entry.settings.parser_version`。这是仓库里两个 `WhopPageSettingsOut(` 构造点之一（另一个是上面的 `whop_settings_defaults`），改完即覆盖所有出口。

### Frontend

#### Modify: `frontend/src/api/domain-types.ts`

`WhopPageSettings` 类型加：
```ts
parser_version?: "v1" | "v2";
```

#### Modify: `frontend/src/components/Dashboard/PageSettingsModal.tsx`

照 `launch_headless` 的模式：
1. 加 state `const [parserV2, setParserV2] = useState(page.settings.parser_version === "v2");`
2. 表单里加一个 checkbox：`使用 parser v2（实验）`
3. save 时：`parser_version: parserV2 ? "v2" : "v1"`

### Tests

#### Backend

- `backend/tests/whop/test_page_settings.py`（已存在）加 case：
  - `from_dict({"parser_version": "v2"}, source="stock")` → `parser_version == "v2"`
  - `from_dict({}, source="stock")` → `parser_version == "v1"`（向后兼容）
  - `from_dict({"parser_version": "garbage"}, source="stock")` → `"v1"`（未知值 fallback）
  - `to_dict(PageSettings(parser_version="v2"))` 包含 `"parser_version": "v2"`

- `backend/tests/api/` PATCH 路由集成测试加 case：body `{"parser_version": "v2"}` → 返回 `WhopPageOut.settings.parser_version == "v2"`，再次 GET 仍是 `"v2"`。

- `backend/tests/parser/test_service.py`（或新建）
  - mock registry 返回 `PageSettings(parser_version="v2")` → 验证 `parser_v2.parse` 被调用
  - mock registry 返回 `PageSettings(parser_version="v1")` 或 None → 验证 `stock_parser.parse` 被调用
  - option 消息：`parser_version` 字段被忽略，走 `option_parser.parse`

#### Frontend

- `frontend/src/components/Dashboard/PageSettingsModal.test.tsx` 加：
  - "toggling parser_version saves it as v2" —— mirror 现有 `toggling launch_headless saves it`
  - 默认（initial state v1）勾选后 PATCH body 包含 `parser_version: "v2"`
  - initial state v2 取消勾选后 PATCH body 包含 `parser_version: "v1"`

## Edge Cases & Decisions

| 场景 | 行为 |
|------|------|
| Settings 文件已存在但无 `parser_version` 字段 | `from_dict` 容忍缺失 → 默认 `"v1"`，向后兼容 |
| `parser_version="v2"` 但 alias 还没 flip | toggle 是 no-op；两条路径走同一个 `parse` 函数。日志里 `parser_version` 仍如实记录 |
| Option page 设了 `parser_version` | 字段持久化但不生效，`service.py` 只在 stock 分支查 |
| 用户在消息高峰期切换 | 由于 settings 在 service 层每条消息读一次，不存在"半切"状态。但已经在飞行中、未到 service 层的消息会走旧 parser，这是预期行为 |
| Settings JSON 文件被外部工具改成 `"parser_version": "v3"` | `from_dict` 把未知值 fallback 到 `"v1"`，不抛异常 |
| Restart backend | settings 已经持久化在 JSON 里，重启后状态保留 |

## Telemetry

`parser/service.py` 解析成功 / 失败 / 异常三处日志加 `extra={"parser_version": "v1"|"v2"|None}`。便于后续在结构化日志里 group-by parser_version 比较：
- 解析时延 `elapsed_ms` 分布
- 失败率
- 触发 chatter 的比例

不引入新指标 schema；如果以后要做 dashboard 把这个抽到 metrics 是另一个 spec。

## Out of Scope

- 把 `parser_v2.__init__.py` 从 v1 alias flip 成真实实现（plan `2026-04-27-parser-v2-token-based-plan.md` 负责）
- option parser 的 v2
- 任何 dashboard / 监控 UI 来展示某条消息使用了哪个 parser
- 全局或 per-trader 粒度的 toggle
- 把 telemetry 抽成 Prometheus metrics

## Risk

- **小**：纯加字段 + 新 if 分支，对 v1 路径零影响。
- alias 还没 flip 时 toggle 看不出效果，可能让人困惑。**Mitigation**：UI label 标 "（实验）"，并在 PR 描述写清楚 alias flip 的依赖关系。
