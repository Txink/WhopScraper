/**
 * Shared request helper for API modules that can't directly import the
 * private `request` function from http.ts. This module manages its own
 * singleton config; callers must invoke `configureRequest` before making
 * any calls. In practice, App.tsx calls both `configureHttp` (for legacy
 * api.*) and `configureRequest` (for orders.ts / alerts.ts) with the same
 * values.
 */

interface RequestConfig {
  baseUrl: string;
  token: string;
}

let _cfg: RequestConfig | null = null;

export function configureRequest(config: RequestConfig): void {
  _cfg = config;
}

export class RequestError extends Error {
  constructor(
    public status: number,
    public body: unknown,
    message: string,
  ) {
    super(message);
    this.name = "RequestError";
  }
}

export async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  if (!_cfg) throw new Error("request not configured (call configureRequest first)");
  const { baseUrl, token } = _cfg;
  const url = new URL(path, baseUrl);
  url.searchParams.set("token", token);
  const resp = await fetch(url.toString(), {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init.headers ?? {}),
    },
  });
  if (!resp.ok) {
    let body: unknown = null;
    try { body = await resp.json(); } catch { body = await resp.text().catch(() => null); }
    throw new RequestError(resp.status, body, `HTTP ${resp.status} ${resp.statusText}`);
  }
  return resp.json() as Promise<T>;
}

export async function del(path: string): Promise<void> {
  if (!_cfg) throw new Error("request not configured (call configureRequest first)");
  const { baseUrl, token } = _cfg;
  const url = new URL(path, baseUrl);
  url.searchParams.set("token", token);
  const resp = await fetch(url.toString(), { method: "DELETE" });
  if (!resp.ok) {
    const body = await resp.json().catch(() => null);
    throw new RequestError(resp.status, body, `HTTP ${resp.status}`);
  }
}
