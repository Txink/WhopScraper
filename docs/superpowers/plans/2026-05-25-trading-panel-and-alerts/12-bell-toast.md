# Task 12: AlertBell + AlertToastStack

**Files:**
- Create:
  - `frontend/src/components/AlertNotifications/AlertBell.tsx`
  - `frontend/src/components/AlertNotifications/AlertToastStack.tsx`
  - `.../AlertNotifications.css`
- Modify: `frontend/src/components/TopBar.tsx` — mount `<AlertBell />`
- Modify: `frontend/src/App.tsx` — mount `<AlertToastStack />`
- Tests: sibling `.test.tsx`

## Steps

- [ ] **Step 1: Test AlertBell**

`AlertBell.test.tsx`:

```typescript
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
```

- [ ] **Step 2: Test AlertToastStack**

`AlertToastStack.test.tsx`:

```typescript
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
```

- [ ] **Step 3: Implement AlertBell**

```typescript
import { useEffect, useRef, useState } from "react";
import { useAlertNotificationsStore } from "../../stores/alertNotifications";
import { alertsApi } from "../../api/alerts";
import "./AlertNotifications.css";

export function AlertBell() {
  const unread = useAlertNotificationsStore((s) => s.unreadCount);
  const history = useAlertNotificationsStore((s) => s.history);
  const clearUnread = useAlertNotificationsStore((s) => s.clearUnread);
  const setHistory = (events: typeof history) =>
    useAlertNotificationsStore.setState({ history: events });
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    alertsApi.events({ limit: 50 }).then((r) => setHistory(r.events))
      .catch(() => {});
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [open]);

  const onOpen = () => {
    setOpen((v) => !v);
    if (!open) clearUnread();
  };

  return (
    <div ref={containerRef} style={{ position: "relative" }}>
      <button
        type="button"
        aria-label="告警"
        className={`bell ${unread > 0 ? "has-unread" : ""}`}
        onClick={onOpen}
      >
        <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9" />
          <path d="M10.3 21a1.94 1.94 0 0 0 3.4 0" />
        </svg>
        {unread > 0 && (
          <span data-testid="bell-badge" className="bell-badge">
            {unread > 99 ? "99+" : unread}
          </span>
        )}
      </button>
      {open && (
        <div className="bell-popover">
          <div className="bell-popover-head">
            <span>告警历史</span>
          </div>
          <div className="bell-popover-body">
            {history.length === 0 && <div style={{ padding: 12, color: "var(--fg-3)" }}>无触发记录</div>}
            {history.map((e) => (
              <div key={e.id} className="bell-event">
                <span className="bell-event-icon" />
                <div className="bell-event-main">
                  <span className="bell-event-cond">{e.message}</span>
                </div>
                <span className="bell-event-time">
                  {new Date(e.triggered_at).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit", second: "2-digit" })}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 4: Implement AlertToastStack**

```typescript
import { useEffect } from "react";
import { useAlertNotificationsStore } from "../../stores/alertNotifications";
import "./AlertNotifications.css";

const TOAST_TTL_MS = 5000;

export function AlertToastStack() {
  const toasts = useAlertNotificationsStore((s) => s.activeToasts);
  const dismiss = useAlertNotificationsStore((s) => s.dismissToast);

  useEffect(() => {
    const timers = toasts.map((t) =>
      setTimeout(() => dismiss(t.event.id), Math.max(0, TOAST_TTL_MS - (Date.now() - t.bornAt)))
    );
    return () => timers.forEach((id) => clearTimeout(id));
  }, [toasts, dismiss]);

  if (toasts.length === 0) return null;
  return (
    <div className="toast-stack">
      {toasts.map((t) => (
        <div
          key={t.event.id}
          className={`toast ${t.alert.repeat_mode === "recurring" ? "recurring" : ""}`}
        >
          <div className="toast-head">
            <span><span className="toast-ticker">{t.event.ticker}</span></span>
            <button className="toast-close" aria-label="关闭" onClick={() => dismiss(t.event.id)}>×</button>
          </div>
          <div className="toast-snap">
            <span>{t.event.message}</span>
          </div>
        </div>
      ))}
    </div>
  );
}
```

`AlertNotifications.css`: copy `.bell*`, `.toast*` styles from `.design/trading-panel-and-alerts.html`.

- [ ] **Step 5: Mount in TopBar + App**

`frontend/src/components/TopBar.tsx` — add inside the right cluster (before the `conn` group):

```tsx
import { AlertBell } from "./AlertNotifications/AlertBell";
// ...
<AlertBell />
```

`frontend/src/App.tsx` — mount at top level:

```tsx
import { AlertToastStack } from "./components/AlertNotifications/AlertToastStack";
// ...
<>
  {/* existing app tree */}
  <AlertToastStack />
</>
```

- [ ] **Step 6: Run + typecheck**

```bash
cd frontend
npm test -- --run src/components/AlertNotifications
npm run typecheck
```

Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/AlertNotifications/ frontend/src/components/TopBar.tsx \
        frontend/src/App.tsx
git commit -m "$(cat <<'EOF'
feat(alerts): AlertBell + AlertToastStack notification surface

Top-bar bell shows unread badge + history popover; click clears
unread. Toast stack renders WS-pushed alert.triggered events with a
5s auto-dismiss timer.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```
