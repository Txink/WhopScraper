# Chat 组件拆分 + UI 快照测试基础设施 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立可复用的 vitest 全量快照 UI 测试基础设施，并把 chat 流的渲染拆为 ChatMessage / StockCard / OptionCard 三个共享 `MessageShell` 外壳的组件，恢复普通消息的 pre-卡片视觉。

**Architecture:** 三层组合 — 低层 `MessageShell` / `PlainBubble` / `SignalBubble`；高层 `ChatMessage` / `StockCard` / `OptionCard`；集中 `frontend/src/test/fixtures.ts` 工厂提供确定性 mock；`StreamView` 重写为薄路由消费三个高层组件。

**Tech Stack:** TypeScript + React 18 + Vitest + jsdom + @testing-library/react + `toMatchSnapshot()`

**Spec:** `docs/superpowers/specs/2026-05-21-chat-component-isolation-and-ui-harness-design.md`

---

## File Structure

**New:**
- `frontend/src/test/fixtures.ts` — 工厂 + 组合场景函数
- `frontend/src/test/fixtures.test.ts` — sanity: 默认值锁定
- `frontend/src/components/Chat/MessageShell.tsx` + `.test.tsx`
- `frontend/src/components/Chat/PlainBubble.tsx` + `.test.tsx`
- `frontend/src/components/Chat/SignalBubble.tsx` + `.test.tsx`（吸收 SignalCard 的渲染）
- `frontend/src/components/Chat/ChatMessage.tsx` + `.test.tsx`
- `frontend/src/components/Chat/StockCard.tsx` + `.test.tsx`
- `frontend/src/components/Chat/OptionCard.tsx` + `.test.tsx`

**Modified:**
- `frontend/src/components/Chat/ChatBoardPanel.css` — 加 `.chat-group.monitor.stock/.option` 着色，删 `.stream-group/.stream-bubble/.chat-stream-head/.stream-body*`
- `frontend/src/components/Chat/StreamView.tsx` — 重写为薄路由
- `frontend/src/components/Chat/StreamView.test.tsx` — 改为路由断言
- `frontend/src/components/Chat/ChatBoardPanel.tsx` — 替换 GroupChatView/SignalCard 引用

**Deleted:**
- `frontend/src/components/Chat/SignalCard.tsx`
- `frontend/src/components/Chat/SignalCard.test.tsx`
- `frontend/src/components/Chat/GroupChatView.tsx`

---

## Task 1: Fixture 工厂模块

**Files:**
- Create: `frontend/src/test/fixtures.ts`
- Test: `frontend/src/test/fixtures.test.ts`

- [ ] **Step 1.1: 创建 `fixtures.ts` 骨架**

```ts
// frontend/src/test/fixtures.ts
import type {
  ChatMessageOut,
  TaskSummary,
  PushEvent,
} from "../api/domain-types";

/** Module-level monotonic counter — reset per fresh import. vitest
 *  isolates modules between test files, so each file starts from 0. */
let _msgN = 0;
let _taskN = 0;
let _pushN = 0;

const BASE_ISO = "2026-05-21T01:00:00Z";

function tickIso(base: string, n: number): string {
  const d = new Date(base);
  d.setUTCMinutes(d.getUTCMinutes() + n);
  return d.toISOString();
}

export function makeMessage(over: Partial<ChatMessageOut> = {}): ChatMessageOut {
  const n = _msgN++;
  return {
    id: `m${n}`,
    page_id: "p",
    author: "alpha",
    content: `msg-${n}`,
    posted_at: tickIso(BASE_ISO, n),
    ...over,
  };
}

export function makeConsecutiveMessages(
  sender: string,
  contents: string[],
): ChatMessageOut[] {
  return contents.map((c) => makeMessage({ author: sender, content: c }));
}

export function makeQuotedMessage(
  author: string,
  content: string,
  quoted: { author: string; content: string },
): ChatMessageOut {
  return makeMessage({
    author,
    content,
    quoted: {
      message_id: null,
      author: quoted.author,
      content: quoted.content,
      posted_at: null,
    },
  });
}

export function makePushEvent(over: Partial<PushEvent> = {}): PushEvent {
  const n = _pushN++;
  return {
    id: n,
    task_id: "t0",
    stage: "submit",
    status: "ok",
    detail: null,
    ts: tickIso(BASE_ISO, n),
    ...over,
  } as PushEvent;
}

export function makeStockTask(over: Partial<TaskSummary> = {}): TaskSummary {
  const n = _taskN++;
  return {
    id: `t${n}`,
    type: "stock",
    status: "FILLED",
    order_id: null,
    stage_timings: {},
    reject_reason: null,
    message: {
      id: `tm${n}`,
      source: "whop",
      author: "TSLL 监听",
      content: "买入 TSLL 200 × 100",
      posted_at: tickIso(BASE_ISO, n),
      received_at: tickIso(BASE_ISO, n),
      url: "https://whop.com/x",
    },
    instruction: {
      type: "stock",
      instruction_type: "BUY",
      ticker: "TSLL",
      symbol: "TSLL.US",
      price: 200,
      quantity: 100,
      price_range: null,
      position_size: null,
      stop_loss_price: null,
      take_profit_price: null,
      context_source: null,
      parser_notes: [],
    },
    last_cum_qty: 100,
    last_cum_avg_price: 199.87,
    created_at: tickIso(BASE_ISO, n),
    updated_at: tickIso(BASE_ISO, n),
    ...over,
  } as TaskSummary;
}

export function makeOptionTask(over: Partial<TaskSummary> = {}): TaskSummary {
  return makeStockTask({
    type: "option",
    message: {
      ...makeStockTask().message,
      author: "NVDA 期权监听",
      content: "NVDA 880C 12/15 × 5",
    },
    instruction: {
      type: "option",
      instruction_type: "BUY",
      ticker: "NVDA",
      symbol: "NVDA.US",
      strike: 880,
      expiry: "2026-12-15",
      option_type: "call",
      price: 5.2,
      quantity: 5,
      price_range: null,
      position_size: null,
      stop_loss_price: null,
      take_profit_price: null,
      context_source: null,
      parser_notes: [],
    },
    ...over,
  } as TaskSummary);
}

export function makeFilledStockTask(over: Partial<TaskSummary> = {}): TaskSummary {
  return makeStockTask({
    status: "FILLED",
    last_cum_qty: 100,
    last_cum_avg_price: 199.87,
    ...over,
  });
}

export function makeFailedParseTask(over: Partial<TaskSummary> = {}): TaskSummary {
  return makeStockTask({
    status: "PARSE_ERROR",
    instruction: null,
    reject_reason: "no match",
    ...over,
  });
}
```

