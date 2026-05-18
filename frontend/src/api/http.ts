import type {
  Task, TaskList, Positions, StatsToday, Health,
  WhopPage, WhopPages, WhopPageCreate, WhopCookieStatus,
  WhopPageSettings, WhopPageSettingsPatch, LongportSettings, LongportSettingsPatch,
  LongportOAuthStartOut, LongportOAuthStatus,
  BrokerStatus,
  Quotes, Candlesticks, Trades, Executions,
  TPairs, TPair, TPairCreate, TPairExtendIn,
  PairAggregate, PendingExecutions,
} from "./domain-types";


interface HttpConfig {
  baseUrl: string;
  token: string;
}

let _config: HttpConfig | null = null;

export function configureHttp(config: HttpConfig): void {
  _config = config;
}

/** Test-only: reset module singleton so tests are fully isolated. */
export function __resetForTests(): void {
  _config = null;
}

function cfg(): HttpConfig {
  if (!_config) throw new Error("http not configured (call configureHttp first)");
  return _config;
}


export class HttpError extends Error {
  constructor(
    public status: number,
    public body: unknown,
    message: string,
  ) {
    super(message);
    this.name = "HttpError";
  }
}


async function request<T>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const { baseUrl, token } = cfg();
  const url = new URL(path, baseUrl);
  // Token via query param so WS + REST share the same auth surface
  url.searchParams.set("token", token);

  const resp = await fetch(url.toString(), {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init.headers || {}),
    },
  });

  if (!resp.ok) {
    let body: unknown = null;
    try { body = await resp.json(); } catch { body = await resp.text().catch(() => null); }
    throw new HttpError(resp.status, body, `HTTP ${resp.status} ${resp.statusText}`);
  }

  return resp.json() as Promise<T>;
}


export interface DbRowsResponse {
  table: string;
  columns: string[];
  rows: unknown[][];
  total: number;
}


