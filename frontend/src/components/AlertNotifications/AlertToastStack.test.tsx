import { describe, expect, it, beforeEach, vi } from "vitest";
import { render, screen, act } from "@testing-library/react";
import { AlertToastStack } from "./AlertToastStack";
import { useAlertNotificationsStore } from "../../stores/alertNotifications";

const e = (id: number) => ({
  id, alert_id: 1, triggered_at: new Date().toISOString(),
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

describe("AlertToastStack", () => {
  it("renders nothing when no toasts", () => {
    render(<AlertToastStack />);
    expect(screen.queryByText(/触发/)).toBeNull();
  });
  it("renders the toast and auto-dismisses after 5s", () => {
    vi.useFakeTimers();
    render(<AlertToastStack />);
    act(() => { useAlertNotificationsStore.getState().push(e(1), alert); });
    expect(screen.getByText("evt-1")).toBeInTheDocument();
    act(() => { vi.advanceTimersByTime(5500); });
    expect(screen.queryByText("evt-1")).toBeNull();
    vi.useRealTimers();
  });
});