- [ ] **Step 1.2: 写 sanity 测试**

```ts
// frontend/src/test/fixtures.test.ts
import { describe, expect, it } from "vitest";
import {
  makeMessage,
  makeStockTask,
  makeOptionTask,
  makePushEvent,
  makeConsecutiveMessages,
  makeQuotedMessage,
  makeFailedParseTask,
} from "./fixtures";

describe("fixtures defaults are deterministic", () => {
  it("first message has id m0 + default sender alpha", () => {
    const m = makeMessage();
    expect(m.id).toBe("m0");
    expect(m.author).toBe("alpha");
    expect(m.posted_at).toBe("2026-05-21T01:00:00.000Z");
  });

  it("consecutive messages share author and increment time", () => {
    const list = makeConsecutiveMessages("bob", ["hi", "yo"]);
    expect(list.map((m) => m.author)).toEqual(["bob", "bob"]);
    expect(list[0].posted_at).not.toBe(list[1].posted_at);
  });

  it("makeStockTask defaults to FILLED + instruction set", () => {
    const t = makeStockTask();
    expect(t.type).toBe("stock");
    expect(t.status).toBe("FILLED");
    expect(t.instruction?.ticker).toBe("TSLL");
  });

  it("makeOptionTask carries strike/expiry", () => {
    const t = makeOptionTask();
    expect(t.type).toBe("option");
    expect(t.instruction?.strike).toBe(880);
    expect(t.instruction?.expiry).toBe("2026-12-15");
  });

  it("makeFailedParseTask has no instruction + PARSE_ERROR", () => {
    const t = makeFailedParseTask();
    expect(t.status).toBe("PARSE_ERROR");
    expect(t.instruction).toBeNull();
  });

  it("makeQuotedMessage embeds quoted block", () => {
    const m = makeQuotedMessage("a", "same — looking", { author: "b", content: "if we break 470" });
    expect(m.quoted?.author).toBe("b");
    expect(m.quoted?.content).toBe("if we break 470");
  });

  it("makePushEvent returns a sensible default", () => {
    const e = makePushEvent();
    expect(e.stage).toBe("submit");
  });
});
```

- [ ] **Step 1.3: 跑测试，应全绿**

Run: `cd frontend && npm run test -- src/test/fixtures.test.ts`
Expected: 7 passed.

- [ ] **Step 1.4: 跑 typecheck**

Run: `cd frontend && npm run typecheck`
Expected: 0 errors.

- [ ] **Step 1.5: Commit**

```bash
git add frontend/src/test/fixtures.ts frontend/src/test/fixtures.test.ts
git commit -m "test(fixtures): central factory module for chat/task/push fixtures"
```

---

## Task 2: MessageShell 组件

**Files:**
- Create: `frontend/src/components/Chat/MessageShell.tsx`
- Test: `frontend/src/components/Chat/MessageShell.test.tsx`
- Modify: `frontend/src/components/Chat/ChatBoardPanel.css`（加 monitor tone 规则）

- [ ] **Step 2.1: 写 MessageShell 的失败测试**

```tsx
// frontend/src/components/Chat/MessageShell.test.tsx
import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { MessageShell } from "./MessageShell";

describe("MessageShell", () => {
  it("left · default", () => {
    const { container } = render(
      <MessageShell sender="alpha" firstAt="2026-05-21T01:00:00Z" align="left">
        <div className="chat-group-bubble">hello</div>
      </MessageShell>,
    );
    expect(container.innerHTML).toMatchSnapshot();
  });

  it("right · watched sender (iMessage-style)", () => {
    const { container } = render(
      <MessageShell sender="alpha" firstAt="2026-05-21T01:00:00Z" align="right">
        <div className="chat-group-bubble">hello</div>
      </MessageShell>,
    );
    expect(container.innerHTML).toMatchSnapshot();
  });

  it("monitor-stock-tone · author renders in source-stock color", () => {
    const { container } = render(
      <MessageShell
        sender="TSLL 监听"
        firstAt="2026-05-21T01:00:00Z"
        align="left"
        senderTone="stock"
      >
        <div className="signal-bubble stock">…</div>
      </MessageShell>,
    );
    expect(container.innerHTML).toMatchSnapshot();
  });

  it("monitor-option-tone · author renders in source-option color", () => {
    const { container } = render(
      <MessageShell
        sender="NVDA 期权监听"
        firstAt="2026-05-21T01:00:00Z"
        align="left"
        senderTone="option"
      >
        <div className="signal-bubble option">…</div>
      </MessageShell>,
    );
    expect(container.innerHTML).toMatchSnapshot();
  });
});
```

- [ ] **Step 2.2: 跑测试确认失败**

Run: `cd frontend && npm run test -- src/components/Chat/MessageShell.test.tsx`
Expected: FAIL — "Cannot find module './MessageShell'"

- [ ] **Step 2.3: 实现 MessageShell**

```tsx
// frontend/src/components/Chat/MessageShell.tsx
import type React from "react";
import { paletteColorFor } from "./avatarPalette";

export interface MessageShellProps {
  sender: string;
  firstAt: string;
  avatarColor?: string;
  avatarText?: string;
  align: "left" | "right";
  senderTone?: "stock" | "option";
  children: React.ReactNode;
}

function fmtTime(iso: string): string {
  const normalized = /[Zz]|[+-]\d\d:?\d\d$/.test(iso) ? iso : `${iso}Z`;
  const d = new Date(normalized);
  return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

export function MessageShell({
  sender, firstAt, avatarColor, avatarText, align, senderTone, children,
}: MessageShellProps): JSX.Element {
  const cls = [
    "chat-group",
    align === "right" ? "chat-group--right" : null,
    senderTone === "stock" ? "monitor stock" : null,
    senderTone === "option" ? "monitor option" : null,
  ].filter(Boolean).join(" ");

  const bg = avatarColor ?? paletteColorFor(sender);
  const txt = avatarText ?? sender.slice(-1);

  return (
    <div className={cls} data-sender={sender}>
      <div className="chat-group-head">
        <span className="chat-avatar" style={{ background: bg }}>{txt}</span>
        <span className="chat-group-author">{sender}</span>
        <span className="chat-group-time">{fmtTime(firstAt)}</span>
      </div>
      <div className="chat-group-body">{children}</div>
    </div>
  );
}
```

