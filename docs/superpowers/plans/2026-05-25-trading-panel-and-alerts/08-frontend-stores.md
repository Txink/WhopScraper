# Task 8: Frontend Stores + WS Dispatch

**Files:**
- Create: `frontend/src/api/orders.ts`, `frontend/src/api/alerts.ts`
- Create: `frontend/src/stores/orders.ts`, `frontend/src/stores/alerts.ts`, `frontend/src/stores/alertNotifications.ts`
- Modify: `frontend/src/api/ws.ts` — dispatch `order.changed`, `alert.triggered`, `alert.changed`
- Modify: `frontend/src/stores/detailView.ts` — add `tabIndex` field
- Tests: `frontend/src/stores/orders.test.ts`, `alerts.test.ts`, `alertNotifications.test.ts`

## Steps

- [ ] **Step 1: Write failing store tests**

`frontend/src/stores/orders.test.ts`:

```typescript
import { describe, it, expect, beforeEach } from "vitest";
import { useOrdersStore } from "./orders";
import type { OrderOut } from "../api/types";

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
```

`frontend/src/stores/alerts.test.ts`:

```typescript
import { describe, it, expect, beforeEach } from "vitest";
import { useAlertsStore } from "./alerts";
import type { AlertOut } from "../api/types";

const a = (overrides: Partial<AlertOut> = {}): AlertOut => ({
  id: 1, ticker: "AAPL", symbol: "AAPL.US",
  condition_type: "price", operator: ">=", threshold: 200,
  pct_change_baseline: null, volume_window: null,
  repeat_mode: "one_shot", cooldown_seconds: 300, enabled: true,
  note: null, created_at: "2026-05-25T10:00:00Z",
  last_triggered_at: null, trigger_count: 0,
  ...overrides,
});

describe("alertsStore", () => {
  beforeEach(() => useAlertsStore.setState({ byTicker: {} }));

  it("setAlerts populates ticker bucket", () => {
    useAlertsStore.getState().setAlerts("AAPL", [a()]);
    expect(useAlertsStore.getState().byTicker["AAPL"]).toHaveLength(1);
  });

  it("upsertAlert by id replaces matching row", () => {
    useAlertsStore.getState().setAlerts("AAPL", [a()]);
    useAlertsStore.getState().upsertAlert(a({ threshold: 205 }));
    expect(useAlertsStore.getState().byTicker["AAPL"]![0]!.threshold).toBe(205);
  });

  it("removeAlert drops the row", () => {
    useAlertsStore.getState().setAlerts("AAPL", [a()]);
    useAlertsStore.getState().removeAlert(1);
    expect(useAlertsStore.getState().byTicker["AAPL"]).toEqual([]);
  });
});
```

`frontend/src/stores/alertNotifications.test.ts`:

```typescript
import { describe, it, expect, beforeEach } from "vitest";
import { useAlertNotificationsStore } from "./alertNotifications";
import type { AlertEventOut, AlertOut } from "../api/types";

const e = (id: number): AlertEventOut => ({
  id, alert_id: 1, triggered_at: new Date().toISOString(),
  ticker: "AAPL", symbol: "AAPL.US",
  snapshot_price: 200.15, snapshot_pct: null, snapshot_volume: null,
  message: `evt-${id}`,
});

const baseAlert: AlertOut = {
  id: 1, ticker: "AAPL", symbol: "AAPL.US",
  condition_type: "price", operator: ">=", threshold: 200,
  pct_change_baseline: null, volume_window: null,
  repeat_mode: "one_shot", cooldown_seconds: 300, enabled: false,
  note: null, created_at: new Date().toISOString(),
  last_triggered_at: null, trigger_count: 1,
};

describe("alertNotificationsStore", () => {
  beforeEach(() => useAlertNotificationsStore.setState({
    unreadCount: 0, history: [], activeToasts: [],
  }));

  it("push increments unread + adds toast + history", () => {
    useAlertNotificationsStore.getState().push(e(1), baseAlert);
    const s = useAlertNotificationsStore.getState();
    expect(s.unreadCount).toBe(1);
    expect(s.history).toHaveLength(1);
    expect(s.activeToasts).toHaveLength(1);
  });

  it("clearUnread zeros the counter without touching history", () => {
    useAlertNotificationsStore.getState().push(e(1), baseAlert);
    useAlertNotificationsStore.getState().clearUnread();
    expect(useAlertNotificationsStore.getState().unreadCount).toBe(0);
    expect(useAlertNotificationsStore.getState().history).toHaveLength(1);
  });

  it("activeToasts is capped at 3; older toasts drop off", () => {
    const store = useAlertNotificationsStore.getState();
    store.push(e(1), baseAlert);
    store.push(e(2), baseAlert);
    store.push(e(3), baseAlert);
    store.push(e(4), baseAlert);
    expect(useAlertNotificationsStore.getState().activeToasts).toHaveLength(3);
  });

  it("dismissToast removes a specific toast", () => {
    useAlertNotificationsStore.getState().push(e(1), baseAlert);
    useAlertNotificationsStore.getState().push(e(2), baseAlert);
    useAlertNotificationsStore.getState().dismissToast(1);
    const ids = useAlertNotificationsStore.getState().activeToasts.map((t) => t.event.id);
    expect(ids).toEqual([2]);
  });
});
```

