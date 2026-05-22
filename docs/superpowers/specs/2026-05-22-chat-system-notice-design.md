# Chat System Notice — Design

**Date:** 2026-05-22
**Branch:** worktree-feat+chat-system-notice

## Problem

The Whop chat panel renders a stream of scraped messages (`watched` + `context` bubbles), but offers no in-panel feedback when the underlying listener transitions in or out of an active state. Users open a page, toggle it on, and stare at an unchanging empty pane wondering whether anything is running. Today only the dashboard's `PageActionBar` power-button surfaces listener state, and that is in a different part of the UI from where the user is actually looking.

We want a lightweight, group-chat-style "system bubble" that appears inside the chat timeline at the moments a listener becomes alive, reconnects, or stops — so the panel itself tells the user "I'm listening" without leaving the chat view.

## Goal

In the chat panel (per Whop page, all three sources — `chat` / `stock` / `option`), insert a centered, color-tinted system bubble at three discrete moments:

- **Joined** — listener.start() succeeded and the **first non-historical message** has arrived. This is what the user picked as the success criterion: the bubble only appears when we have proof that data is actually flowing.
- **Reconnected** — same as Joined, but for restart events (`restart_page`).
- **Left** — `stop_page` was invoked; fires immediately without waiting for any message.

Out of scope (YAGNI):

- Persistence. Notices are pushed via WebSocket only, never written to `chat_message` / a new table. They live in frontend memory; full page refresh clears them. The existing WS hub 500-event ring buffer covers brief reconnects.
- Account-switch / broker-login signals. The previous discussion covered those; they are a separate concern and will be specced independently.
- `errored` / `recovered` transitions from the listener `_loop` (transient self-recovery). The existing `PageActionBar` already paints those; sending them into the chat would be noisy.
- `remove_page` → `left`. Removing a page also removes its panel; sending a final notice into a panel that is about to disappear has no value.
- Folding consecutive notices, animations, hover affordances. The first iteration renders them in linear `ts` order.

## Existing scaffolding (already wired, no changes)

```
backend  app/whop/listener.py        — tracks `_started_at`, computes `is_historical` per message
         app/whop/registry.py        — publishes whop.page_changed { action } for start/stop/restart/added/removed/errored/recovered
         app/api/ws.py               — WebSocketHub bridges domain events → WS clients with ring buffer
frontend src/api/ws.ts               — WS client + auto-reconnect with `?since=<event_id>` replay
         src/App.tsx                 — central event router; routes by `event.type`
         src/components/Chat/        — ChatCard (watched/context), chatTimeline merge
```

Three facts that make this small:

1. The listener already computes `is_historical` for every message (`listener.py` line 325-329). The "first non-historical message after start" pivot is a single boolean flag away.
2. The WS hub's `_payload_to_dict` has a `dict` pass-through (`ws.py:146`), so adding a new payload type is one isinstance branch.
3. The frontend chat already renders multiple bubble variants via a discriminated `BatchItem.kind` (`ChatCard.tsx:18`), so adding a third `"system"` variant is additive, not invasive.

## Design

### 1. New event type

**`backend/app/core/events.py`** adds:

```python
class Topics:
    ...
    CHAT_SYSTEM_NOTICE = "chat.system_notice"

@dataclass(frozen=True)
class ChatSystemNoticePayload:
    page_id: str
    page_name: str          # snapshot at publish time — frontend renders without re-resolving
    source: str             # "chat" | "stock" | "option"
    kind: str               # "joined" | "reconnected" | "left"
    ts: str                 # ISO-8601; joined/reconnected = first message's posted_at, left = now()
```

### 2. Backend emission

#### Joined / reconnected — from the listener

`backend/app/whop/listener.py` `WhopListener.__init__` adds:

```python
self._pending_notice_kind: str | None = notice_kind_on_first_live  # "joined" | "reconnected" | None
self._page_name: str = page_name  # injected by registry from the WhopPageEntry
```

In `_scan_once`, **immediately after** the existing `is_historical` calculation at line 325-329:

