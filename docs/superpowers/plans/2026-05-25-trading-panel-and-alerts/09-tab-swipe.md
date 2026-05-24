# Task 9: DetailTabSwipe + Footer + DetailPane integration

**Files:**
- Create: `frontend/src/components/Positions/DetailTabSwipe.tsx` + `.css`
- Create: `frontend/src/components/Positions/DetailTabFooter.tsx`
- Modify: `frontend/src/components/Positions/DetailPane.tsx`
- Test: `frontend/src/components/Positions/DetailTabSwipe.test.tsx`

## Steps

- [ ] **Step 1: Failing test**

`frontend/src/components/Positions/DetailTabSwipe.test.tsx`:

```typescript
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { DetailTabSwipe } from "./DetailTabSwipe";

const tabs = [
  { id: "records", label: "交易记录", content: <div data-testid="t0">tab0</div> },
  { id: "trading", label: "交易面板", content: <div data-testid="t1">tab1</div> },
  { id: "alerts",  label: "告警",     content: <div data-testid="t2">tab2</div> },
];

describe("DetailTabSwipe", () => {
  it("renders all three tabs initially mounted (for swipe continuity)", () => {
    render(<DetailTabSwipe tabs={tabs} index={1} onIndexChange={() => {}} />);
    expect(screen.getByTestId("t0")).toBeInTheDocument();
    expect(screen.getByTestId("t1")).toBeInTheDocument();
    expect(screen.getByTestId("t2")).toBeInTheDocument();
  });

  it("clicking an indicator dot fires onIndexChange", async () => {
    const onIndex = vi.fn();
    render(<DetailTabSwipe tabs={tabs} index={0} onIndexChange={onIndex} />);
    const dots = screen.getAllByRole("button", { name: /切换到/ });
    await userEvent.click(dots[2]!);
    expect(onIndex).toHaveBeenCalledWith(2);
  });

  it("ArrowRight increments tab; ArrowLeft decrements; clamps at edges", async () => {
    const onIndex = vi.fn();
    const { rerender } = render(
      <DetailTabSwipe tabs={tabs} index={0} onIndexChange={onIndex} />
    );
    const container = screen.getByTestId("detail-tab-swipe");
    container.focus();
    await userEvent.keyboard("{ArrowRight}");
    expect(onIndex).toHaveBeenLastCalledWith(1);
    rerender(<DetailTabSwipe tabs={tabs} index={2} onIndexChange={onIndex} />);
    container.focus();
    await userEvent.keyboard("{ArrowRight}");  // already at max; no change
    expect(onIndex).toHaveBeenLastCalledWith(2);
  });

  it("footer shows the active tab's label", () => {
    render(<DetailTabSwipe tabs={tabs} index={1} onIndexChange={() => {}} />);
    expect(screen.getByText("交易面板")).toBeInTheDocument();
  });

  it("⚙ click invokes onOpenSettings with active index", async () => {
    const onSettings = vi.fn();
    render(
      <DetailTabSwipe tabs={tabs} index={1} onIndexChange={() => {}} onOpenSettings={onSettings} />
    );
    await userEvent.click(screen.getByRole("button", { name: /设置/ }));
    expect(onSettings).toHaveBeenCalledWith(1);
  });

  it("mouse drag past threshold changes tab", () => {
    const onIndex = vi.fn();
    render(<DetailTabSwipe tabs={tabs} index={1} onIndexChange={onIndex} />);
    const container = screen.getByTestId("detail-tab-swipe");
    fireEvent.mouseDown(container, { clientX: 500 });
    fireEvent.mouseMove(container, { clientX: 400 });  // > 50px = swipe left → next
    fireEvent.mouseUp(container, { clientX: 400 });
    expect(onIndex).toHaveBeenCalledWith(2);
  });

  it("clicking an input inside content does NOT trigger drag", () => {
    const onIndex = vi.fn();
    const tabsWithInput = [
      ...tabs.slice(0, 1),
      { id: "trading", label: "交易面板", content: <input data-testid="inp" /> },
      ...tabs.slice(2),
    ];
    render(<DetailTabSwipe tabs={tabsWithInput} index={1} onIndexChange={onIndex} />);
    const inp = screen.getByTestId("inp");
    fireEvent.mouseDown(inp, { clientX: 500 });
    fireEvent.mouseMove(inp, { clientX: 400 });
    fireEvent.mouseUp(inp, { clientX: 400 });
    expect(onIndex).not.toHaveBeenCalled();
  });
});
```

