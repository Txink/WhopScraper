# Task 10: TradingPanel (active orders + quick order + replace + full modal)

**Files:**
- Create:
  - `frontend/src/components/Positions/TradingPanel/TradingPanel.tsx` + `.css`
  - `.../ActiveOrdersTable.tsx`
  - `.../QuickOrderRow.tsx`
  - `.../ReplaceOrderPopover.tsx`
  - `.../FullOrderModal.tsx`
- Tests: sibling `.test.tsx` for each

Total work: ~6 sub-steps below, each its own commit.

---

## 10A. ActiveOrdersTable

- [ ] **A.1 Test**

`ActiveOrdersTable.test.tsx`:

```typescript
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ActiveOrdersTable } from "./ActiveOrdersTable";
import type { OrderOut } from "../../../api/types";

const row = (overrides: Partial<OrderOut> = {}): OrderOut => ({
  order_id: "ord-1", task_id: null, ticker: "AAPL", symbol: "AAPL.US",
  side: "BUY", order_type: "LIMIT", price: 199, qty: 200, filled_qty: 0,
  status: "NewStatus", source: "manual",
  submitted_at: "2026-05-25T10:00:00Z", last_replaced_at: null,
  ...overrides,
});

describe("ActiveOrdersTable", () => {
  it("renders rows", () => {
    render(<ActiveOrdersTable orders={[row()]} onReplace={() => {}} onCancel={() => {}} />);
    expect(screen.getByText("AAPL")).toBeInTheDocument();
  });
  it("calls onReplace with order when 改 clicked", async () => {
    const onReplace = vi.fn();
    render(<ActiveOrdersTable orders={[row()]} onReplace={onReplace} onCancel={() => {}} />);
    await userEvent.click(screen.getByRole("button", { name: "改" }));
    expect(onReplace).toHaveBeenCalledWith(expect.objectContaining({ order_id: "ord-1" }));
  });
  it("disables 改/撤 for filled orders", () => {
    render(<ActiveOrdersTable orders={[row({ status: "FilledStatus", filled_qty: 200 })]} onReplace={() => {}} onCancel={() => {}} />);
    expect(screen.getByRole("button", { name: "改" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "撤" })).toBeDisabled();
  });
  it("activeOnly filter hides terminal-status rows", () => {
    render(<ActiveOrdersTable orders={[
      row({ order_id: "a", status: "NewStatus" }),
      row({ order_id: "b", status: "FilledStatus", filled_qty: 200 }),
    ]} activeOnly onReplace={() => {}} onCancel={() => {}} />);
    expect(screen.queryByText(/ord-b/)).not.toBeInTheDocument();
  });
});
```

- [ ] **A.2 Implement**

```typescript
import type { OrderOut } from "../../../api/types";

interface Props {
  orders: OrderOut[];
  activeOnly?: boolean;
  onReplace: (order: OrderOut) => void;
  onCancel: (order: OrderOut) => void;
}

const TERMINAL = new Set(["FilledStatus", "CancelledStatus", "RejectedStatus", "Filled", "Cancelled", "Rejected"]);

function isTerminal(o: OrderOut): boolean {
  return TERMINAL.has(o.status) || (o.filled_qty >= o.qty && o.qty > 0);
}

function fmtTime(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false });
}

export function ActiveOrdersTable({ orders, activeOnly, onReplace, onCancel }: Props) {
  const visible = activeOnly ? orders.filter((o) => !isTerminal(o)) : orders;
  return (
    <table className="tbl">
      <thead>
        <tr>
          <th>时间</th><th>方向</th><th>类型</th>
          <th className="num">价格</th><th className="num">数量</th>
          <th className="num">已成</th><th>状态</th><th>来源</th><th>操作</th>
        </tr>
      </thead>
      <tbody>
        {visible.map((o) => {
          const done = isTerminal(o);
          const sideClass = o.side === "BUY" ? "buy" : "sell";
          return (
            <tr key={o.order_id}>
              <td>{fmtTime(o.submitted_at)}</td>
              <td><span className={`side-pill ${sideClass}`}>{o.side}</span></td>
              <td>{o.order_type === "LIMIT" ? "LIMIT" : "MKT"}</td>
              <td className="num">{o.price != null ? `$${o.price.toFixed(3)}` : "—"}</td>
              <td className="num">{o.qty}</td>
              <td className="num">{o.filled_qty}</td>
              <td>{o.status}</td>
              <td><span style={{ fontSize: 10, color: "var(--fg-3)" }}>
                {o.source === "manual" ? "手动" : o.source === "signal" ? "信号" : "长桥app"}
              </span></td>
              <td>
                <div className="row-actions">
                  <button className="row-btn" disabled={done} onClick={() => onReplace(o)}>改</button>
                  <button className="row-btn danger" disabled={done} onClick={() => onCancel(o)}>撤</button>
                </div>
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}
```