- [ ] **Step 2.4: 加 monitor tone CSS**

Modify `frontend/src/components/Chat/ChatBoardPanel.css` — find the existing `.chat-group-author` rule (around line 104) and add directly below:

```css
.chat-group.monitor.stock  .chat-group-author { color: var(--source-stock); }
.chat-group.monitor.option .chat-group-author { color: var(--source-option); }
```

- [ ] **Step 2.5: 跑测试，应通过并生成快照**

Run: `cd frontend && npm run test -- src/components/Chat/MessageShell.test.tsx`
Expected: 4 passed, snapshots written.

- [ ] **Step 2.6: 人工 review `__snapshots__/MessageShell.test.tsx.snap`**

打开 `frontend/src/components/Chat/__snapshots__/MessageShell.test.tsx.snap`，确认：
- `left · default` 有 `class="chat-group"`、head 三个 span、body 内含 children
- `right` 有 `class="chat-group chat-group--right"`
- `monitor-stock-tone` 有 `class="chat-group monitor stock"`
- `monitor-option-tone` 有 `class="chat-group monitor option"`

- [ ] **Step 2.7: Commit**

```bash
git add frontend/src/components/Chat/MessageShell.tsx \
        frontend/src/components/Chat/MessageShell.test.tsx \
        frontend/src/components/Chat/__snapshots__/MessageShell.test.tsx.snap \
        frontend/src/components/Chat/ChatBoardPanel.css
git commit -m "feat(chat): MessageShell — shared head + body slot with align/tone"
```

---

## Task 3: PlainBubble 组件

**Files:**
- Create: `frontend/src/components/Chat/PlainBubble.tsx`
- Test: `frontend/src/components/Chat/PlainBubble.test.tsx`

- [ ] **Step 3.1: 写 PlainBubble 的失败测试**

```tsx
// frontend/src/components/Chat/PlainBubble.test.tsx
import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { PlainBubble } from "./PlainBubble";

describe("PlainBubble", () => {
  it("short · plain text", () => {
    const { container } = render(<PlainBubble content="hi" />);
    expect(container.innerHTML).toMatchSnapshot();
  });

  it("long · multi-line content", () => {
    const { container } = render(
      <PlainBubble content={"line 1\nline 2\nline 3 with more text"} />,
    );
    expect(container.innerHTML).toMatchSnapshot();
  });

  it("with-quoted · embeds quoted preview", () => {
    const { container } = render(
      <PlainBubble
        content="same — also stalking NVDA 880C"
        quoted={{ author: "alpha", content: "if we break 470 i'm taking calls" }}
      />,
    );
    expect(container.innerHTML).toMatchSnapshot();
  });
});
```

- [ ] **Step 3.2: 跑测试确认失败**

Run: `cd frontend && npm run test -- src/components/Chat/PlainBubble.test.tsx`
Expected: FAIL — module not found.

- [ ] **Step 3.3: 实现 PlainBubble**

```tsx
// frontend/src/components/Chat/PlainBubble.tsx
export interface PlainBubbleProps {
  content: string;
  quoted?: { author: string; content: string } | null;
}

export function PlainBubble({ content, quoted }: PlainBubbleProps): JSX.Element {
  return (
    <div className="chat-group-bubble">
      {quoted && (
        <div className="chat-group-quoted" title={quoted.content}>
          <span className="chat-group-quoted-sender">{quoted.author}</span>
          <span className="chat-group-quoted-body">{quoted.content}</span>
        </div>
      )}
      {content}
    </div>
  );
}
```

- [ ] **Step 3.4: 跑测试，应通过**

Run: `cd frontend && npm run test -- src/components/Chat/PlainBubble.test.tsx`
Expected: 3 passed.

- [ ] **Step 3.5: Commit**

```bash
git add frontend/src/components/Chat/PlainBubble.tsx \
        frontend/src/components/Chat/PlainBubble.test.tsx \
        frontend/src/components/Chat/__snapshots__/PlainBubble.test.tsx.snap
git commit -m "feat(chat): PlainBubble — text bubble with quoted preview"
```

---

## Task 4: SignalBubble 组件（吸收 SignalCard 渲染逻辑）

**Files:**
- Create: `frontend/src/components/Chat/SignalBubble.tsx`
- Test: `frontend/src/components/Chat/SignalBubble.test.tsx`

- [ ] **Step 4.1: 写 SignalBubble 的失败测试**

```tsx
// frontend/src/components/Chat/SignalBubble.test.tsx
import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { SignalBubble } from "./SignalBubble";
import {
  makeStockTask,
  makeOptionTask,
  makeFailedParseTask,
} from "../../test/fixtures";

describe("SignalBubble", () => {
  it("stock-folded · filled order", () => {
    const { container } = render(
      <SignalBubble
        task={makeStockTask()}
        pushEvents={[]}
        expanded={false}
        onToggle={() => {}}
        autoTrade={true}
        variant="stock"
      />,
    );
    expect(container.innerHTML).toMatchSnapshot();
  });

  it("stock-expanded · detail block visible", () => {
    const { container } = render(
      <SignalBubble
        task={makeStockTask()}
        pushEvents={[]}
        expanded={true}
        onToggle={() => {}}
        autoTrade={true}
        variant="stock"
      />,
    );
    expect(container.innerHTML).toMatchSnapshot();
  });

  it("option-folded · contract label 880C 12/15", () => {
    const { container } = render(
      <SignalBubble
        task={makeOptionTask()}
        pushEvents={[]}
        expanded={false}
        onToggle={() => {}}
        autoTrade={true}
        variant="option"
      />,
    );
    expect(container.innerHTML).toMatchSnapshot();
  });

  it("option-expanded · strike/expiry detail visible", () => {
    const { container } = render(
      <SignalBubble
        task={makeOptionTask()}
        pushEvents={[]}
        expanded={true}
        onToggle={() => {}}
        autoTrade={true}
        variant="option"
      />,
    );
    expect(container.innerHTML).toMatchSnapshot();
  });

  it("parse-error · red sig + no ord", () => {
    const { container } = render(
      <SignalBubble
        task={makeFailedParseTask()}
        pushEvents={[]}
        expanded={false}
        onToggle={() => {}}
        autoTrade={true}
        variant="stock"
      />,
    );
    expect(container.innerHTML).toMatchSnapshot();
  });
});
```