- [ ] **Step 2: Verify failure**

```bash
cd frontend && npm test -- --run src/components/Positions/DetailTabSwipe.test.tsx
```

Expected: Module-not-found.

- [ ] **Step 3: Implement component**

`frontend/src/components/Positions/DetailTabSwipe.tsx`:

```typescript
import {
  useCallback, useEffect, useRef, useState, type ReactNode,
} from "react";
import { DetailTabFooter } from "./DetailTabFooter";
import "./DetailTabSwipe.css";

export interface TabDef {
  id: string;
  label: string;
  content: ReactNode;
}

interface Props {
  tabs: TabDef[];
  index: number;
  onIndexChange: (i: number) => void;
  onOpenSettings?: (i: number) => void;
}

const DRAG_THRESHOLD_PX = 8;
const SWIPE_DISTANCE_PX = 50;
const SWIPE_VELOCITY = 0.4;  // px/ms

function isFormTarget(el: EventTarget | null): boolean {
  if (!(el instanceof HTMLElement)) return false;
  const tag = el.tagName;
  return (
    tag === "INPUT" || tag === "SELECT" || tag === "TEXTAREA" || tag === "BUTTON" ||
    el.isContentEditable
  );
}

export function DetailTabSwipe({ tabs, index, onIndexChange, onOpenSettings }: Props) {
  const max = tabs.length - 1;
  const [dragDx, setDragDx] = useState(0);
  const startRef = useRef<{ x: number; t: number; pointerId: number | null } | null>(null);

  const onKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLDivElement>) => {
      if (e.key === "ArrowRight" && index < max) {
        onIndexChange(index + 1);
      } else if (e.key === "ArrowLeft" && index > 0) {
        onIndexChange(index - 1);
      }
    },
    [index, max, onIndexChange],
  );

  const startDrag = (clientX: number, target: EventTarget | null) => {
    if (isFormTarget(target)) return;
    startRef.current = { x: clientX, t: Date.now(), pointerId: null };
    setDragDx(0);
  };
  const moveDrag = (clientX: number) => {
    const s = startRef.current;
    if (!s) return;
    setDragDx(clientX - s.x);
  };
  const endDrag = (clientX: number) => {
    const s = startRef.current;
    startRef.current = null;
    if (!s) return;
    const dx = clientX - s.x;
    const dt = Math.max(1, Date.now() - s.t);
    const velocity = Math.abs(dx) / dt;
    setDragDx(0);
    if (Math.abs(dx) < DRAG_THRESHOLD_PX) return;
    const shouldSwipe = Math.abs(dx) > SWIPE_DISTANCE_PX || velocity > SWIPE_VELOCITY;
    if (!shouldSwipe) return;
    if (dx < 0 && index < max) onIndexChange(index + 1);
    else if (dx > 0 && index > 0) onIndexChange(index - 1);
  };

  // Mouse
  const onMouseDown = (e: React.MouseEvent<HTMLDivElement>) => startDrag(e.clientX, e.target);
  const onMouseMove = (e: React.MouseEvent<HTMLDivElement>) => moveDrag(e.clientX);
  const onMouseUp = (e: React.MouseEvent<HTMLDivElement>) => endDrag(e.clientX);

  // Touch
  const onTouchStart = (e: React.TouchEvent<HTMLDivElement>) => {
    const t = e.touches[0];
    if (!t) return;
    startDrag(t.clientX, e.target);
  };
  const onTouchMove = (e: React.TouchEvent<HTMLDivElement>) => {
    const t = e.touches[0];
    if (!t) return;
    moveDrag(t.clientX);
  };
  const onTouchEnd = (e: React.TouchEvent<HTMLDivElement>) => {
    const t = e.changedTouches[0];
    if (!t) return;
    endDrag(t.clientX);
  };

  // Cancel drag if pointer leaves window mid-drag
  useEffect(() => {
    const cancel = () => {
      startRef.current = null;
      setDragDx(0);
    };
    window.addEventListener("mouseleave", cancel);
    window.addEventListener("blur", cancel);
    return () => {
      window.removeEventListener("mouseleave", cancel);
      window.removeEventListener("blur", cancel);
    };
  }, []);

  const translatePct = -index * 100;
  const transform = `translateX(calc(${translatePct}% + ${dragDx}px))`;

  return (
    <div
      className="detail-tab-swipe"
      data-testid="detail-tab-swipe"
      tabIndex={0}
      onKeyDown={onKeyDown}
      onMouseDown={onMouseDown}
      onMouseMove={onMouseMove}
      onMouseUp={onMouseUp}
      onTouchStart={onTouchStart}
      onTouchMove={onTouchMove}
      onTouchEnd={onTouchEnd}
    >
      <div className="detail-tab-track" style={{ transform }}>
        {tabs.map((t) => (
          <div className="detail-tab-pane" key={t.id}>
            {t.content}
          </div>
        ))}
      </div>
      <DetailTabFooter
        tabs={tabs}
        index={index}
        onIndexChange={onIndexChange}
        onOpenSettings={onOpenSettings}
      />
    </div>
  );
}
```

