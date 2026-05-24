import { describe, it, expect, beforeEach } from "vitest";
import { useAlertsStore } from "./alerts";
import type { AlertOut } from "./alerts";

const sample = (overrides: Partial<AlertOut> = {}): AlertOut => ({
  id: 1, ticker: "AAPL", symbol: "AAPL.US",
  condition_type: "price", operator: ">=", threshold: 200,
  pct_change_baseline: null, volume_window: null,
  repeat_mode: "one_shot", cooldown_seconds: 300,
  enabled: true, note: null,
  created_at: "2026-05-25T00:00:00Z",
  last_triggered_at: null, trigger_count: 0,
  ...overrides,
});

describe("alertsStore", () => {
  beforeEach(() => useAlertsStore.setState({ byTicker: {} }));

  it("setAlerts replaces the ticker's list", () => {
    useAlertsStore.getState().setAlerts("AAPL", [sample()]);
    expect(useAlertsStore.getState().byTicker["AAPL"]).toHaveLength(1);
  });

  it("upsertAlert by id", () => {
    useAlertsStore.getState().setAlerts("AAPL", [sample()]);
    useAlertsStore.getState().upsertAlert(sample({ threshold: 210, enabled: false }));
    const list = useAlertsStore.getState().byTicker["AAPL"]!;
    expect(list).toHaveLength(1);
    expect(list[0]!.threshold).toBe(210);
  });

  it("removeAlert by id across tickers", () => {
    useAlertsStore.getState().setAlerts("AAPL", [sample({ id: 1 }), sample({ id: 2 })]);
    useAlertsStore.getState().removeAlert(1);
    const list = useAlertsStore.getState().byTicker["AAPL"]!;
    expect(list).toHaveLength(1);
    expect(list[0]!.id).toBe(2);
  });
});
