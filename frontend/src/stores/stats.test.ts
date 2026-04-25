import { describe, expect, it, beforeEach } from "vitest";
import { useStatsStore } from "./stats";

describe("stats store", () => {
  beforeEach(() => {
    useStatsStore.setState({ stats: null });
  });

  it("setStats stores value", () => {
    useStatsStore.getState().setStats({
      msg_count: 5, parse_ok: 4, parse_rate: 0.8,
      orders: 3, filled: 2, rejected: 1,
    });
    expect(useStatsStore.getState().stats?.msg_count).toBe(5);
  });

  it("reset clears", () => {
    useStatsStore.getState().setStats({
      msg_count: 5, parse_ok: 4, parse_rate: 0.8,
      orders: 3, filled: 2, rejected: 1,
    });
    useStatsStore.getState().reset();
    expect(useStatsStore.getState().stats).toBeNull();
  });
});