- [ ] **A.3 Run + commit**

```bash
cd frontend && npm test -- --run src/components/Positions/TradingPanel/ActiveOrdersTable.test.tsx
git add frontend/src/components/Positions/TradingPanel/ActiveOrdersTable.tsx \
        frontend/src/components/Positions/TradingPanel/ActiveOrdersTable.test.tsx
git commit -m "feat(trading): ActiveOrdersTable component"
```

---

## 10B. QuickOrderRow

- [ ] **B.1 Test**

```typescript
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QuickOrderRow } from "./QuickOrderRow";

describe("QuickOrderRow", () => {
  it("toggling MKT disables price input", async () => {
    render(<QuickOrderRow symbol="AAPL.US" ticker="AAPL" presets={{ regular: 200, half: 100, third: 67 }} lastDone={199.0} onSubmit={() => {}} onMore={() => {}} />);
    await userEvent.click(screen.getByRole("button", { name: "MKT" }));
    expect(screen.getByLabelText("价")).toBeDisabled();
  });
  it("submit calls onSubmit with form state", async () => {
    const onSubmit = vi.fn();
    render(<QuickOrderRow symbol="AAPL.US" ticker="AAPL" presets={{ regular: 200, half: 100, third: 67 }} lastDone={199.0} onSubmit={onSubmit} onMore={() => {}} />);
    await userEvent.click(screen.getByRole("button", { name: "提交" }));
    expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({
      symbol: "AAPL.US", side: "BUY", order_type: "LIMIT", qty: 200, price: 199.0,
    }));
  });
  it("preset chip fills quantity", async () => {
    render(<QuickOrderRow symbol="AAPL.US" ticker="AAPL" presets={{ regular: 200, half: 100, third: 67 }} lastDone={199.0} onSubmit={() => {}} onMore={() => {}} />);
    await userEvent.click(screen.getByRole("button", { name: /数/ }));  // open dropdown
    await userEvent.click(screen.getByRole("button", { name: /半仓/ }));
    expect((screen.getByLabelText("数") as HTMLInputElement).value).toBe("100");
  });
});
```

- [ ] **B.2 Implement**

