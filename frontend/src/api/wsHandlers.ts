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
import type { OrderOut } from "./orders";
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
