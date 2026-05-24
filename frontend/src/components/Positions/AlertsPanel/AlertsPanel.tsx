import { useEffect, useState } from "react";
import { alertsApi } from "../../../api/alerts";
import { useAlertsStore } from "../../../stores/alerts";
import type { AlertCreate, AlertOut } from "../../../api/alerts";
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
