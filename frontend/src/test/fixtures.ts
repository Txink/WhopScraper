// frontend/src/test/fixtures.ts
import type { TaskSummary, PushEvent } from "../api/domain-types";
import type { ChatMessageOut } from "../components/Chat/chatCards";

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
    id: `e${n}`,
    task_id: "t0",
    order_id: "order-0",
    state: "submit",
    received_at: tickIso(BASE_ISO, n),
    delta_qty: null,
    delta_price: null,
    cumulative_qty: null,
    cumulative_avg_price: null,
    note: null,
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
      raw_content: "买入 TSLL 200 × 100",
      posted_at: tickIso(BASE_ISO, n),
      received_at: tickIso(BASE_ISO, n),
      url: "https://whop.com/x",
      quoted_message_id: null,
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