- [ ] **Step 2: Run — verify failures**

```bash
cd frontend && npm test -- --run src/stores
```

Expected: Module-not-found errors.

- [ ] **Step 3: Implement API helpers**

`frontend/src/api/orders.ts`:

```typescript
import { api as http } from "./http";
import type {
  OrderListOut, OrderOut, SubmitOrderRequest, ReplaceOrderRequest,
} from "./types";

export const ordersApi = {
  submit: (req: SubmitOrderRequest): Promise<OrderOut> =>
    http.post("/api/orders", req),
  replace: (orderId: string, req: ReplaceOrderRequest): Promise<void> =>
    http.patch(`/api/orders/${encodeURIComponent(orderId)}`, req),
  cancel: (orderId: string): Promise<void> =>
    http.del(`/api/orders/${encodeURIComponent(orderId)}`),
  listToday: (ticker: string): Promise<OrderListOut> =>
    http.get(`/api/orders?ticker=${encodeURIComponent(ticker)}`),
};
```

(Add generic `post`/`patch`/`del`/`get` helpers to `frontend/src/api/http.ts` if not yet present; they should already exist — verify.)

`frontend/src/api/alerts.ts`:

```typescript
import { api as http } from "./http";
import type {
  AlertCreate, AlertUpdate, AlertOut, AlertListOut, AlertEventListOut,
} from "./types";

export const alertsApi = {
  list: (ticker: string): Promise<AlertListOut> =>
    http.get(`/api/alerts?ticker=${encodeURIComponent(ticker)}`),
  create: (req: AlertCreate): Promise<AlertOut> =>
    http.post("/api/alerts", req),
  update: (id: number, req: AlertUpdate): Promise<AlertOut> =>
    http.patch(`/api/alerts/${id}`, req),
  remove: (id: number): Promise<void> =>
    http.del(`/api/alerts/${id}`),
  events: (params: { ticker?: string; limit?: number } = {}): Promise<AlertEventListOut> => {
    const q = new URLSearchParams();
    if (params.ticker) q.set("ticker", params.ticker);
    if (params.limit) q.set("limit", String(params.limit));
    return http.get(`/api/alerts/events?${q.toString()}`);
  },
};
```

- [ ] **Step 4: Implement stores**

`frontend/src/stores/orders.ts`:

```typescript
import { create } from "zustand";
import type { OrderOut } from "../api/types";

interface OrdersState {
  byTicker: Record<string, OrderOut[]>;
  setOrders: (ticker: string, orders: OrderOut[]) => void;
  upsertOrder: (ticker: string, order: OrderOut) => void;
  removeOrder: (ticker: string, orderId: string) => void;
}

export const useOrdersStore = create<OrdersState>((set) => ({
  byTicker: {},
  setOrders: (ticker, orders) =>
    set((s) => ({ byTicker: { ...s.byTicker, [ticker]: orders } })),
  upsertOrder: (ticker, order) =>
    set((s) => {
      const list = s.byTicker[ticker] ?? [];
      const idx = list.findIndex((o) => o.order_id === order.order_id);
      const next = idx >= 0 ? list.map((o, i) => (i === idx ? { ...o, ...order } : o)) : [order, ...list];
      return { byTicker: { ...s.byTicker, [ticker]: next } };
    }),
  removeOrder: (ticker, orderId) =>
    set((s) => ({
      byTicker: {
        ...s.byTicker,
        [ticker]: (s.byTicker[ticker] ?? []).filter((o) => o.order_id !== orderId),
      },
    })),
}));
```

`frontend/src/stores/alerts.ts`:

```typescript
import { create } from "zustand";
import type { AlertOut } from "../api/types";

interface AlertsState {
  byTicker: Record<string, AlertOut[]>;
  setAlerts: (ticker: string, alerts: AlertOut[]) => void;
  upsertAlert: (alert: AlertOut) => void;
  removeAlert: (alertId: number) => void;
}

export const useAlertsStore = create<AlertsState>((set) => ({
  byTicker: {},
  setAlerts: (ticker, alerts) =>
    set((s) => ({ byTicker: { ...s.byTicker, [ticker]: alerts } })),
  upsertAlert: (alert) =>
    set((s) => {
      const list = s.byTicker[alert.ticker] ?? [];
      const idx = list.findIndex((a) => a.id === alert.id);
      const next = idx >= 0 ? list.map((a, i) => (i === idx ? alert : a)) : [...list, alert];
      return { byTicker: { ...s.byTicker, [alert.ticker]: next } };
    }),
  removeAlert: (alertId) =>
    set((s) => {
      const next: Record<string, AlertOut[]> = {};
      for (const [t, list] of Object.entries(s.byTicker)) {
        next[t] = list.filter((a) => a.id !== alertId);
      }
      return { byTicker: next };
    }),
}));
```

