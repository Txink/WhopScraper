# Task 11: AlertsPanel + AlertModal

**Files:**
- Create: `frontend/src/components/Positions/AlertsPanel/AlertsPanel.tsx` + `.css`
- Create: `.../AlertModal.tsx`
- Tests: sibling `.test.tsx`

## Steps

- [ ] **Step 1: Test AlertsPanel**

`AlertsPanel.test.tsx`:

```typescript
import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { AlertsPanel } from "./AlertsPanel";
import { useAlertsStore } from "../../../stores/alerts";
import type { AlertOut } from "../../../api/types";

vi.mock("../../../api/alerts", () => ({
  alertsApi: {
    list: vi.fn().mockResolvedValue({ alerts: [] }),
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
```

- [ ] **Step 2: Test AlertModal**

`AlertModal.test.tsx`:

```typescript
import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { AlertModal } from "./AlertModal";

describe("AlertModal", () => {
  it("switching to pct_change shows baseline picker", async () => {
    render(<AlertModal ticker="AAPL" symbol="AAPL.US" onSubmit={() => {}} onClose={() => {}} />);
    await userEvent.click(screen.getByRole("button", { name: /涨跌幅/ }));
    expect(screen.getByText(/今开|昨收/)).toBeInTheDocument();
  });
  it("submit posts price create payload", async () => {
    const onSubmit = vi.fn();
    render(<AlertModal ticker="AAPL" symbol="AAPL.US" onSubmit={onSubmit} onClose={() => {}} />);
    await userEvent.click(screen.getByRole("button", { name: /创建告警/ }));
    expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({
      ticker: "AAPL", symbol: "AAPL.US", condition_type: "price",
    }));
  });
});
```

- [ ] **Step 3: Implement AlertModal**

