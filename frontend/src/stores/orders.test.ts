import { describe, it, expect, beforeEach } from "vitest";
import { useOrdersStore } from "./orders";
import type { OrderOut } from "./orders";

const sample = (overrides: Partial<OrderOut> = {}): OrderOut => ({
  order_id: "ord-1", task_id: null, ticker: "AAPL", symbol: "AAPL.US",
  side: "BUY", order_type: "LIMIT", price: 199.0, qty: 200, filled_qty: 0,
  status: "SUBMITTING", source: "manual", submitted_at: null,
  last_replaced_at: null, ...overrides,
});

describe("ordersStore", () => {
  beforeEach(() => useOrdersStore.setState({ byTicker: {} }));

  it("setOrders replaces the ticker's list", () => {
    useOrdersStore.getState().setOrders("AAPL", [sample()]);
    expect(useOrdersStore.getState().byTicker["AAPL"]).toHaveLength(1);
  });

  it("upsertOrder by order_id", () => {
    useOrdersStore.getState().setOrders("AAPL", [sample()]);
    useOrdersStore.getState().upsertOrder("AAPL", sample({ filled_qty: 80, status: "Partial" }));
    const list = useOrdersStore.getState().byTicker["AAPL"]!;
    expect(list).toHaveLength(1);
    expect(list[0]!.filled_qty).toBe(80);
  });

  it("removeOrder by id", () => {
    useOrdersStore.getState().setOrders("AAPL", [sample()]);
    useOrdersStore.getState().removeOrder("AAPL", "ord-1");
    expect(useOrdersStore.getState().byTicker["AAPL"]).toHaveLength(0);
  });
});
