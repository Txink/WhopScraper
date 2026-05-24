import { useEffect, useState } from "react";
import type { AlertCreate, AlertOut } from "../../../api/alerts";

interface Props {
  ticker: string;
  symbol: string;
  initial?: AlertOut;
  onSubmit: (req: AlertCreate) => void;
  onClose: () => void;
  /** "bottom" anchors the card near the bottom of .detail-pane so it
   *  pops up close to the AlertsPanel that triggered it, rather than
   *  floating in the vertical middle. Default "center". */
  placement?: "center" | "bottom";
}

/** Alert create/edit modal. Mirrors the project's PairDetailModal
 *  pattern (.pair-modal-backdrop + .modal-card) so it anchors inside
 *  .detail-pane rather than the viewport — avoids the swipe-track
 *  transform issue that would mis-position position:fixed children. */
export function AlertModal({ ticker, symbol, initial, onSubmit, onClose, placement = "center" }: Props) {
  const [conditionType, setConditionType] = useState<"price" | "pct_change" | "volume">(
    initial?.condition_type ?? "price"
  );
  const [operator, setOperator] = useState<">=" | "<=">(initial?.operator ?? ">=");
  const [threshold, setThreshold] = useState<string>(String(initial?.threshold ?? "0"));
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

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

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

  const title = initial ? `编辑告警 · ${ticker}` : `新建告警 · ${ticker}`;

  return (
    <div
      className={`pair-modal-backdrop ${placement === "bottom" ? "placement-bottom" : ""}`}
      role="presentation"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="modal-card alert-modal" role="dialog" aria-label={title}>
        <header className="modal-head">
          <h3>{title}</h3>
          <button type="button" className="modal-close" onClick={onClose} aria-label="关闭">×</button>
        </header>

        <div className="modal-field">
          <span className="modal-field-label">条件类型</span>
          <div className="seg">
            <button type="button" className={`seg-btn ${conditionType === "price" ? "active" : ""}`} onClick={() => setConditionType("price")}>价格阈值</button>
            <button type="button" className={`seg-btn ${conditionType === "pct_change" ? "active" : ""}`} onClick={() => setConditionType("pct_change")}>涨跌幅</button>
            <button type="button" className={`seg-btn ${conditionType === "volume" ? "active" : ""}`} onClick={() => setConditionType("volume")}>成交量</button>
          </div>
        </div>

        <div className="modal-row">
          <div className="modal-field">
            <span className="modal-field-label">方向</span>
            <div className="seg">
              <button type="button" className={`seg-btn ${operator === ">=" ? "active" : ""}`} onClick={() => setOperator(">=")}>≥</button>
              <button type="button" className={`seg-btn ${operator === "<=" ? "active" : ""}`} onClick={() => setOperator("<=")}>≤</button>
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
              <button type="button" className={`seg-btn ${baseline === "today_open" ? "active" : ""}`} onClick={() => setBaseline("today_open")}>今开</button>
              <button type="button" className={`seg-btn ${baseline === "prev_close" ? "active" : ""}`} onClick={() => setBaseline("prev_close")}>昨收</button>
            </div>
          </div>
        )}
        {conditionType === "volume" && (
          <div className="modal-field">
            <span className="modal-field-label">窗口</span>
            <div className="seg">
              <button type="button" className={`seg-btn ${volumeWindow === "1min" ? "active" : ""}`} onClick={() => setVolumeWindow("1min")}>1min</button>
              <button type="button" className={`seg-btn ${volumeWindow === "5min" ? "active" : ""}`} onClick={() => setVolumeWindow("5min")}>5min</button>
            </div>
          </div>
        )}

        <div className="modal-field">
          <span className="modal-field-label">触发模式</span>
          <div className="seg">
            <button type="button" className={`seg-btn ${repeatMode === "one_shot" ? "active" : ""}`} onClick={() => setRepeatMode("one_shot")}>ONE-SHOT</button>
            <button type="button" className={`seg-btn ${repeatMode === "recurring" ? "active" : ""}`} onClick={() => setRepeatMode("recurring")}>RECURRING</button>
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

        <footer className="pair-modal-foot alert-modal-foot">
          <button type="button" className="btn ghost" onClick={onClose}>取消</button>
          <button type="button" className="btn primary" onClick={submit}>
            {initial ? "保存" : "创建告警"}
          </button>
        </footer>
      </div>
    </div>
  );
}
