import { describe, it, expect, beforeEach } from "vitest";
import { useAlertNotificationsStore } from "./alertNotifications";
import type { AlertEventOut, AlertOut } from "./alertNotifications";

const sampleEvent = (overrides: Partial<AlertEventOut> = {}): AlertEventOut => ({
  id: 1, alert_id: 10, ticker: "AAPL", symbol: "AAPL.US",
  triggered_at: "2026-05-25T00:00:00Z",
  snapshot_price: 200, snapshot_pct: null, snapshot_volume: null,
  message: "AAPL >= 200",
  ...overrides,
});

const sampleAlert = (overrides: Partial<AlertOut> = {}): AlertOut => ({
  id: 10, ticker: "AAPL", symbol: "AAPL.US",
  condition_type: "price", operator: ">=", threshold: 200,
  pct_change_baseline: null, volume_window: null,
  repeat_mode: "one_shot", cooldown_seconds: 300, enabled: false,
  note: null, created_at: "2026-05-25T00:00:00Z",
  last_triggered_at: "2026-05-25T00:00:00Z", trigger_count: 1,
  ...overrides,
});

describe("alertNotificationsStore", () => {
  beforeEach(() =>
    useAlertNotificationsStore.setState({
      unreadCount: 0,
      history: [],
      activeToasts: [],
    }),
  );

  it("push increments unreadCount and prepends to history", () => {
    useAlertNotificationsStore.getState().push(sampleEvent({ id: 1 }), sampleAlert());
    useAlertNotificationsStore.getState().push(sampleEvent({ id: 2 }), sampleAlert());
    const s = useAlertNotificationsStore.getState();
    expect(s.unreadCount).toBe(2);
    expect(s.history).toHaveLength(2);
    expect(s.history[0]!.id).toBe(2);
    expect(s.activeToasts).toHaveLength(2);
    expect(s.activeToasts[0]!.event.id).toBe(2);
    expect(s.activeToasts[0]!.alert.repeat_mode).toBe("one_shot");
  });

  it("clearUnread resets counter without touching history", () => {
    useAlertNotificationsStore.getState().push(sampleEvent(), sampleAlert());
    useAlertNotificationsStore.getState().clearUnread();
    const s = useAlertNotificationsStore.getState();
    expect(s.unreadCount).toBe(0);
    expect(s.history).toHaveLength(1);
  });

  it("activeToasts capped at 3", () => {
    for (let i = 1; i <= 4; i++) {
      useAlertNotificationsStore.getState().push(sampleEvent({ id: i }), sampleAlert());
    }
    expect(useAlertNotificationsStore.getState().activeToasts).toHaveLength(3);
  });

  it("dismissToast removes by event id", () => {
    useAlertNotificationsStore.getState().push(sampleEvent({ id: 1 }), sampleAlert());
    useAlertNotificationsStore.getState().push(sampleEvent({ id: 2 }), sampleAlert());
    useAlertNotificationsStore.getState().dismissToast(1);
    const toasts = useAlertNotificationsStore.getState().activeToasts;
    expect(toasts.every((t) => t.event.id !== 1)).toBe(true);
  });
});
