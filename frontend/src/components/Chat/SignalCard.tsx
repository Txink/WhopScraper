import type { TaskSummary, PushEvent } from "../../api/domain-types";
import { layersForTask } from "./signalCardHelpers";
import { ConfirmActions } from "../Card/ConfirmActions";
import { PushChain } from "../Card/PushChain";
import { fmtBeijingFull } from "../Card/cardHelpers";
import "./SignalCard.css";

export interface SignalCardProps {
  task: TaskSummary;
  pushEvents: PushEvent[];
  /** Controlled: parent decides whether this card is expanded. */
  expanded: boolean;
  /** Click the bubble → parent toggles. */
  onToggle(): void;
  autoTrade: boolean;
}

export function SignalCard({
  task, pushEvents, expanded, onToggle, autoTrade,
}: SignalCardProps): JSX.Element {
  const layers = layersForTask(task, { autoTrade });
  const sourceClass =
    layers.kind === "parse_error" ? "neutral"
    : task.type === "option" ? "option"
    : "stock";

  return (
    <div
      className={`signal-bubble ${sourceClass}`}
      data-state={expanded ? "expanded" : "folded"}
      role="button"
      tabIndex={0}
      onClick={(e) => {
        if ((e.target as HTMLElement).closest(".confirm-pair")) return;
        onToggle();
      }}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onToggle();
        }
      }}
    >
      <div className="signal-summary">
        {/* Layer 1: MSG */}
        <div className="layer-msg" title={layers.msg}>{layers.msg}</div>

        {/* Layer 2: SIG */}
        {layers.sig && (
          <div className="layer-sig">
            {layers.sig.error ? (
              <span className="layer-error">{layers.sig.error}</span>
            ) : (
              <>
                {layers.sig.side && (
                  <span className={`side-chip ${layers.sig.side.toLowerCase()}`}>{layers.sig.side}</span>
                )}
                {layers.sig.ticker && <span className="ticker">{layers.sig.ticker}</span>}
                {layers.sig.contract && <span className="contract">{layers.sig.contract}</span>}
                {layers.sig.price != null && <span className="price">${layers.sig.price.toFixed(2)}</span>}
                {layers.sig.quantity != null && (
                  <span className="qty">× {layers.sig.quantity}{task.type === "option" ? " 张" : ""}</span>
                )}
                {layers.sig.showConfirmActions && (
                  <span className="confirm-pair">
                    <ConfirmActions taskId={task.id} variant="compact" />
                  </span>
                )}
              </>
            )}
          </div>
        )}

        {/* Layer 3: ORD */}
        {layers.ord && (
          <div className="layer-ord">
            <span className={`state-dot ${layers.ord.dot}`} />
            <span className="state-text">{layers.ord.text}</span>
            {layers.ord.cum && <span className="cum">{layers.ord.cum}</span>}
            <span className="expander">▾</span>
          </div>
        )}
      </div>

      {/* Expanded detail */}
      {expanded && (
        <div className="signal-detail">
          <div className="detail-block">
            <div className="detail-label">MSG · 原始消息</div>
            <div className="detail-meta">
              domID {task.message.id} · posted {fmtBeijingFull(task.message.posted_at)}
              {task.message.url && (
                <> · <a href={task.message.url} target="_blank" rel="noopener noreferrer">url ↗</a></>
              )}
            </div>
          </div>
          {task.instruction && layers.sig && !layers.sig.error && (
            <div className="detail-block">
              <div className="detail-label">SIG · 解析指令</div>
              <div className="detail-meta">
                {layers.sig.ctx && <>ctx = {layers.sig.ctx}</>}
                {layers.sig.parseDeltaMs != null && (
                  <> · parse +{layers.sig.parseDeltaMs.toFixed(3)}ms</>
                )}
                {task.type === "option" && task.instruction.strike != null && (
                  <> · strike {task.instruction.strike}</>
                )}
                {task.type === "option" && task.instruction.expiry && (
                  <> · expiry {task.instruction.expiry}</>
                )}
              </div>
            </div>
          )}
          {(pushEvents.length > 0 || task.order_id) && (
            <div className="detail-block">
              <div className="detail-label">ORD · 推送链</div>
              <PushChain
                events={pushEvents}
                taskStatus={task.status}
                totalQty={task.instruction?.quantity}
                submitOrderId={task.order_id ?? null}
                submitEndIso={null}
              />
            </div>
          )}
        </div>
      )}
    </div>
  );
}
