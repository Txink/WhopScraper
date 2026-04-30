import { useEffect, useState } from "react";
import { api, type SimScenarioOverview } from "../../api/http";
import "./SimPanel.css";

export interface SimPanelProps {
  open: boolean;
  onClose: () => void;
}

interface RunRecord {
  /** Wall-clock when the run was triggered (for de-duping rapid clicks). */
  ts: number;
  scenarioName: string;
  scenarioLabel: string;
  messageId: string;
  status: "running" | "done" | "error";
  error?: string;
}

export function SimPanel({ open, onClose }: SimPanelProps) {
  const [scenarios, setScenarios] = useState<SimScenarioOverview[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [runs, setRuns] = useState<RunRecord[]>([]);
  // Names currently running — disables the button to prevent rapid double-fires.
  const [pending, setPending] = useState<Set<string>>(new Set());

  useEffect(() => {
    if (!open || scenarios !== null) return;
    let cancelled = false;
    setLoadError(null);
    api.listSimScenarios()
      .then((r) => { if (!cancelled) setScenarios(r.scenarios); })
      .catch((e: Error) => { if (!cancelled) setLoadError(e.message); });
    return () => { cancelled = true; };
  }, [open, scenarios]);

  if (!open) return null;

  const runScenario = async (s: SimScenarioOverview) => {
    if (pending.has(s.name)) return;
    setPending((prev) => new Set(prev).add(s.name));
    try {
      const result = await api.runSimScenario(s.name);
      setRuns((prev) => [
        {
          ts: Date.now(),
          scenarioName: s.name,
          scenarioLabel: s.label,
          messageId: result.message_id,
          status: "running",
        },
        ...prev,
      ].slice(0, 20));
      // Mark as done after a generous timeout matching the longest scenario
      // (modify_price_qty_then_cancel ≈ 6s). Frontend has no other signal
      // since the runner is fire-and-forget.
      const totalDelay = (s.push_step_count + 1) * 1500 + 3000;
      setTimeout(() => {
        setRuns((prev) => prev.map((r) =>
          r.messageId === result.message_id ? { ...r, status: "done" } : r,
        ));
      }, Math.min(totalDelay, 15000));
    } catch (e) {
      setRuns((prev) => [
        {
          ts: Date.now(),
          scenarioName: s.name,
          scenarioLabel: s.label,
          messageId: "",
          status: "error",
          error: (e as Error).message,
        },
        ...prev,
      ].slice(0, 20));
    } finally {
      // Re-enable after a short cool-down (button should not stay disabled
      // forever — the run continues in the background regardless).
      setTimeout(() => {
        setPending((prev) => {
          const next = new Set(prev);
          next.delete(s.name);
          return next;
        });
      }, 1500);
    }
  };

  return (
    <div className="sim-overlay" onClick={onClose} role="dialog" aria-label="模拟器">
      <div className="sim-modal" onClick={(e) => e.stopPropagation()}>
        <div className="sim-header">
          <span className="sim-title">模拟器 · 触发场景</span>
          <span className="sim-subtitle">
            模拟数据走真实的 message → parse → DB → WS 链路；推送由 PushListener 处理；
            和真实订单一样落库 + 渲染
          </span>
          <button className="sim-close" onClick={onClose} aria-label="关闭">×</button>
        </div>

        <div className="sim-body">
          {loadError && <div className="sim-error">加载场景失败：{loadError}</div>}
          {scenarios === null && !loadError && <div className="sim-loading">加载中…</div>}
          {scenarios !== null && (
            <ul className="sim-scenario-list">
              {scenarios.map((s) => (
                <li key={s.name} className="sim-scenario-item">
                  <div className="sim-scenario-info">
                    <span className="sim-scenario-label">{s.label}</span>
                    <span className="sim-scenario-desc">{s.description}</span>
                    <span className="sim-scenario-meta">
                      <span className="k">msg</span>{" "}
                      <span className="v">{s.message_text}</span>
                      {" · "}
                      <span className="k">push</span>{" "}
                      <span className="v">{s.push_step_count}</span>
                    </span>
                  </div>
                  <button
                    className="sim-run-btn"
                    onClick={() => runScenario(s)}
                    disabled={pending.has(s.name)}
                  >
                    {pending.has(s.name) ? "运行中…" : "运行"}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>

        {runs.length > 0 && (
          <div className="sim-history">
            <div className="sim-history-head">最近运行</div>
            <ul>
              {runs.map((r) => (
                <li key={`${r.ts}-${r.messageId}`} className={`sim-history-item ${r.status}`}>
                  <span className="ts">{new Date(r.ts).toLocaleTimeString("zh-CN", { hour12: false })}</span>
                  <span className="label">{r.scenarioLabel}</span>
                  {r.messageId && (
                    <span className="msg-id" title={r.messageId}>{r.messageId.slice(0, 24)}</span>
                  )}
                  <span className="status">{r.status === "running" ? "进行中" : r.status === "done" ? "完成" : `失败：${r.error}`}</span>
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </div>
  );
}
