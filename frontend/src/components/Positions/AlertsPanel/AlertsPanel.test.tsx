import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { AlertsPanel } from "./AlertsPanel";
import { useAlertsStore } from "../../../stores/alerts";
import type { AlertOut } from "../../../api/alerts";

vi.mock("../../../api/alerts", () => ({
  alertsApi: {
    list: vi.fn().mockImplementation(() => new Promise(() => {})),
    create: vi.fn(),
    update: vi.fn(),
    remove: vi.fn(),
  },
}));

const a = (o: Partial<AlertOut> = {}): AlertOut => ({
  id: 1, ticker: "AAPL", symbol: "AAPL.US",
  condition_type: "price", operator: ">=", threshold: 200,
  pct_change_baseline: null, volume_window: null,
  repeat_mode: "one_shot", cooldown_seconds: 300, enabled: true,
  note: null, created_at: "2026-05-25T10:00:00Z",
  last_triggered_at: null, trigger_count: 0, ...o,
});

beforeEach(() => useAlertsStore.setState({ byTicker: { AAPL: [a()] } }));

describe("AlertsPanel", () => {
  it("renders existing alerts", () => {
    render(<AlertsPanel ticker="AAPL" symbol="AAPL.US" />);
    expect(screen.getByText(/价格/)).toBeInTheDocument();
  });
  it("clicking + 添加告警 opens modal", async () => {
    render(<AlertsPanel ticker="AAPL" symbol="AAPL.US" />);
    await userEvent.click(screen.getByRole("button", { name: /添加告警/ }));
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });
  it("clicking × asks for confirmation", async () => {
    render(<AlertsPanel ticker="AAPL" symbol="AAPL.US" />);
    await userEvent.click(screen.getAllByRole("button", { name: "×" })[0]!);
    expect(screen.getByText(/确认删除/)).toBeInTheDocument();
  });
});