- [ ] **Step 4.2: 跑测试确认失败**

Run: `cd frontend && npm run test -- src/components/Chat/SignalBubble.test.tsx`
Expected: FAIL — module not found.

- [ ] **Step 4.3: 实现 SignalBubble（搬运 SignalCard 渲染）**

```tsx
// frontend/src/components/Chat/SignalBubble.tsx
import type { TaskSummary, PushEvent } from "../../api/domain-types";
import { layersForTask } from "./signalCardHelpers";
import { ConfirmActions } from "../Card/ConfirmActions";
import { PushChain } from "../Card/PushChain";
import { fmtBeijingFull } from "../Card/cardHelpers";
import "./SignalCard.css";

export interface SignalBubbleProps {
  task: TaskSummary;
  pushEvents: PushEvent[];
  expanded: boolean;
  onToggle(): void;
  autoTrade: boolean;
  variant: "stock" | "option";
}

export function SignalBubble({
  task, pushEvents, expanded, onToggle, autoTrade, variant,
}: SignalBubbleProps): JSX.Element {
  const layers = layersForTask(task, { autoTrade });
  const sourceClass = layers.kind === "parse_error" ? "neutral" : variant;

  return (
    <div
      className={`signal-bubble ${sourceClass}`}
      data-state={expanded ? "expanded" : "folded"}
      role="button"
      tabIndex={0}
      onClick={(e) => {
        if ((e.target as HTMLElement).closest(".confirm-pair")) return;
        onToggle();
      }}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onToggle();
        }
      }}
    >
      <div className="signal-summary">
        <div className="layer-msg" title={layers.msg}>{layers.msg}</div>

        {layers.sig && (
          <div className="layer-sig">
            {layers.sig.error ? (
              <span className="layer-error">{layers.sig.error}</span>
            ) : (
              <>
                {layers.sig.side && (
                  <span className={`side-chip ${layers.sig.side.toLowerCase()}`}>{layers.sig.side}</span>
                )}
                {layers.sig.ticker && <span className="ticker">{layers.sig.ticker}</span>}
                {layers.sig.contract && <span className="contract">{layers.sig.contract}</span>}
                {layers.sig.price != null && <span className="price">${layers.sig.price.toFixed(2)}</span>}
                {layers.sig.quantity != null && (
                  <span className="qty">× {layers.sig.quantity}{variant === "option" ? " 张" : ""}</span>
                )}
                {layers.sig.showConfirmActions && (
                  <span className="confirm-pair">
                    <ConfirmActions taskId={task.id} variant="compact" />
                  </span>
                )}
              </>
            )}
          </div>
        )}

        {layers.ord && (
          <div className="layer-ord">
            <span className={`state-dot ${layers.ord.dot}`} />
            <span className="state-text">{layers.ord.text}</span>
            {layers.ord.cum && <span className="cum">{layers.ord.cum}</span>}
            <span className="expander">▾</span>
          </div>
        )}
      </div>

      {expanded && (
        <div className="signal-detail">
          <div className="detail-block">
            <div className="detail-label">MSG · 原始消息</div>
            <div className="detail-meta">
              domID {task.message.id} · posted {fmtBeijingFull(task.message.posted_at)}
              {task.message.url && (
                <> · <a href={task.message.url} target="_blank" rel="noopener noreferrer">url ↗</a></>
              )}
            </div>
          </div>
          {task.instruction && layers.sig && !layers.sig.error && (
            <div className="detail-block">
              <div className="detail-label">SIG · 解析指令</div>
              <div className="detail-meta">
                {layers.sig.ctx && <>ctx = {layers.sig.ctx}</>}
                {layers.sig.parseDeltaMs != null && (
                  <> · parse +{layers.sig.parseDeltaMs.toFixed(3)}ms</>
                )}
                {variant === "option" && task.instruction.strike != null && (
                  <> · strike {task.instruction.strike}</>
                )}
                {variant === "option" && task.instruction.expiry && (
                  <> · expiry {task.instruction.expiry}</>
                )}
              </div>
            </div>
          )}
          {(pushEvents.length > 0 || task.order_id) && (
            <div className="detail-block">
              <div className="detail-label">ORD · 推送链</div>
              <PushChain
                events={pushEvents}
                taskStatus={task.status}
                totalQty={task.instruction?.quantity}
                submitOrderId={task.order_id ?? null}
                submitEndIso={null}
              />
            </div>
          )}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 4.4: 跑测试，应通过**

Run: `cd frontend && npm run test -- src/components/Chat/SignalBubble.test.tsx`
Expected: 5 passed, snapshots written.

- [ ] **Step 4.5: Commit**

```bash
git add frontend/src/components/Chat/SignalBubble.tsx \
        frontend/src/components/Chat/SignalBubble.test.tsx \
        frontend/src/components/Chat/__snapshots__/SignalBubble.test.tsx.snap
git commit -m "feat(chat): SignalBubble — 3-layer signal rendering (stock/option variant)"
```

---

## Task 5: ChatMessage 组件

**Files:**
- Create: `frontend/src/components/Chat/ChatMessage.tsx`
- Test: `frontend/src/components/Chat/ChatMessage.test.tsx`

- [ ] **Step 5.1: 写失败测试**

```tsx
// frontend/src/components/Chat/ChatMessage.test.tsx
import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ChatMessage } from "./ChatMessage";
import {
  makeMessage,
  makeConsecutiveMessages,
  makeQuotedMessage,
} from "../../test/fixtures";