```typescript
import { useState } from "react";
import type { AlertCreate, AlertOut } from "../../../api/types";

interface Props {
  ticker: string;
  symbol: string;
  initial?: AlertOut;
  onSubmit: (req: AlertCreate) => void;
  onClose: () => void;
}

export function AlertModal({ ticker, symbol, initial, onSubmit, onClose }: Props) {
  const [conditionType, setConditionType] = useState<"price" | "pct_change" | "volume">(
    initial?.condition_type ?? "price"
  );
  const [operator, setOperator] = useState<">=" | "<=">(initial?.operator ?? ">=");
  const [threshold, setThreshold] = useState<string>(String(initial?.threshold ?? ""));
  const [baseline, setBaseline] = useState<"today_open" | "prev_close">(
    initial?.pct_change_baseline ?? "today_open"
  );
  const [volumeWindow, setVolumeWindow] = useState<"1min" | "5min">(
    initial?.volume_window ?? "1min"
  );
  const [repeatMode, setRepeatMode] = useState<"one_shot" | "recurring">(
    initial?.repeat_mode ?? "one_shot"
  );
  const [cooldown, setCooldown] = useState<string>(String(initial?.cooldown_seconds ?? 300));
  const [note, setNote] = useState<string>(initial?.note ?? "");

  const submit = () => {
    const t = parseFloat(threshold);
    if (!Number.isFinite(t)) return;
    onSubmit({
      ticker, symbol,
      condition_type: conditionType, operator, threshold: t,
      pct_change_baseline: conditionType === "pct_change" ? baseline : null,
      volume_window: conditionType === "volume" ? volumeWindow : null,
      repeat_mode: repeatMode,
      cooldown_seconds: parseInt(cooldown, 10) || 300,
      note: note || null,
    });
  };

  return (
    <div className="modal-backdrop" onClick={onClose} role="presentation">
      <div className="modal" role="dialog" aria-label="新建告警" onClick={(e) => e.stopPropagation()}>
        <h3>新建告警 · {ticker}<button onClick={onClose}>×</button></h3>

        <div className="modal-field">
          <span className="modal-field-label">条件类型</span>
          <div className="seg">
            <button className={`seg-btn ${conditionType === "price" ? "active" : ""}`} onClick={() => setConditionType("price")}>价格阈值</button>
            <button className={`seg-btn ${conditionType === "pct_change" ? "active" : ""}`} onClick={() => setConditionType("pct_change")}>涨跌幅</button>
            <button className={`seg-btn ${conditionType === "volume" ? "active" : ""}`} onClick={() => setConditionType("volume")}>成交量</button>
          </div>
        </div>

        <div className="modal-row">
          <div className="modal-field">
            <span className="modal-field-label">方向</span>
            <div className="seg">
              <button className={`seg-btn ${operator === ">=" ? "active" : ""}`} onClick={() => setOperator(">=")}>≥</button>
              <button className={`seg-btn ${operator === "<=" ? "active" : ""}`} onClick={() => setOperator("<=")}>≤</button>
            </div>
          </div>
          <div className="modal-field" style={{ flex: 2 }}>
            <span className="modal-field-label">阈值</span>
            <input className="text-input" type="text" value={threshold} onChange={(e) => setThreshold(e.target.value)} />
          </div>
        </div>

        {conditionType === "pct_change" && (
          <div className="modal-field">
            <span className="modal-field-label">基准</span>
            <div className="seg">
              <button className={`seg-btn ${baseline === "today_open" ? "active" : ""}`} onClick={() => setBaseline("today_open")}>今开</button>
              <button className={`seg-btn ${baseline === "prev_close" ? "active" : ""}`} onClick={() => setBaseline("prev_close")}>昨收</button>
            </div>
          </div>
        )}
        {conditionType === "volume" && (
          <div className="modal-field">
            <span className="modal-field-label">窗口</span>
            <div className="seg">
              <button className={`seg-btn ${volumeWindow === "1min" ? "active" : ""}`} onClick={() => setVolumeWindow("1min")}>1min</button>
              <button className={`seg-btn ${volumeWindow === "5min" ? "active" : ""}`} onClick={() => setVolumeWindow("5min")}>5min</button>
            </div>
          </div>
        )}

        <div className="modal-field">
          <span className="modal-field-label">触发模式</span>
          <div className="seg">
            <button className={`seg-btn ${repeatMode === "one_shot" ? "active" : ""}`} onClick={() => setRepeatMode("one_shot")}>ONE-SHOT</button>
            <button className={`seg-btn ${repeatMode === "recurring" ? "active" : ""}`} onClick={() => setRepeatMode("recurring")}>RECURRING</button>
          </div>
        </div>
        {repeatMode === "recurring" && (
          <div className="modal-field">
            <span className="modal-field-label">节流（秒）</span>
            <input className="text-input" type="text" value={cooldown} onChange={(e) => setCooldown(e.target.value)} />
          </div>
        )}

        <div className="modal-field">
          <span className="modal-field-label">备注（可选）</span>
          <input className="text-input" type="text" value={note} onChange={(e) => setNote(e.target.value)} />
        </div>

        <div className="modal-foot">
          <button className="btn-secondary" onClick={onClose}>取消</button>
          <button className="btn-primary" onClick={submit}>创建告警</button>
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Implement AlertsPanel**

```typescript
import { useEffect, useState } from "react";
import { alertsApi } from "../../../api/alerts";
import { useAlertsStore } from "../../../stores/alerts";
import type { AlertCreate, AlertOut } from "../../../api/types";
import { AlertModal } from "./AlertModal";
import "./AlertsPanel.css";

interface Props { ticker: string; symbol: string }

function fmtCond(a: AlertOut): string {
  const op = a.operator === ">=" ? "≥" : "≤";
  if (a.condition_type === "price") return `价格 ${op} $${a.threshold.toFixed(2)}`;
  if (a.condition_type === "pct_change") {
    const base = a.pct_change_baseline === "today_open" ? "今开" : "昨收";
    return `${a.threshold > 0 ? "涨幅" : "跌幅"} ${op} ${Math.abs(a.threshold).toFixed(2)}% vs ${base}`;
  }
  return `${a.volume_window ?? "1min"} 成交量 ${op} ${a.threshold.toLocaleString("en-US")} 股`;
}

function fmtState(a: AlertOut): { text: string; cls: "triggered" | "never" } {
  if (a.trigger_count === 0) return { text: "未触发", cls: "never" };
  const time = a.last_triggered_at ? new Date(a.last_triggered_at).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" }) : "—";
  return { text: `触发 ${a.trigger_count} 次 · ${time}${a.enabled ? "" : " · 自动禁用"}`, cls: "triggered" };
}

