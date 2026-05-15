import { describe, it, expect, beforeEach } from "vitest";
import { useExecutionsStore } from "./executions";
import type { Execution } from "../api/domain-types";

const _exec = (order_id: string, overrides: Partial<Execution> = {}): Execution => ({
  order_id,
  symbol: "TSLA.US",
  ticker: "TSLA",
  side: "BUY",
  qty: 10,
  price: 245.5,
  ts: "2026-05-15T12:00:00+00:00",
  ...overrides,
});

describe("executions store", () => {
  beforeEach(() => {
    useExecutionsStore.getState().reset();
  });

  it("setExecutions replaces the full list", () => {
    useExecutionsStore.getState().setExecutions([_exec("o-1"), _exec("o-2")]);
    expect(useExecutionsStore.getState().executions).toHaveLength(2);
    useExecutionsStore.getState().setExecutions([_exec("o-3")]);
    expect(useExecutionsStore.getState().executions.map((e) => e.order_id)).toEqual(["o-3"]);
  });

  it("upsertExecution appends when order_id is new", () => {
    useExecutionsStore.getState().setExecutions([_exec("o-1")]);
    useExecutionsStore.getState().upsertExecution(_exec("o-2", { qty: 20 }));
    const list = useExecutionsStore.getState().executions;
    expect(list.map((e) => e.order_id)).toEqual(["o-1", "o-2"]);
  });

  it("upsertExecution replaces in place when order_id already exists (partial-fill update)", () => {
    // Initial fill: 5 shares.
    useExecutionsStore.getState().setExecutions([_exec("o-1", { qty: 5, price: 245 })]);
    // Subsequent push: cumulative 12 shares at weighted-avg 245.3.
    useExecutionsStore.getState().upsertExecution(
      _exec("o-1", { qty: 12, price: 245.3 }),
    );
    const list = useExecutionsStore.getState().executions;
    expect(list).toHaveLength(1);
    expect(list[0]?.qty).toBe(12);
    expect(list[0]?.price).toBe(245.3);
  });
});