describe("ChatMessage", () => {
  it("single · one bubble under one head", () => {
    const m = makeMessage({ author: "alpha", content: "hi" });
    const { container } = render(
      <ChatMessage
        sender="alpha"
        firstAt={m.posted_at}
        messages={[m]}
        align="left"
      />,
    );
    expect(container.innerHTML).toMatchSnapshot();
  });

  it("consecutive-3-msgs · three bubbles share one head", () => {
    const list = makeConsecutiveMessages("bob", ["first", "second", "third"]);
    const { container } = render(
      <ChatMessage
        sender="bob"
        firstAt={list[0].posted_at}
        messages={list}
        align="left"
      />,
    );
    expect(container.innerHTML).toMatchSnapshot();
  });

  it("right-aligned · watched sender renders chat-group--right", () => {
    const m = makeMessage({ author: "carol", content: "watched-msg" });
    const { container } = render(
      <ChatMessage
        sender="carol"
        firstAt={m.posted_at}
        messages={[m]}
        align="right"
      />,
    );
    expect(container.innerHTML).toMatchSnapshot();
  });

  it("with-quoted · embeds quoted preview in bubble", () => {
    const m = makeQuotedMessage("alpha", "agreed", { author: "bob", content: "long NVDA" });
    const { container } = render(
      <ChatMessage
        sender="alpha"
        firstAt={m.posted_at}
        messages={[m]}
        align="left"
      />,
    );
    expect(container.innerHTML).toMatchSnapshot();
  });
});
```

- [ ] **Step 5.2: 跑测试确认失败**

Run: `cd frontend && npm run test -- src/components/Chat/ChatMessage.test.tsx`
Expected: FAIL — module not found.

- [ ] **Step 5.3: 实现 ChatMessage**

```tsx
// frontend/src/components/Chat/ChatMessage.tsx
import type { ChatMessageOut } from "./chatCards";
import { MessageShell } from "./MessageShell";
import { PlainBubble } from "./PlainBubble";

export interface ChatMessageProps {
  sender: string;
  firstAt: string;
  messages: ChatMessageOut[];
  align: "left" | "right";
}

export function ChatMessage({
  sender, firstAt, messages, align,
}: ChatMessageProps): JSX.Element {
  return (
    <MessageShell sender={sender} firstAt={firstAt} align={align}>
      {messages.map((m) => (
        <PlainBubble key={m.id} content={m.content} quoted={m.quoted ?? null} />
      ))}
    </MessageShell>
  );
}
```

- [ ] **Step 5.4: 跑测试**

Run: `cd frontend && npm run test -- src/components/Chat/ChatMessage.test.tsx`
Expected: 4 passed.

- [ ] **Step 5.5: Commit**

```bash
git add frontend/src/components/Chat/ChatMessage.tsx \
        frontend/src/components/Chat/ChatMessage.test.tsx \
        frontend/src/components/Chat/__snapshots__/ChatMessage.test.tsx.snap
git commit -m "feat(chat): ChatMessage — Shell + N×PlainBubble for consecutive messages"
```

---

## Task 6: StockCard 组件

**Files:**
- Create: `frontend/src/components/Chat/StockCard.tsx`
- Test: `frontend/src/components/Chat/StockCard.test.tsx`

- [ ] **Step 6.1: 写失败测试**

```tsx
// frontend/src/components/Chat/StockCard.test.tsx
import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { StockCard } from "./StockCard";
import {
  makeStockTask,
  makeFailedParseTask,
} from "../../test/fixtures";

describe("StockCard", () => {
  it("folded · filled order", () => {
    const { container } = render(
      <StockCard
        monitorName="TSLL 监听"
        task={makeStockTask()}
        pushEvents={[]}
        expanded={false}
        onToggle={() => {}}
        autoTrade={true}
        align="left"
      />,
    );
    expect(container.innerHTML).toMatchSnapshot();
  });

  it("expanded · detail visible inside shell", () => {
    const { container } = render(
      <StockCard
        monitorName="TSLL 监听"
        task={makeStockTask()}
        pushEvents={[]}
        expanded={true}
        onToggle={() => {}}
        autoTrade={true}
        align="left"
      />,
    );
    expect(container.innerHTML).toMatchSnapshot();
  });

  it("parse-error · red sig", () => {
    const { container } = render(
      <StockCard
        monitorName="TSLL 监听"
        task={makeFailedParseTask()}
        pushEvents={[]}
        expanded={false}
        onToggle={() => {}}
        autoTrade={true}
        align="left"
      />,
    );
    expect(container.innerHTML).toMatchSnapshot();
  });

  it("order-pending · INSTRUCTION_READY shows confirm pair when autoTrade=false", () => {
    const { container } = render(
      <StockCard
        monitorName="TSLL 监听"
        task={makeStockTask({ status: "INSTRUCTION_READY" })}
        pushEvents={[]}
        expanded={false}
        onToggle={() => {}}
        autoTrade={false}
        align="left"
      />,
    );
    expect(container.innerHTML).toMatchSnapshot();
  });
});
```

- [ ] **Step 6.2: 跑测试确认失败**

Run: `cd frontend && npm run test -- src/components/Chat/StockCard.test.tsx`
Expected: FAIL — module not found.

- [ ] **Step 6.3: 实现 StockCard**

```tsx
// frontend/src/components/Chat/StockCard.tsx
import type { TaskSummary, PushEvent } from "../../api/domain-types";
import { MessageShell } from "./MessageShell";
import { SignalBubble } from "./SignalBubble";

export interface StockCardProps {
  monitorName: string;
  task: TaskSummary;
  pushEvents: PushEvent[];
  expanded: boolean;
  onToggle(): void;
  autoTrade: boolean;
  align: "left" | "right";
}

export function StockCard({
  monitorName, task, pushEvents, expanded, onToggle, autoTrade, align,
}: StockCardProps): JSX.Element {
  return (
    <MessageShell
      sender={monitorName}
      firstAt={task.message.posted_at}
      align={align}
      senderTone="stock"
    >
      <SignalBubble
        task={task}
        pushEvents={pushEvents}
        expanded={expanded}
        onToggle={onToggle}
        autoTrade={autoTrade}
        variant="stock"
      />
    </MessageShell>
  );
}
```

- [ ] **Step 6.4: 跑测试**

Run: `cd frontend && npm run test -- src/components/Chat/StockCard.test.tsx`
Expected: 4 passed.

- [ ] **Step 6.5: Commit**

```bash
git add frontend/src/components/Chat/StockCard.tsx \
        frontend/src/components/Chat/StockCard.test.tsx \
        frontend/src/components/Chat/__snapshots__/StockCard.test.tsx.snap
