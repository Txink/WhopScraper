import { useEffect, useState } from "react";
import { alertsApi } from "../../../api/alerts";
import { useAlertsStore } from "../../../stores/alerts";
import type { AlertCreate, AlertOut } from "../../../api/alerts";
import { ConfirmModal } from "../ConfirmModal";
import { AlertModal } from "./AlertModal";
import "./AlertsPanel.css";

interface Props {
  ticker: string;
  symbol: string;
  /** Optional hooks for callers (DetailPane) that want to host the
   *  create/edit + delete-confirm modals themselves — so they render
   *  at the .detail-pane level rather than inside the swipe-track's
   *  transformed subtree (which mis-positions absolute/fixed children).
   *  When omitted, AlertsPanel falls back to rendering both modals
   *  itself. */
  onRequestAddOrEdit?: (initial: AlertOut | null) => void;
  onRequestDelete?: (alert: AlertOut) => void;
}

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

export function AlertsPanel({ ticker, symbol, onRequestAddOrEdit, onRequestDelete }: Props) {
  const alerts = useAlertsStore((s) => s.byTicker[ticker]) ?? [];
  const setAlerts = useAlertsStore((s) => s.setAlerts);
  const upsertAlert = useAlertsStore((s) => s.upsertAlert);
  const removeAlert = useAlertsStore((s) => s.removeAlert);
  // Fallback modal state used only when the caller doesn't host them.
  const [fallbackModalFor, setFallbackModalFor] = useState<"new" | AlertOut | null>(null);
  const [fallbackConfirmDelete, setFallbackConfirmDelete] = useState<AlertOut | null>(null);

  useEffect(() => {
    alertsApi.list(ticker).then((r) => setAlerts(ticker, r.alerts))
      .catch((e) => console.warn("alerts fetch failed", e));
  }, [ticker, setAlerts]);

  const createOrUpdate = async (req: AlertCreate) => {
    try {
      const a = await alertsApi.create(req);
      upsertAlert(a);
      setFallbackModalFor(null);
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
    } catch (e) {
      console.error("delete alert failed", e);
    } finally {
      setFallbackConfirmDelete(null);
    }
  };

  const openAddOrEdit = (initial: AlertOut | null) => {
    if (onRequestAddOrEdit) onRequestAddOrEdit(initial);
    else setFallbackModalFor(initial ?? "new");
  };
  const askDelete = (a: AlertOut) => {
    if (onRequestDelete) onRequestDelete(a);
    else setFallbackConfirmDelete(a);
  };

  const enabledCount = alerts.filter((a) => a.enabled).length;

  return (
    <div className="panel alerts-panel">
      <div className="alerts-head">
        <div className="alerts-h">告警 · {ticker} · 共 {alerts.length} 条 · 启用 {enabledCount}</div>
        <button className="alert-add-btn" onClick={() => openAddOrEdit(null)}>+ 添加告警</button>
      </div>

      <div className="alerts-body">
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
                <button className="row-btn" onClick={() => openAddOrEdit(a)}>编辑</button>
                <button className="row-btn danger" onClick={() => askDelete(a)}>×</button>
              </div>
            </div>
          );
        })}
      </div>

      <div className="tab-foot">
        <span className="tab-foot-left">
          <button type="button" className="trade-menu-btn" aria-label="告警设置" title="告警设置（暂未启用）">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <circle cx="12" cy="12" r="3" />
              <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09a1.65 1.65 0 0 0-1-1.51 1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09a1.65 1.65 0 0 0 1.51-1 1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
            </svg>
          </button>
          <span>告警 · 启用 {enabledCount} / 共 {alerts.length}</span>
        </span>
      </div>

      {/* Fallback in-pane modals (only when caller doesn't host them).
       *  These render inside the swipe-track's transformed subtree, so
       *  positioning may be off — only safe in standalone tests. */}
      {fallbackModalFor && (
        <AlertModal
          ticker={ticker} symbol={symbol}
          initial={fallbackModalFor === "new" ? undefined : fallbackModalFor}
          onSubmit={createOrUpdate}
          onClose={() => setFallbackModalFor(null)}
        />
      )}
      {fallbackConfirmDelete && (
        <ConfirmModal
          title="确认删除告警？"
          description={`${fmtCond(fallbackConfirmDelete)} — 删除后无法恢复。`}
          confirmLabel="删除"
          danger
          onCancel={() => setFallbackConfirmDelete(null)}
          onConfirm={() => remove(fallbackConfirmDelete)}
        />
      )}
    </div>
  );
}
