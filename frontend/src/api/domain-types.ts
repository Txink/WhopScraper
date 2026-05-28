// frontend/src/api/domain-types.ts
// Re-exports common schema types under shorter names for ergonomic DX.
// Auto-derived from openapi-typescript output — regenerate via: npm run gen:types
import type { components } from "./types";

export type Task = components["schemas"]["TaskOut"];
export type TaskSummary = components["schemas"]["TaskSummaryOut"];
export type TaskList = components["schemas"]["TaskListOut"];
export type Message = components["schemas"]["MessageOut"];
export type Instruction = components["schemas"]["InstructionOut"];
export type InstructionLabel = components["schemas"]["InstructionLabelOut"];
export type CorrectedInstruction = components["schemas"]["CorrectedInstruction"];
export type PushEvent = components["schemas"]["PushEventOut"];
// Position extended with ``name`` until next ``npm run gen:types``. The
// backend already returns ``name`` (symbol display name from the broker)
// — needed for HK / A-share positions whose ticker is numeric and useless
// without the company name.
export type Position = components["schemas"]["PositionOut"] & {
  name?: string | null;
};
export type Positions = components["schemas"]["PositionsOut"];
export type StatsToday = components["schemas"]["StatsTodayOut"];
export type Health = components["schemas"]["HealthOut"];

export type Quote = components["schemas"]["QuoteOut"];
export type Quotes = components["schemas"]["QuotesOut"];
export type Candlestick = components["schemas"]["CandlestickOut"];
export type Candlesticks = components["schemas"]["CandlesticksOut"];
// Trade extended with ``symbol`` and ``t_pair_tags`` until next
// ``npm run gen:types``. The backend already returns both:
//   - symbol: options on the same ticker share a ticker but have distinct
//     symbols, so per-contract Day P/L needs this.
//   - t_pair_tags: ``[[pair_id, allocated_qty], ...]`` — denormalized做T
//     allocation list maintained by the pair CRUD layer. Empty array
//     means the trade is fully open for做T binding.
export type Trade = components["schemas"]["TradeOut"] & {
  symbol?: string | null;
  t_pair_tags?: [number, number][];
};

/** Broker-side order (one row per order_id, partial fills aggregated:
 *  qty=sum, price=weighted-avg, ts=latest). Source of truth for Day P/L
 *  and 做T binding. ``task_id`` is non-null only when the order was
 *  submitted by signal-station's own trader — manual fills via the
 *  LongBridge app / web have task_id=null. */
export interface Execution {
  order_id: string;
  task_id?: string | null;
  symbol: string;
  ticker: string;
  side: "BUY" | "SELL";
  qty: number;
  price: number;
  ts: string;
}

export interface Executions {
  executions: Execution[];
  /** Wall-clock moment of the most recent broker→DB sync write for the
   *  returned slice. Detail pane shows "上次更新：xxx". Null on first
   *  fetch before any sync has completed. */
  last_synced_at?: string | null;
  /** Total fills matching the request's filters (account/ticker/window),
   *  ignoring offset/limit. Lets the UI render "已加载 M / N · 加载更多". */
  total_count: number;
  /** ``true`` when more rows exist past the returned page. The trade list
   *  uses this to decide whether to render the "加载更多" affordance. */
  has_more: boolean;
}
export type Trades = components["schemas"]["TradesOut"];
// TPair extended with v2 fields (``id: number``, ``profit: number``)
// until next ``npm run gen:types``. Backend now uses SQLite-native
// autoincrement INTEGER ids and persists realized做T profit on the row.
export type TPair = Omit<components["schemas"]["TPairOut"], "id"> & {
  id: number;
  profit: number;
};
export type TPairs = Omit<components["schemas"]["TPairsOut"], "pairs"> & {
  pairs: TPair[];
};
export type TPairAllocation = components["schemas"]["TPairAllocation"];
export type TPairCreate = components["schemas"]["TPairCreate"];
export type TPairExtendIn = components["schemas"]["TPairExtendIn"];

/** Aggregate做T stats for a (account, ticker) — sourced from
 *  ``GET /api/pairs/aggregate``. Server computes via SQL SUM/COUNT, so
 *  DetailSummary's做T row can render without pulling every pair into memory. */
export interface PairAggregate {
  profit_total: number;
  count: number;
  win_count: number;
}

/** One row of "pending做T" trade — broker fill with remaining qty not
 *  yet allocated to any pair. Sourced from
 *  ``GET /api/broker/executions/pending``. */
export interface PendingTrade {
  order_id: string;
  ticker: string;
  symbol: string;
  side: "BUY" | "SELL";
  qty: number;
  allocated_qty: number;
  pending_qty: number;
  price: number;
  ts: string;
}

export interface PendingExecutions {
  pending_buy_qty: number;
  pending_sell_qty: number;
  trades: PendingTrade[];
}

export type BrokerStatus = components["schemas"]["BrokerStatusOut"];

// Extend the OpenAPI-generated types with parser_version until the next
// `npm run gen:types` regeneration. The `?` keeps existing fixtures (which
// omit the field) valid; the backend defaults to "v1".
export type WhopPageSettings = components["schemas"]["WhopPageSettingsOut"] & {
  parser_version?: "v1" | "v2";
};
export type WhopPageSettingsPatch = components["schemas"]["WhopPageSettingsPatch"] & {
  parser_version?: "v1" | "v2";
};
export type WhopPage = Omit<components["schemas"]["WhopPageOut"], "settings"> & {
  settings: WhopPageSettings;
  /** Set when this page is a sub-monitor under a chat parent.
   *  Null / undefined means top-level. Until the next ``npm run gen:types``
   *  regen, this extension carries the new field client-side. */
  parent_chat_id?: string | null;
};
export type WhopPages = components["schemas"]["WhopPagesOut"];
export type WhopPageCreate = components["schemas"]["WhopPageCreate"] & {
  parent_chat_id?: string | null;
};
export type WhopCookieStatus = components["schemas"]["WhopCookieStatusOut"];
export type TickerConfig = components["schemas"]["TickerConfigOut"];

/**
 * Multi-account-era LongBridge account slot. ``account_id`` is the
 * registered OAuth client_id (stable per Longbridge account).
 * ``authorized`` reflects whether the SDK token cache holds a valid
 * token. ``label`` is the user-chosen display name.
 */
export interface LongportAccount {
  account_id: string;
  label: string;
  authorized: boolean;
}

export interface LongportSettings {
  active_account_id: string | null;
  accounts: LongportAccount[];
  auto_trade: boolean;
  region: string;
  dry_run: boolean;
}

/** PATCH-able subset (flags only). Account list is managed via the OAuth
 *  endpoints below. */
export interface LongportSettingsPatch {
  auto_trade?: boolean;
  region?: string;
  dry_run?: boolean;
}

export interface LongportOAuthStartOut {
  session_id: string;
  auth_url: string;
  account_id: string;
}

export type LongportOAuthState =
  | "awaiting_url"
  | "ready"
  | "success"
  | "error"
  | "cancelled";

export interface LongportOAuthStatus {
  state: LongportOAuthState;
  error?: string | null;
  account_id?: string | null;
}