git commit -m "feat(chat): StockCard — Shell + SignalBubble[variant=stock]"
```

---

## Task 7: OptionCard 组件

**Files:**
- Create: `frontend/src/components/Chat/OptionCard.tsx`
- Test: `frontend/src/components/Chat/OptionCard.test.tsx`

- [ ] **Step 7.1: 写失败测试**

```tsx
// frontend/src/components/Chat/OptionCard.test.tsx
import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { OptionCard } from "./OptionCard";
import { makeOptionTask } from "../../test/fixtures";

describe("OptionCard", () => {
  it("folded · contract label 880C 12/15", () => {
    const { container } = render(
      <OptionCard
        monitorName="NVDA 期权监听"
        task={makeOptionTask()}
        pushEvents={[]}
        expanded={false}
        onToggle={() => {}}
        autoTrade={true}
        align="left"
      />,
    );
    expect(container.innerHTML).toMatchSnapshot();
  });

  it("expanded · strike/expiry detail visible", () => {
    const { container } = render(
      <OptionCard
        monitorName="NVDA 期权监听"
        task={makeOptionTask()}
        pushEvents={[]}
        expanded={true}
        onToggle={() => {}}
        autoTrade={true}
        align="left"
      />,
    );
    expect(container.innerHTML).toMatchSnapshot();
  });
});
```

- [ ] **Step 7.2: 跑测试确认失败**

Run: `cd frontend && npm run test -- src/components/Chat/OptionCard.test.tsx`
Expected: FAIL — module not found.

- [ ] **Step 7.3: 实现 OptionCard**

```tsx
// frontend/src/components/Chat/OptionCard.tsx
import type { TaskSummary, PushEvent } from "../../api/domain-types";
import { MessageShell } from "./MessageShell";
import { SignalBubble } from "./SignalBubble";

export interface OptionCardProps {
  monitorName: string;
  task: TaskSummary;
  pushEvents: PushEvent[];
  expanded: boolean;
  onToggle(): void;
  autoTrade: boolean;
  align: "left" | "right";
}

export function OptionCard({
  monitorName, task, pushEvents, expanded, onToggle, autoTrade, align,
}: OptionCardProps): JSX.Element {
  return (
    <MessageShell
      sender={monitorName}
      firstAt={task.message.posted_at}
      align={align}
      senderTone="option"
    >
      <SignalBubble
        task={task}
        pushEvents={pushEvents}
        expanded={expanded}
        onToggle={onToggle}
        autoTrade={autoTrade}
        variant="option"
      />
    </MessageShell>
  );
}
```

- [ ] **Step 7.4: 跑测试**

Run: `cd frontend && npm run test -- src/components/Chat/OptionCard.test.tsx`
Expected: 2 passed.

- [ ] **Step 7.5: Commit**

```bash
git add frontend/src/components/Chat/OptionCard.tsx \
        frontend/src/components/Chat/OptionCard.test.tsx \
        frontend/src/components/Chat/__snapshots__/OptionCard.test.tsx.snap
git commit -m "feat(chat): OptionCard — Shell + SignalBubble[variant=option]"
```

---

## Task 8: StreamView 重写为薄路由

**Files:**
- Modify: `frontend/src/components/Chat/StreamView.tsx`
- Modify: `frontend/src/components/Chat/StreamView.test.tsx`
- Modify: `frontend/src/components/Chat/ChatBoardPanel.css`（删 `.stream-*` 块）

- [ ] **Step 8.1: 改写 `StreamView.test.tsx` 为路由断言**

```tsx
// frontend/src/components/Chat/StreamView.test.tsx
import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { StreamView } from "./StreamView";
import type { StreamGroup } from "./chatTimeline";
import {
  makeMessage,
  makeStockTask,
  makeOptionTask,
} from "../../test/fixtures";

function groups(): StreamGroup[] {
  const m1 = makeMessage({ author: "alpha", content: "hi" });
  const m2 = makeMessage({ author: "alpha", content: "again" });
  return [
    { kind: "msgs", sender: "alpha", entries: [m1, m2] },
    { kind: "signal", sender: "TSLL 监听", task: makeStockTask() },
    { kind: "signal", sender: "NVDA 期权监听", task: makeOptionTask() },
  ];
}

describe("StreamView routing", () => {
  it("msg group → ChatMessage (chat-group without monitor class)", () => {
    const { container } = render(
      <StreamView
        groups={groups()}
        watched={new Set()}
        pushEventsByTask={{}}
        expandedTaskId={null}
        onToggleTask={() => {}}
        autoTrade={true}
      />,
    );
    const msgGroup = container.querySelector('[data-sender="alpha"]');
    expect(msgGroup?.className).toBe("chat-group");
  });

  it("stock signal group → StockCard (chat-group.monitor.stock)", () => {
    const { container } = render(
      <StreamView
        groups={groups()}
        watched={new Set()}
        pushEventsByTask={{}}
        expandedTaskId={null}
        onToggleTask={() => {}}
        autoTrade={true}
      />,
    );
    const node = container.querySelector('[data-sender="TSLL 监听"]');
    expect(node?.classList.contains("monitor")).toBe(true);
    expect(node?.classList.contains("stock")).toBe(true);
  });

  it("option signal group → OptionCard (chat-group.monitor.option)", () => {
    const { container } = render(
      <StreamView
        groups={groups()}
        watched={new Set()}
        pushEventsByTask={{}}
        expandedTaskId={null}
        onToggleTask={() => {}}
        autoTrade={true}
      />,
    );
    const node = container.querySelector('[data-sender="NVDA 期权监听"]');
    expect(node?.classList.contains("monitor")).toBe(true);
    expect(node?.classList.contains("option")).toBe(true);
  });

  it("watched sender → align=right (chat-group--right)", () => {
    const { container } = render(
      <StreamView
        groups={groups()}
        watched={new Set(["alpha"])}
        pushEventsByTask={{}}
        expandedTaskId={null}
        onToggleTask={() => {}}
        autoTrade={true}
      />,
    );
    const node = container.querySelector('[data-sender="alpha"]');
    expect(node?.classList.contains("chat-group--right")).toBe(true);
  });

  it("empty groups → no children", () => {
    const { container } = render(
      <StreamView
        groups={[]}
        watched={new Set()}
        pushEventsByTask={{}}
        expandedTaskId={null}
        onToggleTask={() => {}}
        autoTrade={true}
      />,
    );
    expect(container.querySelectorAll(".chat-group")).toHaveLength(0);
  });
});
```

- [ ] **Step 8.2: 跑测试确认（基于旧 StreamView）失败**

Run: `cd frontend && npm run test -- src/components/Chat/StreamView.test.tsx`
Expected: FAIL — 旧 StreamView 用的是 `.stream-group / .chat-stream-head / .stream-bubble`，新断言查 `.chat-group` 找不到。

- [ ] **Step 8.3: 重写 StreamView.tsx**

```tsx
// frontend/src/components/Chat/StreamView.tsx
import type { PushEvent } from "../../api/domain-types";
import type { StreamGroup } from "./chatTimeline";
import { ChatMessage } from "./ChatMessage";
import { StockCard } from "./StockCard";
import { OptionCard } from "./OptionCard";