```typescript
import { useEffect, useState } from "react";
import type { SubmitOrderRequest } from "../../../api/types";

interface Presets { regular: number; half: number; third: number }
interface Props {
  symbol: string;
  ticker: string;
  presets: Presets;
  lastDone: number | null;
  onSubmit: (req: SubmitOrderRequest) => void;
  onMore: () => void;
}

export function QuickOrderRow({ symbol, presets, lastDone, onSubmit, onMore }: Props) {
  const [side, setSide] = useState<"BUY" | "SELL">("BUY");
  const [orderType, setOrderType] = useState<"LIMIT" | "MARKET">("LIMIT");
  const [price, setPrice] = useState<string>(lastDone != null ? lastDone.toFixed(2) : "");
  const [qty, setQty] = useState<string>(String(presets.regular));
  const [presetsOpen, setPresetsOpen] = useState(false);
  useEffect(() => {
    if (orderType === "LIMIT" && lastDone != null) setPrice(lastDone.toFixed(2));
  }, [lastDone, orderType]);

  const submit = () => {
    const p = orderType === "LIMIT" ? parseFloat(price) : null;
    const q = parseInt(qty, 10);
    if (!q || q <= 0) return;
    if (orderType === "LIMIT" && (!p || p <= 0)) return;
    onSubmit({ symbol, side, order_type: orderType, price: p, qty: q, time_in_force: "Day", note: null });
  };

  const total = (() => {
    const p = orderType === "LIMIT" ? parseFloat(price) : lastDone ?? 0;
    const q = parseInt(qty, 10) || 0;
    return p && q ? (p * q).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : "—";
  })();

  return (
    <div className="quick-order">
      <div className="toggle-group">
        <button className={`toggle-btn buy ${side === "BUY" ? "active" : ""}`} onClick={() => setSide("BUY")}>BUY</button>
        <button className={`toggle-btn sell ${side === "SELL" ? "active" : ""}`} onClick={() => setSide("SELL")}>SELL</button>
      </div>
      <div className="toggle-group">
        <button className={`toggle-btn neutral ${orderType === "LIMIT" ? "active" : ""}`} onClick={() => setOrderType("LIMIT")}>LIMIT</button>
        <button className={`toggle-btn neutral ${orderType === "MARKET" ? "active" : ""}`} onClick={() => setOrderType("MARKET")}>MKT</button>
      </div>
      <div className="field">
        <span className="k">价</span>
        <input aria-label="价" className="num-input" type="text" value={price} disabled={orderType === "MARKET"} onChange={(e) => setPrice(e.target.value)} />
      </div>
      <div className="field" style={{ position: "relative" }}>
        <span className="k">数</span>
        <input aria-label="数" className="num-input qty-input" type="text" value={qty} onChange={(e) => setQty(e.target.value)} />
        <button className="row-btn" style={{ padding: "2px 6px", fontSize: 10 }} onClick={() => setPresetsOpen((o) => !o)}>▾</button>
        {presetsOpen && (
          <div style={{ position: "absolute", top: "100%", right: 0, background: "var(--bg-2)", border: "1px solid var(--line-strong)", borderRadius: "var(--radius-card)", padding: 4, zIndex: 5 }}>
            <button className="row-btn" onClick={() => { setQty(String(presets.regular)); setPresetsOpen(false); }}>常规 {presets.regular}</button>
            <button className="row-btn" onClick={() => { setQty(String(presets.half)); setPresetsOpen(false); }}>半仓 {presets.half}</button>
            <button className="row-btn" onClick={() => { setQty(String(presets.third)); setPresetsOpen(false); }}>1/3 {presets.third}</button>
          </div>
        )}
      </div>
      <button className={`submit-btn ${side === "SELL" ? "sell" : ""}`} onClick={submit}>提交</button>
      <button className="more-btn" onClick={onMore}>更多 ▾</button>
      <div className="quick-summary">SIDE <b>{side}</b> · 总额 <b>${total}</b></div>
    </div>
  );
}
```

- [ ] **B.3 Run + commit**

```bash
git add frontend/src/components/Positions/TradingPanel/QuickOrderRow.tsx \
        frontend/src/components/Positions/TradingPanel/QuickOrderRow.test.tsx
git commit -m "feat(trading): QuickOrderRow inline form"
```

---

## 10C. ReplaceOrderPopover

- [ ] **C.1 Test**

