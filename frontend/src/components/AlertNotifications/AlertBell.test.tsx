import { describe, expect, it, beforeEach, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { AlertBell } from "./AlertBell";
import { useAlertNotificationsStore } from "../../stores/alertNotifications";

vi.mock("../../api/alerts", () => ({
  alertsApi: { events: vi.fn().mockResolvedValue({ events: [] }) },
}));

const e = (id: number) => ({
  id, alert_id: 1, triggered_at: "2026-05-25T14:23:00Z",
  ticker: "AAPL", symbol: "AAPL.US",
  snapshot_price: 200.15, snapshot_pct: null, snapshot_volume: null,
  message: `evt-${id}`,
});

const alert = {
  id: 1, ticker: "AAPL", symbol: "AAPL.US",
  condition_type: "price" as const, operator: ">=" as const, threshold: 200,
  pct_change_baseline: null, volume_window: null,
  repeat_mode: "one_shot" as const, cooldown_seconds: 300, enabled: false,
  note: null, created_at: "2026-05-25T10:00:00Z",
  last_triggered_at: null, trigger_count: 1,
};

beforeEach(() => useAlertNotificationsStore.setState({
  unreadCount: 0, history: [], activeToasts: [],
}));

describe("AlertBell", () => {
  it("badge hidden when zero unread", () => {
    render(<AlertBell />);
    expect(screen.queryByTestId("bell-badge")).toBeNull();
  });
  it("badge shows count when >0", () => {
    useAlertNotificationsStore.getState().push(e(1), alert);
    useAlertNotificationsStore.getState().push(e(2), alert);
    render(<AlertBell />);
    expect(screen.getByTestId("bell-badge")).toHaveTextContent("2");
  });
  it("clicking bell opens popover and clears unread", async () => {
    useAlertNotificationsStore.getState().push(e(1), alert);
    render(<AlertBell />);
    await userEvent.click(screen.getByRole("button", { name: /告警/ }));
    expect(useAlertNotificationsStore.getState().unreadCount).toBe(0);
  });
});