`frontend/src/stores/alertNotifications.ts`:

```typescript
import { create } from "zustand";
import type { AlertEventOut, AlertOut } from "../api/types";

export interface AlertToast {
  event: AlertEventOut;
  alert: AlertOut;
  bornAt: number;  // Date.now()
}

interface State {
  unreadCount: number;
  history: AlertEventOut[];  // newest first; capped at 100
  activeToasts: AlertToast[];  // newest last; capped at 3
  push: (event: AlertEventOut, alert: AlertOut) => void;
  clearUnread: () => void;
  dismissToast: (eventId: number) => void;
  clearHistory: () => void;
}

const MAX_HISTORY = 100;
const MAX_TOASTS = 3;

export const useAlertNotificationsStore = create<State>((set) => ({
  unreadCount: 0,
  history: [],
  activeToasts: [],
  push: (event, alert) =>
    set((s) => ({
      unreadCount: s.unreadCount + 1,
      history: [event, ...s.history].slice(0, MAX_HISTORY),
      activeToasts: [...s.activeToasts, { event, alert, bornAt: Date.now() }].slice(-MAX_TOASTS),
    })),
  clearUnread: () => set({ unreadCount: 0 }),
  dismissToast: (eventId) =>
    set((s) => ({ activeToasts: s.activeToasts.filter((t) => t.event.id !== eventId) })),
  clearHistory: () => set({ history: [], unreadCount: 0 }),
}));
```

- [ ] **Step 5: Extend detailView store**

In `frontend/src/stores/detailView.ts` add a `tabIndex` field (0=records, 1=trading, 2=alerts):

```typescript
// inside existing interface:
  tabIndex: 0 | 1 | 2;
  setTabIndex: (i: 0 | 1 | 2) => void;
// inside the create() factory state object:
  tabIndex: 0,
  setTabIndex: (i) => set({ tabIndex: i }),
```

Reset `tabIndex: 0` in the existing `resetDetail()` method or wherever the store clears when the user navigates back to the positions list.

- [ ] **Step 6: Wire WS dispatch**

In `frontend/src/api/ws.ts`, add handlers in the existing topic-switch (around the existing `task.*` handlers):

```typescript
import { useOrdersStore } from "../stores/orders";
import { useAlertsStore } from "../stores/alerts";
import { useAlertNotificationsStore } from "../stores/alertNotifications";

// inside dispatch
case "order.changed": {
  const action = payload.action as string;
  if (action === "created" || action === "updated" || action === "filled") {
    const order = payload.order;
    if (order?.ticker && order?.order_id) {
      useOrdersStore.getState().upsertOrder(order.ticker, order);
    }
  } else if (action === "cancelled" && payload.order_id) {
    // We don't always know the ticker — fall back to "any list contains this id".
    const byTicker = useOrdersStore.getState().byTicker;
    for (const t of Object.keys(byTicker)) {
      if (byTicker[t]!.some((o) => o.order_id === payload.order_id)) {
        useOrdersStore.getState().removeOrder(t, payload.order_id);
        break;
      }
    }
  }
  break;
}
case "alert.changed": {
  const a = payload.alert;
  const action = payload.action;
  if (action === "deleted") useAlertsStore.getState().removeAlert(a.id);
  else useAlertsStore.getState().upsertAlert(a);
  break;
}
case "alert.triggered": {
  useAlertNotificationsStore.getState().push(payload.event, payload.alert);
  // Also bump alert row's trigger_count locally via upsert.
  useAlertsStore.getState().upsertAlert(payload.alert);
  break;
}
```

- [ ] **Step 7: Run + verify**

```bash
cd frontend
npm test -- --run src/stores
npm run typecheck
```

Expected: all green.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/api/orders.ts frontend/src/api/alerts.ts \
        frontend/src/stores/orders.ts frontend/src/stores/alerts.ts \
        frontend/src/stores/alertNotifications.ts frontend/src/stores/detailView.ts \
        frontend/src/api/ws.ts frontend/src/stores/orders.test.ts \
        frontend/src/stores/alerts.test.ts frontend/src/stores/alertNotifications.test.ts
git commit -m "$(cat <<'EOF'
feat(stores): orders + alerts + alertNotifications stores

Zustand stores indexed by ticker; alertNotifications maintains
unread count, history, and a 3-toast active queue. WS dispatch wires
order.changed / alert.changed / alert.triggered into the stores.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```
