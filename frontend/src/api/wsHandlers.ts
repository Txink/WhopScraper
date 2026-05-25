/**
 * WS topic handlers for order.changed, alert.changed, alert.triggered.
 *
 * Wire these into App.tsx's onEvent dispatcher:
 *
 *   import { handleOrderChanged, handleAlertChanged, handleAlertTriggered }
 *     from "./api/wsHandlers";
 *
 *   // inside onEvent:
 *   } else if (evt.type === "order.changed") {
 *     handleOrderChanged(evt);
 *   } else if (evt.type === "alert.changed") {
 *     handleAlertChanged(evt);
 *   } else if (evt.type === "alert.triggered") {
 *     handleAlertTriggered(evt);
 *   }
 */

import type { WsEvent } from "./ws";
import { listOrders, type OrderOut } from "./orders";
import type { AlertOut, AlertEventOut } from "./alerts";
import { useOrdersStore } from "../stores/orders";
import { useAlertsStore } from "../stores/alerts";
import { useAlertNotificationsStore } from "../stores/alertNotifications";

/** Handler for `order.changed` — upserts or removes the order in ordersStore. */
export function handleOrderChanged(evt: WsEvent): void {
  const payload = evt.payload as { order?: OrderOut; action?: string };
  if (!payload.order) return;
  const order = payload.order;
  const ticker = order.ticker;

  if (payload.action === "deleted") {
    useOrdersStore.getState().removeOrder(ticker, order.order_id);
  } else {
    useOrdersStore.getState().upsertOrder(ticker, order);
  }
}

/** Handler for `task.push_event` — when a broker push lands for an
 *  order we currently display, refetch that ticker's orders so the
 *  trading panel reflects the new broker status (e.g. NotReported →
 *  Canceled, Filled, etc). We refetch rather than mutate in place
 *  because the broker-side OrderStatus string and Task domain status
 *  use different vocabularies; `OrdersService.list_today` is the
 *  single source of truth that already reconciles them.
 *
 *  LongPort's `replace_order` mints a NEW order_id (old → Replaced,
 *  new → ReplacedNotReported). The new id won't be in the store yet,
 *  so when we can't match by id we refetch every ticker the user is
 *  currently viewing — the next list_today response will carry the
 *  replacement order (source="external" since no manual_task points
 *  at the new id) and the panel resyncs. */
export function handleTaskPushEvent(evt: WsEvent): void {
  const payload = evt.payload as { task?: { order_id?: string | null } };
  const oid = payload.task?.order_id;
  if (!oid) return;
  const byTicker = useOrdersStore.getState().byTicker;
  const refetch = (ticker: string) =>
    listOrders(ticker)
      .then((r) => useOrdersStore.getState().setOrders(ticker, r.orders))
      .catch((e) => console.warn("orders refetch after push failed", e));
  for (const ticker of Object.keys(byTicker)) {
    const list = byTicker[ticker];
    if (list?.some((o) => o.order_id === oid)) {
      void refetch(ticker);
      return;
    }
  }
  // Unknown order_id — likely a replace-spawned new id. Refetch every
  // ticker we currently have orders for so whichever pane is in view
  // picks it up.
  for (const ticker of Object.keys(byTicker)) void refetch(ticker);
}

/** Handler for `alert.changed` — upserts or removes the alert in alertsStore. */
export function handleAlertChanged(evt: WsEvent): void {
  const payload = evt.payload as { alert?: AlertOut; action?: string };
  if (!payload.alert) return;
  const alert = payload.alert;

  if (payload.action === "deleted") {
    useAlertsStore.getState().removeAlert(alert.id);
  } else {
    useAlertsStore.getState().upsertAlert(alert);
  }
}

/** Handler for `alert.triggered` — pushes the event + alert pair into
 *  alertNotificationsStore so the toast carries the alert's repeat_mode
 *  for styling. Backend payload shape is `{event, alert}`. */
export function handleAlertTriggered(evt: WsEvent): void {
  const payload = evt.payload as { event?: AlertEventOut; alert?: AlertOut };
  if (!payload.event || !payload.alert) return;
  useAlertNotificationsStore.getState().push(payload.event, payload.alert);
  // Bump the alert's trigger_count locally so the AlertsPanel row reflects
  // the latest state without a refetch.
  useAlertsStore.getState().upsertAlert(payload.alert);
}