export interface StreamViewProps {
  groups: StreamGroup[];
  watched: Set<string>;
  pushEventsByTask: Record<string, PushEvent[]>;
  expandedTaskId: string | null;
  onToggleTask(taskId: string): void;
  autoTrade: boolean;
}

export function StreamView({
  groups, watched, pushEventsByTask, expandedTaskId, onToggleTask, autoTrade,
}: StreamViewProps): JSX.Element {
  return (
    <div className="stream-view">
      {groups.map((g, i) => {
        const align: "left" | "right" = watched.has(g.sender) ? "right" : "left";
        if (g.kind === "msgs") {
          return (
            <ChatMessage
              key={`${i}-${g.sender}`}
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
            key={`${i}-${g.sender}`}
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
}
```

- [ ] **Step 8.4: 删除 `.stream-group / .chat-stream-head / .stream-bubble / .stream-body` 等 CSS 块**

Open `frontend/src/components/Chat/ChatBoardPanel.css` — delete the block from `/* ── Stream view (highlight mode) ── */` (around line 328) through the end of the stream-related rules (around line 400, right before `/* ── Monitor sender chips */`). Keep `.stream-view` itself as the outer flex column:

```css
.stream-view {
  display: flex; flex-direction: column;
  gap: 14px;
}
```

The rules to delete (these classes are no longer rendered after Task 8.3):
- `.stream-group { ... }`
- `.chat-stream-head { ... }` (including `.stream-group.watched` and `.stream-group.monitor.*` variants)
- `.stream-body { ... }` (including watched variant)
- `.stream-bubble { ... }` (including watched variant)
- `.stream-body .signal-bubble { ... }` (align variants)
- `.board[data-mode="highlight"] .stream-group:not(.watched) { ... }` (and its hover)

- [ ] **Step 8.5: 跑 StreamView 测试**

Run: `cd frontend && npm run test -- src/components/Chat/StreamView.test.tsx`
Expected: 5 passed.

- [ ] **Step 8.6: 跑 typecheck**

Run: `cd frontend && npm run typecheck`
Expected: 0 errors.

- [ ] **Step 8.7: Commit**

```bash
git add frontend/src/components/Chat/StreamView.tsx \
        frontend/src/components/Chat/StreamView.test.tsx \
        frontend/src/components/Chat/ChatBoardPanel.css
git commit -m "refactor(chat): StreamView routes to ChatMessage/StockCard/OptionCard"
```

---

## Task 9: ChatBoardPanel 路径合并

**Files:**
- Modify: `frontend/src/components/Chat/ChatBoardPanel.tsx`

- [ ] **Step 9.1: 替换 SignalCard 引用 + 删除 GroupChatView 路径**

Open `frontend/src/components/Chat/ChatBoardPanel.tsx`. Make four edits:

**Edit A — imports（第 17-22 行附近）:**

Replace:
```ts
import { groupIntoCards } from "./chatCards";
import { ChatCard } from "./ChatCard";
import { ChatSenderBar } from "./ChatSenderBar";
import { GroupChatView } from "./GroupChatView";
import { buildTimeline, buildFilterBlocks, buildStreamGroups } from "./chatTimeline";
import { SignalCard } from "./SignalCard";
import { StreamView } from "./StreamView";
```

With:
```ts
import { groupIntoCards } from "./chatCards";
import { ChatCard } from "./ChatCard";
import { ChatSenderBar } from "./ChatSenderBar";
import { buildTimeline, buildFilterBlocks, buildStreamGroups } from "./chatTimeline";
import { StockCard } from "./StockCard";
import { OptionCard } from "./OptionCard";
import { StreamView } from "./StreamView";
```

**Edit B — filter mode aggregate body：** find the block:

```tsx
          <div className="chat-thread">
            {b.tasks.map((t) => (
              <div key={t.id} className="chat-row">
                <SignalCard
                  task={t}
                  pushEvents={pushEventsByTask[t.id] ?? []}
                  expanded={expandedSignalId === t.id}
                  onToggle={() => toggleSignal(t.id)}
                  autoTrade={autoTrade}
                />
              </div>
            ))}
          </div>
```

Replace with:

```tsx
          <div className="chat-thread">
            {b.tasks.map((t) => {
              const Card = t.type === "option" ? OptionCard : StockCard;
              const monitorName =
                urlToMonitorName[t.message.url ?? ""] ?? "(unknown)";
              return (
                <Card
                  key={t.id}
                  monitorName={monitorName}
                  task={t}
                  pushEvents={pushEventsByTask[t.id] ?? []}
                  expanded={expandedSignalId === t.id}
                  onToggle={() => toggleSignal(t.id)}
                  autoTrade={autoTrade}
                  align="left"
                />
              );
            })}
          </div>
```

**Edit C — highlight / fallback routing：** find the trailing `else` branch (around line 261-282) that picks between GroupChatView and StreamView, replace the whole block:

```tsx
  } else {
    // Highlight mode or no watched senders → stream view.
    // If there are no child tasks and no watched senders, fall back to the
    // original GroupChatView so the pure-chat path is unchanged.
    if (childTasks.length === 0 && watchedSenders.length === 0) {
      body = <GroupChatView messages={messages} />;
    } else if (childTasks.length === 0 && mode === "highlight") {
      body = <GroupChatView messages={messages} watched={watchedSet} />;
    } else {
      const groups = buildStreamGroups(timeline, urlToMonitorName);
      body = (
        <StreamView
          groups={groups}
          watched={watchedSet}
          pushEventsByTask={pushEventsByTask}
          expandedTaskId={expandedSignalId}
          onToggleTask={toggleSignal}
          autoTrade={autoTrade}
        />
      );
    }
  }
```

With:

```tsx
  } else {
    // Highlight mode or no watched senders → stream view.
    // All routes go through StreamView, which internally renders ChatMessage
    // for chat-msg groups and StockCard/OptionCard for signal groups.
    const groups = buildStreamGroups(timeline, urlToMonitorName);
    body = (
      <StreamView
        groups={groups}
        watched={watchedSet}
        pushEventsByTask={pushEventsByTask}
        expandedTaskId={expandedSignalId}
        onToggleTask={toggleSignal}
        autoTrade={autoTrade}
      />
    );
  }
```

- [ ] **Step 9.2: 跑全套测试**

Run: `cd frontend && npm run test`
Expected: all pass (含 ChatBoardPanel 的整合不会回归)。

- [ ] **Step 9.3: 跑 typecheck**

Run: `cd frontend && npm run typecheck`
Expected: 0 errors.

- [ ] **Step 9.4: Commit**

```bash
git add frontend/src/components/Chat/ChatBoardPanel.tsx
git commit -m "refactor(chat): ChatBoardPanel — drop GroupChatView path, use StockCard/OptionCard in aggregate"
```

---

## Task 10: 清理死代码

**Files:**
- Delete: `frontend/src/components/Chat/SignalCard.tsx`
- Delete: `frontend/src/components/Chat/SignalCard.test.tsx`
- Delete: `frontend/src/components/Chat/__snapshots__/SignalCard.test.tsx.snap` (if exists)
- Delete: `frontend/src/components/Chat/GroupChatView.tsx`

- [ ] **Step 10.1: 确认无残余引用**

Run:
```bash
cd /Users/tianpengxuan/Documents/signal-station/frontend && \
  grep -rn "from.*['\"].*SignalCard['\"]" src/ ; \
  grep -rn "from.*['\"].*GroupChatView['\"]" src/
```

Expected: 无输出 (除了被删除的文件本身的 self-reference)。

如果有遗漏，回到 Task 9 修正后再继续。

- [ ] **Step 10.2: 删除文件**

```bash
rm frontend/src/components/Chat/SignalCard.tsx \
   frontend/src/components/Chat/SignalCard.test.tsx \
   frontend/src/components/Chat/GroupChatView.tsx
# Snapshot file may not exist; -f ignores missing
rm -f frontend/src/components/Chat/__snapshots__/SignalCard.test.tsx.snap
```

- [ ] **Step 10.3: 跑全套测试 + typecheck**

Run:
```bash
cd frontend && npm run test && npm run typecheck
```

Expected: all pass; 0 type errors.

- [ ] **Step 10.4: Commit**

```bash
git add -A frontend/src/components/Chat/
git commit -m "refactor(chat): delete SignalCard.tsx + GroupChatView.tsx (replaced)"
```

---

## Task 11: 最终验收

- [ ] **Step 11.1: 跑全套测试**

Run: `cd frontend && npm run test`
Expected: 所有测试通过。Specifically expect ~20+ new snapshot tests pass.

- [ ] **Step 11.2: 跑 typecheck**

Run: `cd frontend && npm run typecheck`
Expected: 0 errors.

- [ ] **Step 11.3: 跑 build（捕获生产构建期错误）**

Run: `cd frontend && npm run build`
Expected: 构建成功，无新增 lint 警告。

- [ ] **Step 11.4: 启动 dev 服务器人工 smoke**

Run: `cd frontend && npm run dev`

打开 http://localhost:5173，进到一个 chat page，验证：
1. 普通聊天消息用 `.chat-group-bubble` 样式（font-size:13px，宽度贴合内容，最大 600px）
2. 切到 highlight 模式 → 监听 stock/option 的信号在流里有 head 三连（avatar + 名 + 时间），下面是 signal-bubble
3. watched 一个人类 → 他的消息右对齐（chat-group--right）
4. 切回 filter 模式 + 多 watched → aggregate ∑ 卡片内每条是 StockCard/OptionCard

- [ ] **Step 11.5: 检查快照清单**

Run:
```bash
ls frontend/src/components/Chat/__snapshots__/
```

Expected: 至少包含
- `MessageShell.test.tsx.snap`
- `PlainBubble.test.tsx.snap`
- `SignalBubble.test.tsx.snap`
- `ChatMessage.test.tsx.snap`
- `StockCard.test.tsx.snap`
- `OptionCard.test.tsx.snap`

且**不**包含 `SignalCard.test.tsx.snap`。

- [ ] **Step 11.6: 检查死 CSS 已删除**

Run:
```bash
grep -n "\.stream-group\|\.chat-stream-head\|\.stream-bubble\|\.stream-body" \
  frontend/src/components/Chat/ChatBoardPanel.css
```

Expected: 无匹配（`.stream-view` 还在，作为外层容器）。

- [ ] **Step 11.7: 最终 commit（如有必要）**

如果 smoke 过程中有微调，commit 之；否则跳过。

---

## 验收清单（来自 spec）

- [ ] 普通消息在 chat 流里恢复 `.chat-group-bubble` 样式 → Task 3 + Task 11.4
- [ ] watched 发送者的消息右对齐 (`.chat-group--right`) → Task 5 right-aligned snapshot + Task 8.1 watched test
- [ ] 正股 / 期权信号在流里与普通消息共享 head 三连 → Task 6/7 + Task 8 path
- [ ] filter 模式 aggregate 卡片内每条信号是 `StockCard` / `OptionCard` → Task 9 Edit B
- [ ] `frontend/src/test/fixtures.ts` 工厂可用 → Task 1
- [ ] ~20+ 稳定快照；`npm run test` 全绿 → Task 11.1
- [ ] `npm run typecheck` 全绿；旧 `SignalCard.tsx` / `GroupChatView.tsx` 已删除 → Task 10 + Task 11.2
- [ ] `ChatBoardPanel.css` 中 `.stream-bubble` / `.chat-stream-head` 等死代码已清 → Task 8.4 + Task 11.6