export const api = {
  async listTasks(params: {
    limit?: number;
    cursor?: string;
    status?: string;
    type?: string;
    symbol?: string;
  } = {}): Promise<TaskList> {
    const qs = new URLSearchParams();
    if (params.limit !== undefined) qs.set("limit", String(params.limit));
    if (params.cursor) qs.set("cursor", params.cursor);
    if (params.status) qs.set("status", params.status);
    if (params.type) qs.set("type", params.type);
    if (params.symbol) qs.set("symbol", params.symbol);
    const suffix = qs.toString() ? `?${qs.toString()}` : "";
    return request<TaskList>(`/api/tasks${suffix}`);
  },

  async countTasks(params: {
    status?: string;
    type?: string;
    symbol?: string;
  } = {}): Promise<{ total_count: number }> {
    const qs = new URLSearchParams();
    if (params.status) qs.set("status", params.status);
    if (params.type) qs.set("type", params.type);
    if (params.symbol) qs.set("symbol", params.symbol);
    const suffix = qs.toString() ? `?${qs.toString()}` : "";
    return request<{ total_count: number }>(`/api/tasks/count${suffix}`);
  },

  async listDbRows(
    table: string,
    params: { limit?: number; offset?: number } = {},
  ): Promise<DbRowsResponse> {
    const qs = new URLSearchParams();
    if (params.limit !== undefined) qs.set("limit", String(params.limit));
    if (params.offset !== undefined) qs.set("offset", String(params.offset));
    const suffix = qs.toString() ? `?${qs.toString()}` : "";
    return request<DbRowsResponse>(`/api/db/${encodeURIComponent(table)}${suffix}`);
  },

  async getTask(id: string): Promise<Task> {
    return request<Task>(`/api/tasks/${encodeURIComponent(id)}`);
  },

  async cancelTask(id: string): Promise<{ ok: boolean }> {
    return request(`/api/tasks/${encodeURIComponent(id)}/cancel`, { method: "POST" });
  },

  async confirmTask(id: string): Promise<Task> {
    return request<Task>(`/api/tasks/${encodeURIComponent(id)}/confirm`, { method: "POST" });
  },

  async skipTask(id: string): Promise<Task> {
    return request<Task>(`/api/tasks/${encodeURIComponent(id)}/skip`, { method: "POST" });
  },

  async stats(): Promise<StatsToday> {
    return request<StatsToday>("/api/stats/today");
  },

  async positions(): Promise<Positions> {
    return request<Positions>("/api/positions");
  },

  async health(): Promise<Health> {
    return request<Health>("/api/health");
  },

  async getLongportSettings(): Promise<LongportSettings> {
    return request<LongportSettings>("/api/longport/settings");
  },

  async updateLongportSettings(patch: LongportSettingsPatch): Promise<LongportSettings> {
    return request<LongportSettings>("/api/longport/settings", {
      method: "PATCH",
      body: JSON.stringify(patch),
    });
  },

  async getBrokerStatus(): Promise<BrokerStatus> {
    return request<BrokerStatus>("/api/longport/broker/status");
  },

  async reloadBroker(): Promise<BrokerStatus> {
    return request<BrokerStatus>("/api/longport/broker/reload", { method: "POST" });
  },

  /** OAuth: start a fresh authorize flow to add a new account slot. The
   *  SDK opens a local callback server; user authorizes in browser. */
  async startLongportOauth(): Promise<LongportOAuthStartOut> {
    return request<LongportOAuthStartOut>("/api/longport/oauth/start", {
      method: "POST",
      body: JSON.stringify({}),
    });
  },

  /** Poll the OAuth session until state flips from ``ready`` to
   *  ``success`` (user finished) or ``error`` / ``cancelled``. */
  async longportOauthStatus(sessionId: string): Promise<LongportOAuthStatus> {
    return request<LongportOAuthStatus>(
      `/api/longport/oauth/status?session_id=${encodeURIComponent(sessionId)}`,
    );
  },

  /** Set the active account. UI is responsible for invoking
   *  /broker/reload + refreshing positions after this returns. */
  async activateLongportAccount(accountId: string): Promise<LongportSettings> {
    return request<LongportSettings>("/api/longport/oauth/activate", {
      method: "POST",
      body: JSON.stringify({ account_id: accountId }),
    });
  },

  /** Remove an account: scrub local token cache + drop from list. */
  async logoutLongportAccount(accountId: string): Promise<LongportSettings> {
    return request<LongportSettings>("/api/longport/oauth/logout", {
      method: "POST",
      body: JSON.stringify({ account_id: accountId }),
    });
  },

  /** Rename an account label. */
  async renameLongportAccount(
    accountId: string,
    label: string,
  ): Promise<LongportSettings> {
    return request<LongportSettings>("/api/longport/oauth/account", {
      method: "PATCH",
      body: JSON.stringify({ account_id: accountId, label }),
    });
  },

  async listWhopPages(): Promise<WhopPages> {
    return request<WhopPages>("/api/whop/pages");
  },

  async addWhopPage(body: WhopPageCreate): Promise<WhopPage> {
    return request<WhopPage>("/api/whop/pages", {
      method: "POST",
      body: JSON.stringify(body),
    });
  },

  async removeWhopPage(id: string): Promise<void> {
    const { baseUrl, token } = cfg();
    const url = new URL(`/api/whop/pages/${encodeURIComponent(id)}`, baseUrl);
    url.searchParams.set("token", token);
    const resp = await fetch(url.toString(), { method: "DELETE" });
    if (!resp.ok) {
      const body = await resp.json().catch(() => null);
      throw new HttpError(resp.status, body, `HTTP ${resp.status}`);
    }
  },

  async restartWhopPage(id: string): Promise<WhopPage> {
    return request<WhopPage>(`/api/whop/pages/${encodeURIComponent(id)}/restart`, {
      method: "POST",
    });
  },

  async startWhopPage(id: string): Promise<WhopPage> {
    return request<WhopPage>(`/api/whop/pages/${encodeURIComponent(id)}/start`, {
      method: "POST",
    });
  },

  async stopWhopPage(id: string): Promise<WhopPage> {
    return request<WhopPage>(`/api/whop/pages/${encodeURIComponent(id)}/stop`, {
      method: "POST",
    });
  },

  async updateWhopPageSettings(
    id: string,
    patch: WhopPageSettingsPatch,
  ): Promise<WhopPage> {
    return request<WhopPage>(
      `/api/whop/pages/${encodeURIComponent(id)}/settings`,
      { method: "PATCH", body: JSON.stringify(patch) },
    );
  },

  async whopPageSettingsDefaults(source: "stock" | "option"): Promise<WhopPageSettings> {
    return request<WhopPageSettings>(
      `/api/whop/pages/defaults?source=${encodeURIComponent(source)}`,
    );
  },

  async whopCookieStatus(): Promise<WhopCookieStatus> {
    return request<WhopCookieStatus>("/api/whop/cookie");
  },

  async cleanupOrphanByUrl(url: string | null): Promise<{ deleted_count: number }> {
    return request<{ deleted_count: number }>(
      "/api/whop/orphan/cleanup",
      { method: "POST", body: JSON.stringify({ url }) },
    );
  },

  /** Force-clean an active page's history (used by 设置弹窗 "清空本页历史"). */
  async cleanupPageHistory(url: string): Promise<{ deleted_count: number }> {
    return request<{ deleted_count: number }>(
      "/api/whop/orphan/cleanup",
      { method: "POST", body: JSON.stringify({ url, force: true }) },
    );
  },

  // -------------------------------------------------------------------------
  // Simulator — exercises real bus → parser → DB → WS pipeline with
  // prebuilt scenarios so the operator can preview UI behaviour without
  // making real broker calls.
  // -------------------------------------------------------------------------

  async listSimScenarios(): Promise<{ scenarios: SimScenarioOverview[] }> {
    return request<{ scenarios: SimScenarioOverview[] }>("/api/sim/scenarios");
  },

  async runSimScenario(name: string): Promise<SimRunResult> {
    return request<SimRunResult>(
      `/api/sim/run/${encodeURIComponent(name)}`,
      { method: "POST" },
    );
  },

  // -------------------------------------------------------------------------
  // Quotes / candlesticks / per-ticker trades — backing data for the
  // positions card grid + detail pane (chart, trade list, 做T binding).
  // -------------------------------------------------------------------------

  async quotes(symbols: string[]): Promise<Quotes> {
    if (symbols.length === 0) return { quotes: [] };
    const qs = new URLSearchParams({ symbols: symbols.join(",") });
    return request<Quotes>(`/api/quote?${qs.toString()}`);
  },

  async candlesticks(
    symbol: string,
    period: "today" | "5" | "7" | "30" | "day" | "week" | "month" | "year" = "today",
    opts: {
      // Only used when period === "today"; ignored otherwise.
      granularity?: "分时" | "1min" | "2min" | "3min" | "5min";
      sessions?: "regular" | "pre" | "post" | "overnight" | "all";
      /** ISO timestamp — when set, fetch bars older than this. Backend
       *  rejects `before` for the today period; only day/week/month/
       *  year support it. */
      before?: string;
    } = {},
  ): Promise<Candlesticks> {
    const qs = new URLSearchParams({ symbol, period });
    if (opts.granularity) qs.set("granularity", opts.granularity);
    if (opts.sessions) qs.set("sessions", opts.sessions);
    if (opts.before) qs.set("before", opts.before);
    return request<Candlesticks>(`/api/candlesticks?${qs.toString()}`);
  },

  async trades(ticker: string, limit = 200): Promise<Trades> {
    const qs = new URLSearchParams({ ticker, limit: String(limit) });
    return request<Trades>(`/api/trades?${qs.toString()}`);
  },

  /** Today's broker-side fills for the active account. Source of truth
   *  for Day P/L — includes orders placed in the LongBridge app / web,
   *  not just those submitted by signal-station's trader pipeline. */
  async todayExecutions(): Promise<Executions> {
    return request<Executions>("/api/broker/today_executions");
  },

  /** Replace the streaming quote watch set on the backend. Called by the
   *  dashboard once positions resolve, and again after each account
   *  switch. Backend diffs against the prior set, subscribes new
   *  symbols, and unsubscribes dropped ones. Pass ``symbols: []`` to
   *  clear (e.g. on dashboard close).
   *
   *  Throws ``HttpError(503)`` when the backend hasn't wired its
   *  QuoteHub yet — typically the early-startup window before broker
   *  init finishes. Callers should retry on the next positions tick. */
  async watchQuotes(symbols: string[]): Promise<{ added: number; removed: number; total: number }> {
    return request("/api/quotes/watch", {
      method: "POST",
      body: JSON.stringify({ symbols }),
    });
  },

  /** Historical broker fills, optionally filtered by underlying ticker.
   *  Used by the detail pane's trade list so manual fills surface
   *  alongside signal-station's own submissions.
   *
   *  Paginated newest-first via ``offset`` / ``limit``; the response's
   *  ``total_count`` + ``has_more`` let the caller decide whether to
   *  fetch the next page. Server-side sync runs on every call (idempotent
   *  upsert) so "加载更多" also picks up fresh fills. */
  async executions(
    ticker?: string,
    opts: { days?: number; offset?: number; limit?: number } = {},
  ): Promise<Executions> {
    // ``days`` only governs the first-time-sync horizon on the server —
    // once history is backfilled the response is the full DB slice
    // regardless. Default omitted so the server's 730d (2-year) default
    // applies; callers can still pass an override for custom horizons.
    const { days, offset = 0, limit = 50 } = opts;
    const qs = new URLSearchParams({
      offset: String(offset),
      limit: String(limit),
    });
    if (ticker) qs.set("ticker", ticker);
    if (days != null) qs.set("days", String(days));
    return request<Executions>(`/api/broker/executions?${qs.toString()}`);
  },

  // -------------------------------------------------------------------------
  // 做T pair CRUD — server allocates qty FIFO when creating/extending.
  // -------------------------------------------------------------------------

  async listPairs(
    ticker?: string,
    opts: { offset?: number; limit?: number } = {},
  ): Promise<TPairs> {
    const { offset = 0, limit = 50 } = opts;
    const qs = new URLSearchParams({
      offset: String(offset),
      limit: String(limit),
    });
    if (ticker) qs.set("ticker", ticker);
    return request<TPairs>(`/api/pairs?${qs.toString()}`);
  },

  async createPair(body: TPairCreate): Promise<TPair> {
    return request<TPair>("/api/pairs", {
      method: "POST",
      body: JSON.stringify(body),
    });
  },

  async extendPair(pairId: number, body: TPairExtendIn): Promise<TPair> {
    return request<TPair>(`/api/pairs/${pairId}/extend`, {
      method: "POST",
      body: JSON.stringify(body),
    });
  },

  async deletePair(pairId: number): Promise<void> {
    const { baseUrl, token } = cfg();
    const url = new URL(`/api/pairs/${pairId}`, baseUrl);
    url.searchParams.set("token", token);
    const resp = await fetch(url.toString(), { method: "DELETE" });
    if (!resp.ok) {
      const body = await resp.json().catch(() => null);
      throw new HttpError(resp.status, body, `HTTP ${resp.status}`);
    }
  },

  /** Bulk-delete every做T pair for ``(active account, ticker)``. Each
   *  affected trade's ``t_pair_tags`` is cleared server-side so the做T
   *  chip column flips empty on the next trade fetch / patch. */
  async deletePairsByTicker(ticker: string): Promise<void> {
    const { baseUrl, token } = cfg();
    const url = new URL("/api/pairs", baseUrl);
    url.searchParams.set("token", token);
    url.searchParams.set("ticker", ticker);
    const resp = await fetch(url.toString(), { method: "DELETE" });
    if (!resp.ok) {
      const body = await resp.json().catch(() => null);
      throw new HttpError(resp.status, body, `HTTP ${resp.status}`);
    }
  },

  /** Wipe ``broker_executions`` rows for ``(active account, ticker)``
   *  AND reset ``positions.history_synced`` so the next
   *  ``executionsHistory(ticker)`` call re-triggers the full chunked
   *  2-year backfill. */
  async deleteBrokerExecutions(ticker: string): Promise<void> {
    const { baseUrl, token } = cfg();
    const url = new URL("/api/broker/executions", baseUrl);
    url.searchParams.set("token", token);
    url.searchParams.set("ticker", ticker);
    const resp = await fetch(url.toString(), { method: "DELETE" });
    if (!resp.ok) {
      const body = await resp.json().catch(() => null);
      throw new HttpError(resp.status, body, `HTTP ${resp.status}`);
    }
  },

  /** Account+ticker scoped做T aggregates (SQL SUM/COUNT). Used by
   *  DetailSummary's做T row so the frontend never has to fetch every pair
   *  just to display totals. Omit ``ticker`` for an account-wide aggregate. */
  async pairAggregate(ticker?: string): Promise<PairAggregate> {
    const qs = new URLSearchParams();
    if (ticker) qs.set("ticker", ticker);
    return request<PairAggregate>(
      `/api/pairs/aggregate${qs.toString() ? "?" + qs.toString() : ""}`,
    );
  },

  /** Broker fills with remaining (unallocated) qty + per-side totals.
   *  Drives the "待做T" section in DetailPane. */
  async pendingExecutions(
    ticker?: string,
    opts: { limit?: number } = {},
  ): Promise<PendingExecutions> {
    const { limit = 100 } = opts;
    const qs = new URLSearchParams({ limit: String(limit) });
    if (ticker) qs.set("ticker", ticker);
    return request<PendingExecutions>(
      `/api/broker/executions/pending?${qs.toString()}`,
    );
  },
};

export interface SimScenarioOverview {
  name: string;
  label: string;
  description: string;
  source: string;
  message_text: string;
  push_step_count: number;
}

export interface SimRunResult {
  scenario_name: string;
  message_id: string;
  order_id: string | null;
  started: boolean;
}
