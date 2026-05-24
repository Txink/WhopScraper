import { create } from "zustand";
import type { components } from "../api/types";

export type OrderOut = components["schemas"]["OrderOut"];

interface OrdersState {
  /** Orders indexed by ticker — each ticker holds its own list. */
  byTicker: Record<string, OrderOut[]>;

  /** Replace the full list for a ticker (e.g. on initial load). */
  setOrders(ticker: string, orders: OrderOut[]): void;

  /** Upsert a single order by order_id. Prepends new orders. */
  upsertOrder(ticker: string, order: OrderOut): void;

  /** Remove an order by id. */
  removeOrder(ticker: string, orderId: string): void;
}

export const useOrdersStore = create<OrdersState>((set) => ({
  byTicker: {},

  setOrders: (ticker, orders) =>
    set((state) => ({
      byTicker: { ...state.byTicker, [ticker]: orders },
    })),

  upsertOrder: (ticker, order) =>
    set((state) => {
      const existing = state.byTicker[ticker] ?? [];
      const idx = existing.findIndex((o) => o.order_id === order.order_id);
      let next: OrderOut[];
      if (idx >= 0) {
        // Replace in place
        next = existing.map((o) => (o.order_id === order.order_id ? order : o));
      } else {
        // Prepend new order
        next = [order, ...existing];
      }
      return { byTicker: { ...state.byTicker, [ticker]: next } };
    }),

  removeOrder: (ticker, orderId) =>
    set((state) => {
      const existing = state.byTicker[ticker] ?? [];
      return {
        byTicker: {
          ...state.byTicker,
          [ticker]: existing.filter((o) => o.order_id !== orderId),
        },
      };
    }),
}));
