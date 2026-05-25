import type { components } from "./types";
import { request, del } from "./_request";

export type OrderOut = components["schemas"]["OrderOut"];
export type OrderListOut = components["schemas"]["OrderListOut"];
export type SubmitOrderRequest = components["schemas"]["SubmitOrderRequest"];
export type ReplaceOrderRequest = components["schemas"]["ReplaceOrderRequest"];

/** List open/recent orders for a ticker. */
export async function listOrders(ticker: string): Promise<OrderListOut> {
  const qs = new URLSearchParams({ ticker });
  return request<OrderListOut>(`/api/orders?${qs.toString()}`);
}

/** Submit a new order. */
export async function submitOrder(body: SubmitOrderRequest): Promise<OrderOut> {
  return request<OrderOut>("/api/orders", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

/** Replace (amend) an existing order's price/qty. */
export async function replaceOrder(
  orderId: string,
  body: ReplaceOrderRequest,
): Promise<OrderOut> {
  return request<OrderOut>(`/api/orders/${encodeURIComponent(orderId)}`, {
    method: "PATCH",
    body: JSON.stringify(body),
  });
}

/** Cancel an order. Backend uses DELETE /api/orders/{id}. */
export async function cancelOrder(orderId: string): Promise<void> {
  return del(`/api/orders/${encodeURIComponent(orderId)}`);
}

// Order.status reaches the frontend in three shapes depending on the
// path that produced it:
//   1. "OrderStatus.Canceled" — LongPort SDK enum, str(enum) form.
//   2. "Canceled"             — same, post-prefix-strip.
//   3. "CANCELLED"            — our Python Status StrEnum (note: UK
//                               double-L, vs the SDK's US single-L).
// normStatus folds all three into a single upper-case label so callers
// can match on a clean set.
function normStatus(s: string): string {
  const stripped = s.startsWith("OrderStatus.") ? s.slice("OrderStatus.".length) : s;
  return stripped.toUpperCase();
}

const TERMINAL_STATUSES = new Set([
  "FILLED",
  "CANCELED", "CANCELLED",       // LongPort vs our enum
  "REJECTED",
  "EXPIRED",
  "PARTIALWITHDRAWAL",
]);

// In-flight cancel states — the order isn't terminal yet (the cancel
// could still fail and the order return to NEW) but the user shouldn't
// be allowed to fire modify/cancel while the previous cancel is racing
// through the broker.
const CANCELLING_STATUSES = new Set([
  "WAITTOCANCEL",
  "PENDINGCANCEL",
]);

/** True if the order has reached a terminal state (filled / cancelled /
 *  rejected / expired). Use this when the question is specifically
 *  "is this order done forever"; for "can the user act on it", prefer
 *  isOrderActionable. */
export function isOrderTerminal(o: OrderOut): boolean {
  return TERMINAL_STATUSES.has(normStatus(o.status))
    || (o.filled_qty >= o.qty && o.qty > 0);
}

/** True if the user should be allowed to modify or cancel this order.
 *  False for terminal orders AND for orders with a cancel already
 *  in flight (avoids racing the broker on duplicate cancels). */
export function isOrderActionable(o: OrderOut): boolean {
  if (isOrderTerminal(o)) return false;
  if (CANCELLING_STATUSES.has(normStatus(o.status))) return false;
  return true;
}
