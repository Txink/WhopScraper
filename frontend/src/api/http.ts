import type {
  Task, TaskList, Positions, StatsToday, Health,
  WhopPage, WhopPages, WhopPageCreate, WhopCookieStatus,
  WhopPageSettings, WhopPageSettingsPatch, LongportSettings, LongportSettingsPatch,
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

  async getTask(id: string): Promise<Task> {
    return request<Task>(`/api/tasks/${encodeURIComponent(id)}`);
  },

  async cancelTask(id: string): Promise<{ ok: boolean }> {
    return request(`/api/tasks/${encodeURIComponent(id)}/cancel`, { method: "POST" });
  },

  async confirmTask(id: string): Promise<Task> {
    return request<Task>(`/api/tasks/${encodeURIComponent(id)}/confirm`, { method: "POST" });
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
};