export function AlertsPanel({ ticker, symbol }: Props) {
  const alerts = useAlertsStore((s) => s.byTicker[ticker]) ?? [];
  const setAlerts = useAlertsStore((s) => s.setAlerts);
  const upsertAlert = useAlertsStore((s) => s.upsertAlert);
  const removeAlert = useAlertsStore((s) => s.removeAlert);
  const [modalFor, setModalFor] = useState<"new" | AlertOut | null>(null);
  const [confirmDelete, setConfirmDelete] = useState<AlertOut | null>(null);

  useEffect(() => {
    alertsApi.list(ticker).then((r) => setAlerts(ticker, r.alerts))
      .catch((e) => console.warn("alerts fetch failed", e));
  }, [ticker, setAlerts]);

  const create = async (req: AlertCreate) => {
    try {
      const a = await alertsApi.create(req);
      upsertAlert(a);
      setModalFor(null);
    } catch (e) {
      console.error("create alert failed", e);
    }
  };

  const toggle = async (a: AlertOut) => {
    try {
      const updated = await alertsApi.update(a.id, { enabled: !a.enabled });
      upsertAlert(updated);
    } catch (e) {
      console.error("toggle alert failed", e);
    }
  };

  const remove = async (a: AlertOut) => {
    try {
      await alertsApi.remove(a.id);
      removeAlert(a.id);
      setConfirmDelete(null);
    } catch (e) {
      console.error("delete alert failed", e);
    }
  };

  const enabledCount = alerts.filter((a) => a.enabled).length;

  return (
    <div className="alerts-panel">
      <div className="alerts-head">
        <div className="alerts-h">告警 · {ticker} · 共 {alerts.length} 条 · 启用 {enabledCount}</div>
        <button className="alert-add-btn" onClick={() => setModalFor("new")}>+ 添加告警</button>
      </div>

      {alerts.map((a) => {
        const state = fmtState(a);
        return (
          <div key={a.id} className={`alert-row ${a.enabled ? "" : "disabled"}`}>
            <input type="checkbox" checked={a.enabled} onChange={() => toggle(a)} />
            <div>
              <div className="alert-cond">{fmtCond(a)}</div>
              <div className="alert-meta">
                <span className={`alert-mode ${a.repeat_mode === "recurring" ? "recurring" : ""}`}>
                  {a.repeat_mode === "one_shot" ? "ONE-SHOT" : `RECURRING · ${a.cooldown_seconds}s 节流`}
                </span>
                <span className={`alert-state ${state.cls}`}>{state.text}</span>
                {a.note && <span style={{ color: "var(--fg-3)", fontStyle: "italic" }}>— {a.note}</span>}
              </div>
            </div>
            <div></div>
            <div className="alert-actions">
              <button className="row-btn" onClick={() => setModalFor(a)}>编辑</button>
              <button className="row-btn danger" onClick={() => setConfirmDelete(a)}>×</button>
            </div>
          </div>
        );
      })}

      {modalFor && (
        <AlertModal
          ticker={ticker} symbol={symbol}
          initial={modalFor === "new" ? undefined : modalFor}
          onSubmit={create} onClose={() => setModalFor(null)}
        />
      )}
      {confirmDelete && (
        <div className="modal-backdrop" onClick={() => setConfirmDelete(null)} role="presentation">
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <h3>确认删除告警？</h3>
            <p>{fmtCond(confirmDelete)} — 删除后无法恢复。</p>
            <div className="modal-foot">
              <button className="btn-secondary" onClick={() => setConfirmDelete(null)}>取消</button>
              <button className="row-btn danger" onClick={() => remove(confirmDelete)}>删除</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
```

`AlertsPanel.css`: lift relevant styles from mockup (`.alerts-head`, `.alert-add-btn`, `.alert-row`, `.alert-cond`, `.alert-meta`, `.alert-mode`, `.alert-state`, `.alert-actions`, `.modal-*`, `.seg`, `.seg-btn`, `.text-input`, `.btn-secondary`, `.btn-primary`).

- [ ] **Step 5: Run + typecheck**

```bash
cd frontend
npm test -- --run src/components/Positions/AlertsPanel
npm run typecheck
```

Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/Positions/AlertsPanel/
git commit -m "$(cat <<'EOF'
feat(alerts): AlertsPanel + AlertModal CRUD UI

Per-ticker list with enable toggle + delete confirm + edit;
AlertModal supports price / pct_change / volume condition tabs and
repeat-mode picker with cooldown override.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```
