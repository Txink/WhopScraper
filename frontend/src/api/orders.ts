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