`frontend/src/components/Positions/DetailTabFooter.tsx`:

```typescript
import type { TabDef } from "./DetailTabSwipe";

interface Props {
  tabs: TabDef[];
  index: number;
  onIndexChange: (i: number) => void;
  onOpenSettings?: (i: number) => void;
}

export function DetailTabFooter({ tabs, index, onIndexChange, onOpenSettings }: Props) {
  const active = tabs[index]!;
  return (
    <div className="detail-tab-footer">
      <button
        type="button"
        className="detail-tab-footer-settings"
        onClick={() => onOpenSettings?.(index)}
        aria-label={`${active.label} 设置`}
      >
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <circle cx="12" cy="12" r="3" />
          <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09a1.65 1.65 0 0 0-1-1.51 1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09a1.65 1.65 0 0 0 1.51-1 1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
        </svg>
        <span>{active.label}</span>
      </button>
      <div className="detail-tab-indicator">
        {tabs.map((t, i) => (
          <button
            type="button"
            key={t.id}
            className={`detail-tab-dot ${i === index ? "active" : ""}`}
            onClick={() => onIndexChange(i)}
            aria-label={`切换到 ${t.label}`}
          />
        ))}
      </div>
    </div>
  );
}
```

`frontend/src/components/Positions/DetailTabSwipe.css` (copy the relevant styles from the mockup file `.design/trading-panel-and-alerts.html` — sections `.bottom-card`, `.bottom-body`, `.bottom-footer`, `.tab-indicator`, `.tab-dot`, `.footer-settings`; rename selectors to `.detail-tab-*`):

```css
.detail-tab-swipe {
  flex: 1 1 auto;
  min-height: 0;
  display: flex; flex-direction: column;
  position: relative;
  overflow: hidden;
  background: var(--bg-2);
  border: 1px solid var(--line);
  border-radius: var(--radius-card);
  outline: none;
}
.detail-tab-track {
  flex: 1 1 auto;
  min-height: 0;
  display: flex;
  width: 100%;
  transition: transform 220ms cubic-bezier(.4, 0, .2, 1);
  will-change: transform;
}
.detail-tab-track:active { transition: none; }
.detail-tab-pane {
  flex: 0 0 100%;
  min-width: 0;
  min-height: 0;
  overflow: auto;
  padding: 12px 14px;
}
.detail-tab-footer {
  height: 36px;
  border-top: 1px solid var(--line);
  display: flex; align-items: center;
  padding: 0 12px;
  position: relative;
  background: var(--bg-2);
}
.detail-tab-footer-settings {
  display: inline-flex; align-items: center; gap: 6px;
  color: var(--fg-3); font-size: 11px;
  background: transparent; border: 0; padding: 4px;
  border-radius: var(--radius-chip);
  transition: color var(--dur) var(--ease);
  cursor: pointer;
}
.detail-tab-footer-settings:hover { color: var(--fg-1); }
.detail-tab-indicator {
  position: absolute;
  left: 50%; top: 50%;
  transform: translate(-50%, -50%);
  display: flex; gap: 6px; align-items: center;
}
.detail-tab-dot {
  width: 6px; height: 6px;
  border-radius: 50%;
  background: var(--fg-3);
  transition: all var(--dur) var(--ease);
  cursor: pointer; border: 0; padding: 0;
}
.detail-tab-dot.active {
  width: 16px;
  border-radius: 3px;
  background: var(--brand);
}
.detail-tab-dot:hover:not(.active) { background: var(--fg-2); }
```