```typescript
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ReplaceOrderPopover } from "./ReplaceOrderPopover";

const order = {
  order_id: "ord-1", task_id: null, ticker: "AAPL", symbol: "AAPL.US",
  side: "BUY" as const, order_type: "LIMIT" as const, price: 199.0,
  qty: 200, filled_qty: 0, status: "New", source: "manual" as const,
  submitted_at: null, last_replaced_at: null,
};

describe("ReplaceOrderPopover", () => {
  it("submitting requires at least one changed field", async () => {
    const onSubmit = vi.fn();
    render(<ReplaceOrderPopover order={order} onSubmit={onSubmit} onClose={() => {}} />);
    await userEvent.click(screen.getByRole("button", { name: "确认" }));
    expect(onSubmit).not.toHaveBeenCalled();
  });
  it("submits price change only", async () => {
    const onSubmit = vi.fn();
    render(<ReplaceOrderPopover order={order} onSubmit={onSubmit} onClose={() => {}} />);
    const priceInput = screen.getByLabelText("价") as HTMLInputElement;
    await userEvent.clear(priceInput);
    await userEvent.type(priceInput, "199.50");
    await userEvent.click(screen.getByRole("button", { name: "确认" }));
    expect(onSubmit).toHaveBeenCalledWith({ price: 199.5, qty: null });
  });
});
```

- [ ] **C.2 Implement**

```typescript
import { useState } from "react";
import type { OrderOut, ReplaceOrderRequest } from "../../../api/types";

interface Props {
  order: OrderOut;
  onSubmit: (req: ReplaceOrderRequest) => void;
  onClose: () => void;
}

export function ReplaceOrderPopover({ order, onSubmit, onClose }: Props) {
  const [price, setPrice] = useState<string>(order.price != null ? order.price.toFixed(2) : "");
  const [qty, setQty] = useState<string>(String(order.qty));

  const submit = () => {
    const np = parseFloat(price);
    const nq = parseInt(qty, 10);
    const newPrice = Number.isFinite(np) && np !== order.price ? np : null;
    const newQty = Number.isFinite(nq) && nq !== order.qty ? nq : null;
    if (newPrice == null && newQty == null) return;
    onSubmit({ price: newPrice, qty: newQty });
  };

  return (
    <div className="replace-popover" onClick={(e) => e.stopPropagation()}>
      <div className="field">
        <label>价</label>
        <input aria-label="价" type="text" value={price} onChange={(e) => setPrice(e.target.value)} />
      </div>
      <div className="field">
        <label>量</label>
        <input aria-label="量" type="text" value={qty} onChange={(e) => setQty(e.target.value)} />
      </div>
      <div className="actions">
        <button onClick={onClose}>取消</button>
        <button onClick={submit}>确认</button>
      </div>
    </div>
  );
}
```

- [ ] **C.3 Commit**

```bash
git add frontend/src/components/Positions/TradingPanel/ReplaceOrderPopover.tsx \
        frontend/src/components/Positions/TradingPanel/ReplaceOrderPopover.test.tsx
git commit -m "feat(trading): ReplaceOrderPopover for inline order modify"
```

---

## 10D. FullOrderModal

- [ ] **D.1 Test**

```typescript
import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { FullOrderModal } from "./FullOrderModal";

describe("FullOrderModal", () => {
  it("renders TIF + notes + advanced fields", () => {
    render(<FullOrderModal symbol="AAPL.US" ticker="AAPL" lastDone={199} onSubmit={() => {}} onClose={() => {}} />);
    expect(screen.getByText(/TIF/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/备注/)).toBeInTheDocument();
  });
  it("submit fires onSubmit with full request", async () => {
    const onSubmit = vi.fn();
    render(<FullOrderModal symbol="AAPL.US" ticker="AAPL" lastDone={199} onSubmit={onSubmit} onClose={() => {}} />);
    await userEvent.click(screen.getByRole("button", { name: "提交订单" }));
    expect(onSubmit).toHaveBeenCalled();
  });
});
```

- [ ] **D.2 Implement**