```python
if not is_historical and self._pending_notice_kind is not None:
    await self._bus.publish(Event(
        Topics.CHAT_SYSTEM_NOTICE,
        ChatSystemNoticePayload(
            page_id=self._page_id,
            page_name=self._page_name,
            source=self._source,
            kind=self._pending_notice_kind,
            ts=tagged.posted_at.isoformat() if tagged.posted_at else datetime.now(UTC).isoformat(),
        ),
    ))
    self._pending_notice_kind = None  # one-shot per epoch
```

`tagged.posted_at` is `Optional[datetime]`; if `None` we fall back to `now()` so we never miss the bubble.

#### Left — from the registry

`backend/app/whop/registry.py` `stop_page` (after `await listener.stop()`, while still holding the lock to snapshot the entry's display name — the field is `entry.name`, not `entry.title`):

```python
await self._bus.publish(Event(
    Topics.CHAT_SYSTEM_NOTICE,
    ChatSystemNoticePayload(
        page_id=entry.id,
        page_name=entry.name,
        source=entry.source,
        kind="left",
        ts=datetime.now(UTC).isoformat(),
    ),
))
```

`remove_page` does **not** publish — the panel disappears with the page.

#### Selecting `joined` vs `reconnected` at start time

The registry already distinguishes the two paths through different `_start_listener` callers. The `notice_kind_on_first_live` argument plumbs through:

- `start_page` / boot-time auto-start → `"joined"`
- `restart_page` → `"reconnected"`
- `add_page` (initial entry creation that also starts) → `"joined"`

### 3. WS bridge

`backend/app/api/ws.py`:

- Line 75 `topics_to_bridge` adds `Topics.CHAT_SYSTEM_NOTICE`.
- `_payload_to_dict` gets a new branch:

```python
if isinstance(p, ChatSystemNoticePayload):
    return {
        "page_id": p.page_id,
        "page_name": p.page_name,
        "source": p.source,
        "kind": p.kind,
        "ts": p.ts,
    }
```

Notices flow into the existing 500-event ring buffer and replay on reconnect via `?since=<event_id>` like every other topic.

### 4. Frontend

#### New store

`frontend/src/stores/systemNoticesStore.ts` — zustand store (matching the existing store flavor), keyed by `page_id`:

```ts
interface Notice {
  id: string;          // crypto.randomUUID() at receive time
  kind: "joined" | "reconnected" | "left";
  source: "chat" | "stock" | "option";
  ts: string;
}

interface State {
  byPage: Record<string, Notice[]>;
  add(pageId: string, notice: Notice): void;       // dedupe by (page_id, kind, ts)
  clearPage(pageId: string): void;                 // called when page tab closes
}
```

Lives only in memory; no `localStorage`, no IndexedDB.

#### WS routing

`frontend/src/App.tsx` adds a case alongside the existing 4 handlers:

```ts
case "chat.system_notice": {
  const p = event.payload as ChatSystemNoticePayload;
  systemNoticesStore.getState().add(p.page_id, {
    id: crypto.randomUUID(),
    kind: p.kind,
    source: p.source,
    ts: p.ts,
  });
  break;
}
```

#### Timeline merge

`frontend/src/components/Chat/chatTimeline.ts` currently defines:

```ts
type TimelineEntry =
  | { kind: "msg"; msg: ChatMessageOut }
  | { kind: "signal"; task: TaskSummary };   // "signal" here means trading signal (task)
```

Extend with a third variant — name it **`"notice"`** to avoid colliding with the existing `"signal"` (which already means "trading signal / TaskSummary"):

```ts
type TimelineEntry =
  | { kind: "msg"; msg: ChatMessageOut }
  | { kind: "signal"; task: TaskSummary }
  | { kind: "notice"; notice: SystemNotice };
```

`buildTimeline` signature gets a third arg `notices: SystemNotice[]` and stable-sorts all three by `ts asc`. When timestamps tie, **notice entries sort before** msg/signal so the "已开启" bubble visually precedes the message that triggered it.

`buildStreamGroups` (stream/highlight mode) adds a `case "notice"` branch that calls `flush()` then emits a new standalone group `{ kind: "notice"; notice }`. It never merges into a `msgs` run.

`StreamGroup` union gains `{ kind: "notice"; notice: SystemNotice }`.

For card/filter mode (`groupIntoCards`), notices are **not** items inside a `ChatCard.items` — they're top-level interleaved blocks at the same level as cards. The current `groupIntoCards(messages)` keeps operating on `ChatMessageOut[]` only; the panel-level renderer interleaves the resulting `ChatCard[]` with notices by `ts` (using each card's `items[0].posted_at` as the card's sort key). This is the cleanest split — card-internal grouping logic stays untouched, the notice rendering layer is a thin merge step at the boundary.

**No change to `chatCards.ts` `BatchItem`.** Notices are not card-internal items.

#### Bubble component

`frontend/src/components/Chat/SystemNoticeBubble.tsx`:

```tsx
const LABEL: Record<Source, string> = {
  chat: "讨论区监听",
  stock: "正股监听",
  option: "期权监听",
};
const ACTION: Record<Kind, { glyph: string; text: string; cls: string }> = {
  joined:      { glyph: "▶", text: "已开启", cls: "joined" },
  reconnected: { glyph: "↻", text: "已重连", cls: "reconnected" },
  left:        { glyph: "■", text: "已结束", cls: "left" },
};
```

CSS imported from a new block in the existing chat stylesheet — three modifier classes `sys-tinted--joined / --reconnected / --left` using `--ok`, `--info`, `--fg-3` color tokens (matching `.design/chat-system-notice-variants.html` Variant 4):

```css
.sys-tinted--joined {
  background: rgba(var(--ok-rgb), 0.10);
  border: 1px solid rgba(var(--ok-rgb), 0.28);
  color: var(--ok);
}
.sys-tinted--reconnected {
  background: rgba(var(--info-rgb), 0.10);
  border: 1px solid rgba(var(--info-rgb), 0.28);
  color: var(--info);
}
.sys-tinted--left {
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid var(--line);
  color: var(--fg-3);
}
```

If `--ok-rgb` / `--info-rgb` are not in the existing palette, add the rgb-channel variants alongside the existing hex tokens (palette is in the global theme file; one-line addition).

#### Panel integration

`ChatBoardPanel` renders one of two modes today (stream vs card/filter). For both, the rendered list is now `(ChatCard | { kind: "notice"; notice: SystemNotice })[]` (or `StreamGroup[]` extended with `"notice"`). Add the `notice` branch to whichever render switch is in use:

```tsx
{block.kind === "notice" ? (
  <SystemNoticeBubble notice={block.notice} />
) : (
  <ChatCard card={block} />
)}
```

## Data flow (end-to-end)

```
listener.start() with notice_kind_on_first_live="joined"
  → _scan_once finds first message with is_historical=False
    → publish CHAT_SYSTEM_NOTICE { kind: "joined", ts: msg.posted_at, ... }
      → WS hub appends to ring buffer + broadcasts
        → frontend App.tsx receives → systemNoticesStore.add
          → ChatBoardPanel re-renders → chatTimeline merges by ts
            → SystemNoticeBubble paints joined-tinted pill before the triggering message
```

```
registry.stop_page(pid)
  → listener.stop()
  → publish CHAT_SYSTEM_NOTICE { kind: "left", ts: now(), ... }
    → ... → SystemNoticeBubble paints left-tinted pill at the moment of stop
```

## Edge cases

| Situation | Behavior |
|---|---|
| Listener.start() then channel stays silent indefinitely | No `joined` notice fires (intentional — the contract is "first message proves liveness") |
| User clicks stop before any message arrived | Only `left` is shown in the timeline — reflects "started but received nothing" |
| `_loop` enters errored → backs off → recovers | No system notice; `PageActionBar` already paints `errored`/`recovered` state |
| Same page rapidly toggled start → stop → start | Three notices appear in timeline order, no folding |
| Frontend WS drop > ring buffer window | Older notices lost (consistent with the no-persistence decision) |
| Same `ts` between notice and triggering message | Stable sort puts system **before** message |
| `posted_at` missing on first live message | Fall back to `datetime.now(UTC)`; never block the notice on a malformed message |
| Page removed while running | `listener.stop()` runs but no `left` is published (panel disappears) |

## Testing

### Backend (pytest)

- `test_listener_emits_joined_on_first_live_message` — feed two messages, first historical, second live; assert exactly one `CHAT_SYSTEM_NOTICE` with `kind="joined"` ts = second.posted_at.
- `test_listener_no_duplicate_joined_on_subsequent_messages` — feed three live messages; assert exactly one notice.
- `test_listener_emits_reconnected_when_constructed_with_that_flag` — same as joined but `notice_kind_on_first_live="reconnected"`.
- `test_listener_falls_back_to_now_when_posted_at_missing` — first live message has `posted_at=None`; assert notice fires with a recent UTC ts.
- `test_registry_emits_left_on_stop_page` — call `stop_page` on a running entry; assert one `kind="left"` published.
- `test_registry_does_not_emit_left_on_remove_page` — call `remove_page` on a running entry; assert zero `chat.system_notice` events (the existing `whop.page_changed` for `removed` still fires).
- `test_registry_restart_path_constructs_listener_with_reconnected_flag` — verify the plumbing argument, not the listener itself.
- `test_ws_bridge_serialises_payload` — round-trip `ChatSystemNoticePayload` → `_payload_to_dict` → expected JSON.

### Frontend (vitest)

- `chatTimeline.test.ts` — interleave messages, tasks, and notices; assert ts-ascending order with system-before-equal-ts.
- `systemNoticesStore.test.ts` — dedupe by `(page_id, kind, ts)` triple; multiple adds with same triple result in one entry.
- `App.test.tsx` (already exists for WS routing) — add a case for `chat.system_notice` dispatching to the store.

### Manual smoke

1. `make dev`, open a chat-source Whop page, toggle on, wait for first message → see green-tinted `▶ 讨论区监听 已开启 HH:mm`.
2. Click stop → see gray-tinted `■ 讨论区监听 已结束 HH:mm`.
3. Click restart, wait for first new message → see blue-tinted `↻ 讨论区已重连 HH:mm`.
4. Refresh the browser → notices are gone (ephemeral, as designed).
5. Open a stock-source page, repeat → notice text shows "正股监听 …".
6. Open an option-source page → "期权监听 …".

## Reference artifact

`.design/chat-system-notice-variants.html` — final visual matches Variant 4 in that file (color-tinted pill with kind glyph + ts).

## File touch list

**Backend (new code):**

- `backend/app/core/events.py` — add `Topics.CHAT_SYSTEM_NOTICE` + `ChatSystemNoticePayload`
- `backend/app/whop/listener.py` — accept `notice_kind_on_first_live` + `page_name` ctor args; emit on first live message
- `backend/app/whop/registry.py` — pass `notice_kind_on_first_live` in start vs restart paths; publish `left` from `stop_page`
- `backend/app/api/ws.py` — bridge new topic + isinstance branch in `_payload_to_dict`

**Backend (tests):**

- `backend/tests/whop/test_listener_system_notice.py` (new)
- `backend/tests/whop/test_registry_system_notice.py` (new)
- `backend/tests/api/test_ws_system_notice.py` (new, or extend existing ws test)

**Frontend (new code):**

- `frontend/src/stores/systemNoticesStore.ts` (new)
- `frontend/src/components/Chat/SystemNoticeBubble.tsx` (new)
- `frontend/src/components/Chat/chatTimeline.ts` — extend `TimelineEntry` with `"notice"` kind, extend `buildTimeline` signature with `notices: SystemNotice[]`, extend `buildStreamGroups` + `StreamGroup` union with notice branch
- `frontend/src/components/Chat/ChatBoardPanel.tsx` — for card/filter mode, interleave `groupIntoCards(messages)` output with notices by ts; for stream mode, render notice groups directly; render branch dispatching to `<SystemNoticeBubble>`
- `frontend/src/App.tsx` — WS handler case
- `frontend/src/api/ws.ts` or shared types — add `ChatSystemNoticePayload` TS type
- `frontend/src/theme.css` (or wherever palette tokens live) — add `--ok-rgb`, `--info-rgb` if missing
- `frontend/src/components/Chat/chat.css` (or panel stylesheet) — `.sys-tinted` + three modifiers

**Frontend (tests):**

- `frontend/src/components/Chat/__tests__/chatTimeline.test.ts` — extend
- `frontend/src/stores/__tests__/systemNoticesStore.test.ts` (new)

**No DB migration. No schema change.**