- [ ] **Step 4: Run tests**

```bash
cd frontend && npm test -- --run src/components/Positions/DetailTabSwipe.test.tsx
```

Expected: all pass.

- [ ] **Step 5: Wire into DetailPane**

In `frontend/src/components/Positions/DetailPane.tsx`, replace the `<TradeList .../>` block at the bottom of the return JSX with:

```tsx
import { DetailTabSwipe, type TabDef } from "./DetailTabSwipe";
import { TradingPanel } from "./TradingPanel/TradingPanel";  // created in Task 10
import { AlertsPanel } from "./AlertsPanel/AlertsPanel";     // created in Task 11
import { useDetailViewStore } from "../../stores/detailView";

// inside DetailPane render, replace <TradeList .../> with:
const tabIndex = useDetailViewStore((s) => s.tabIndex);
const setTabIndex = useDetailViewStore((s) => s.setTabIndex);

const tabs: TabDef[] = [
  {
    id: "records",
    label: "交易记录",
    content: (
      <TradeList
        trades={trades}
        pairs={isOption ? [] : pairs}
        ticker={ticker}
        lastSyncedAt={lastSyncedAt}
        disableBinding={isOption}
        totalCount={tradesTotal}
        loading={tradesLoading}
        onRequestMore={loadMoreTrades}
        onConfirmBind={onConfirmBind}
        onExtendPair={onExtendPair}
        filter={tradeFilter}
        onFilterChange={setTradeFilter}
        onClearAllPairs={onClearAllPairs}
        onSyncRecentTrades={onSyncRecentTrades}
        onRefetchTrades={onRefetchTrades}
        onClearAllTrades={onClearAllTrades}
      />
    ),
  },
  { id: "trading", label: "交易面板", content: <TradingPanel ticker={ticker} symbol={symbol} /> },
  { id: "alerts", label: "告警",   content: <AlertsPanel ticker={ticker} symbol={symbol} /> },
];

return (
  <div className="detail-pane">
    <DetailSummary {...summaryProps} />
    <div className="detail-chart-card">{/* ... existing chart head + wrap ... */}</div>
    <DetailTabSwipe
      tabs={tabs}
      index={tabIndex}
      onIndexChange={setTabIndex}
      onOpenSettings={(i) => {
        // each panel exposes its own settings via a tiny imperative store;
        // forward to the active panel's settings opener.
      }}
    />
    {/* existing pair-modal + confirm-modal stay outside the swipe container */}
  </div>
);
```

(Settings opener implementation deferred — Tasks 10/11 add their own popovers; the prop hook above will be filled in by those tasks. Until then `onOpenSettings` may be a no-op.)

- [ ] **Step 6: Run typecheck + tests**

```bash
cd frontend
npm run typecheck
npm test -- --run src/components/Positions
```

Note: `TradingPanel` and `AlertsPanel` don't exist yet — temporarily stub them as `() => <div />` so this task compiles. They're implemented in Tasks 10 & 11.

Stub in same step:

```typescript
// frontend/src/components/Positions/TradingPanel/TradingPanel.tsx (stub)
export function TradingPanel(_: { ticker: string; symbol: string }) { return <div>TradingPanel</div>; }
// frontend/src/components/Positions/AlertsPanel/AlertsPanel.tsx (stub)
export function AlertsPanel(_: { ticker: string; symbol: string }) { return <div>AlertsPanel</div>; }
```

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/Positions/DetailTabSwipe.tsx \
        frontend/src/components/Positions/DetailTabSwipe.css \
        frontend/src/components/Positions/DetailTabFooter.tsx \
        frontend/src/components/Positions/DetailTabSwipe.test.tsx \
        frontend/src/components/Positions/DetailPane.tsx \
        frontend/src/components/Positions/TradingPanel/TradingPanel.tsx \
        frontend/src/components/Positions/AlertsPanel/AlertsPanel.tsx
git commit -m "$(cat <<'EOF'
feat(detail): swipeable 3-tab container with footer indicator

DetailTabSwipe replaces the TradeList slot — left-right drag / keyboard
/ dot-click navigates between records / trading / alerts tabs. Footer
shows ⚙ + active tab name on the left and a 3-dot indicator centered.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```