```typescript
import { useState } from "react";
import type { SubmitOrderRequest } from "../../../api/types";

interface Props {
  symbol: string;
  ticker: string;
  lastDone: number | null;
  onSubmit: (req: SubmitOrderRequest) => void;
  onClose: () => void;
}

export function FullOrderModal({ symbol, lastDone, onSubmit, onClose }: Props) {
  const [side, setSide] = useState<"BUY" | "SELL">("BUY");
  const [orderType, setOrderType] = useState<"LIMIT" | "MARKET">("LIMIT");
  const [price, setPrice] = useState<string>(lastDone != null ? lastDone.toFixed(2) : "");
  const [qty, setQty] = useState<string>("100");
  const [tif, setTif] = useState<"Day">("Day");
  const [note, setNote] = useState<string>("");

  const submit = () => {
    const p = orderType === "LIMIT" ? parseFloat(price) : null;
    const q = parseInt(qty, 10);
    if (!q) return;
    if (orderType === "LIMIT" && !p) return;
    onSubmit({ symbol, side, order_type: orderType, price: p, qty: q, time_in_force: tif, note: note || null });
  };

  return (
    <div className="modal-backdrop" onClick={onClose} role="presentation">
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <h3>下单（高级）<button onClick={onClose}>×</button></h3>
        <div className="modal-field"><label>方向</label>
          <button onClick={() => setSide("BUY")} className={side === "BUY" ? "active" : ""}>BUY</button>
          <button onClick={() => setSide("SELL")} className={side === "SELL" ? "active" : ""}>SELL</button>
        </div>
        <div className="modal-field"><label>类型</label>
          <button onClick={() => setOrderType("LIMIT")} className={orderType === "LIMIT" ? "active" : ""}>LIMIT</button>
          <button onClick={() => setOrderType("MARKET")} className={orderType === "MARKET" ? "active" : ""}>MARKET</button>
        </div>
        <div className="modal-field"><label>价格</label>
          <input type="text" value={price} onChange={(e) => setPrice(e.target.value)} disabled={orderType === "MARKET"} />
        </div>
        <div className="modal-field"><label>数量</label>
          <input type="text" value={qty} onChange={(e) => setQty(e.target.value)} />
        </div>
        <div className="modal-field"><label>TIF</label>
          <button onClick={() => setTif("Day")} className="active">Day</button>
        </div>
        <div className="modal-field"><label htmlFor="note">备注</label>
          <input id="note" type="text" value={note} onChange={(e) => setNote(e.target.value)} />
        </div>
        <div className="modal-foot">
          <button onClick={onClose}>取消</button>
          <button onClick={submit}>提交订单</button>
        </div>
      </div>
    </div>
  );
}
```

- [ ] **D.3 Commit**

```bash
git add frontend/src/components/Positions/TradingPanel/FullOrderModal.tsx \
        frontend/src/components/Positions/TradingPanel/FullOrderModal.test.tsx
git commit -m "feat(trading): FullOrderModal advanced order entry"
```

---

## 10E. TradingPanel orchestration

- [ ] **E.1 Implement**

`frontend/src/components/Positions/TradingPanel/TradingPanel.tsx`:

