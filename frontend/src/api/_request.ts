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

/** Pull the most user-readable error string out of an HTTP error response.
 *  FastAPI errors live in `body.detail` (string or list of objects); other
 *  shapes fall back to the status line. */
function errorMessage(status: number, statusText: string, body: unknown): string {
  if (body && typeof body === "object" && "detail" in body) {
    const d = (body as { detail: unknown }).detail;
    if (typeof d === "string") return d;
    if (Array.isArray(d) && d.length > 0) {
      try { return JSON.stringify(d); } catch { /* fall through */ }
    }
  }
  if (typeof body === "string" && body) return body;
  return `HTTP ${status} ${statusText}`.trim();
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
    throw new RequestError(resp.status, body, errorMessage(resp.status, resp.statusText, body));
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
    let body: unknown = null;
    try { body = await resp.json(); } catch { body = await resp.text().catch(() => null); }
    throw new RequestError(resp.status, body, errorMessage(resp.status, resp.statusText, body));
  }
}
