import type { components } from "./types";
import { request, del } from "./_request";

export type AlertOut = components["schemas"]["AlertOut"];
export type AlertListOut = components["schemas"]["AlertListOut"];
export type AlertCreate = components["schemas"]["AlertCreate"];
export type AlertUpdate = components["schemas"]["AlertUpdate"];
export type AlertEventOut = components["schemas"]["AlertEventOut"];
export type AlertEventListOut = components["schemas"]["AlertEventListOut"];

/** List alerts, optionally filtered by ticker. */
export async function listAlerts(ticker?: string): Promise<AlertListOut> {
  const qs = new URLSearchParams();
  if (ticker) qs.set("ticker", ticker);
  const suffix = qs.toString() ? `?${qs.toString()}` : "";
  return request<AlertListOut>(`/api/alerts${suffix}`);
}

/** Create a new alert. */
export async function createAlert(body: AlertCreate): Promise<AlertOut> {
  return request<AlertOut>("/api/alerts", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

/** Update an existing alert. */
export async function updateAlert(
  alertId: number,
  body: AlertUpdate,
): Promise<AlertOut> {
  return request<AlertOut>(`/api/alerts/${alertId}`, {
    method: "PATCH",
    body: JSON.stringify(body),
  });
}

/** Delete an alert. */
export async function deleteAlert(alertId: number): Promise<void> {
  return del(`/api/alerts/${alertId}`);
}

/** List alert trigger events, optionally filtered by ticker. */
export async function listAlertEvents(
  ticker?: string,
  opts: { limit?: number; offset?: number } = {},
): Promise<AlertEventListOut> {
  const { limit = 50, offset = 0 } = opts;
  const qs = new URLSearchParams({ limit: String(limit), offset: String(offset) });
  if (ticker) qs.set("ticker", ticker);
  return request<AlertEventListOut>(`/api/alerts/events?${qs.toString()}`);
}

/** Convenience object for component-level usage. */
export const alertsApi = {
  list: (ticker?: string) => listAlerts(ticker),
  create: (body: AlertCreate) => createAlert(body),
  update: (alertId: number, body: AlertUpdate) => updateAlert(alertId, body),
  remove: (alertId: number) => deleteAlert(alertId),
  events: (opts: { limit?: number; offset?: number } = {}) =>
    listAlertEvents(undefined, opts),
};