```typescript
import { useEffect, useState } from "react";
import { ordersApi } from "../../../api/orders";
import { useOrdersStore } from "../../../stores/orders";
import { useQuotesStore } from "../../../stores/quotes";
import { ActiveOrdersTable } from "./ActiveOrdersTable";
import { QuickOrderRow } from "./QuickOrderRow";
import { ReplaceOrderPopover } from "./ReplaceOrderPopover";
import { FullOrderModal } from "./FullOrderModal";
import type { OrderOut, SubmitOrderRequest, ReplaceOrderRequest } from "../../../api/types";
import "./TradingPanel.css";

interface Props { ticker: string; symbol: string }

export function TradingPanel({ ticker, symbol }: Props) {
  const orders = useOrdersStore((s) => s.byTicker[ticker]) ?? [];
  const setOrders = useOrdersStore((s) => s.setOrders);
  const removeOrder = useOrdersStore((s) => s.removeOrder);
  const quote = useQuotesStore((s) => s.quotesBySymbol[symbol]);
  const lastDone = quote?.last_done ?? null;
  const [activeOnly, setActiveOnly] = useState(false);
  const [replaceFor, setReplaceFor] = useState<OrderOut | null>(null);
  const [moreOpen, setMoreOpen] = useState(false);
  const [confirmCancel, setConfirmCancel] = useState<OrderOut | null>(null);

  // TODO: source presets from page settings; fallback for now.
  const presets = { regular: 200, half: 100, third: 67 };

  useEffect(() => {
    ordersApi.listToday(ticker).then((r) => setOrders(ticker, r.orders))
      .catch((e) => console.warn("orders fetch failed", e));
  }, [ticker, setOrders]);

  const onSubmit = async (req: SubmitOrderRequest) => {
    try {
      const o = await ordersApi.submit(req);
      useOrdersStore.getState().upsertOrder(o.ticker, o);
    } catch (e) {
      console.error("submit failed", e);
    }
  };
  const onReplace = (o: OrderOut) => setReplaceFor(o);
  const submitReplace = async (req: ReplaceOrderRequest) => {
    if (!replaceFor) return;
    try {
      await ordersApi.replace(replaceFor.order_id, req);
      setReplaceFor(null);
    } catch (e) {
      console.error("replace failed", e);
    }
  };
  const onCancel = (o: OrderOut) => setConfirmCancel(o);
  const confirmCancelFire = async () => {
    if (!confirmCancel) return;
    try {
      await ordersApi.cancel(confirmCancel.order_id);
      removeOrder(ticker, confirmCancel.order_id);
      setConfirmCancel(null);
    } catch (e) {
      console.error("cancel failed", e);
    }
  };

  return (
    <div className="trading-panel">
      <div className="trading-panel-head">
        <div className="alerts-h">活跃订单 · {ticker} · 今日</div>
        <button className="row-btn" onClick={() => setActiveOnly((v) => !v)}>
          {activeOnly ? "全部" : "仅活跃"}
        </button>
      </div>
      <ActiveOrdersTable orders={orders} activeOnly={activeOnly} onReplace={onReplace} onCancel={onCancel} />
      <QuickOrderRow symbol={symbol} ticker={ticker} presets={presets} lastDone={lastDone} onSubmit={onSubmit} onMore={() => setMoreOpen(true)} />
      {replaceFor && <ReplaceOrderPopover order={replaceFor} onSubmit={submitReplace} onClose={() => setReplaceFor(null)} />}
      {moreOpen && <FullOrderModal symbol={symbol} ticker={ticker} lastDone={lastDone} onSubmit={(r) => { onSubmit(r); setMoreOpen(false); }} onClose={() => setMoreOpen(false)} />}
      {confirmCancel && (
        <div className="modal-backdrop" onClick={() => setConfirmCancel(null)} role="presentation">
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <h3>撤销订单</h3>
            <p>确认撤销 {confirmCancel.side} {confirmCancel.qty} {confirmCancel.ticker} @ {confirmCancel.price}？</p>
            <div className="modal-foot">
              <button onClick={() => setConfirmCancel(null)}>取消</button>
              <button className="row-btn danger" onClick={confirmCancelFire}>确认撤单</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
```

`TradingPanel.css`: lift the relevant table / quick-order / modal styles from `.design/trading-panel-and-alerts.html` (sections `.tbl`, `.side-pill`, `.row-actions`, `.quick-order`, `.toggle-group`, `.toggle-btn`, `.submit-btn`, `.more-btn`, `.modal-*`, `.replace-popover`).

- [ ] **E.2 Run all trading-panel tests + typecheck**

```bash
cd frontend
npm test -- --run src/components/Positions/TradingPanel
npm run typecheck
```

Expected: all green.

- [ ] **E.3 Commit**

```bash
git add frontend/src/components/Positions/TradingPanel/TradingPanel.tsx \
        frontend/src/components/Positions/TradingPanel/TradingPanel.css
git commit -m "$(cat <<'EOF'
feat(trading): TradingPanel orchestrates orders flow

Lists today's orders for the ticker, dispatches submit / replace /
cancel through ordersApi + ordersStore, hosts the modal popovers.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```
