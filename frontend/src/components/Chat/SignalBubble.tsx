import type { TaskSummary, PushEvent } from "../../api/domain-types";
import { layersForTask } from "./signalCardHelpers";
import { ConfirmActions } from "../Card/ConfirmActions";
import { LabelActions } from "../Card/LabelActions";
import { PushChain } from "../Card/PushChain";
import { fmtBeijingFull, submitEndIso } from "../Card/cardHelpers";
import { useLazyPushEvents } from "../../hooks/useLazyPushEvents";
import { authedAssetUrl } from "../../api/http";
import "./SignalCard.css";

export interface SignalBubbleProps {
  task: TaskSummary;
  pushEvents: PushEvent[];
  expanded: boolean;
  onToggle(): void;
  autoTrade: boolean;
  /** Must match task.type. StockCard always passes "stock"; OptionCard always
   *  passes "option". Drives sourceClass, qty unit suffix (" 张"), and the
   *  option-only strike/expiry detail rows. */
  variant: "stock" | "option";
}

export function SignalBubble({
  task, pushEvents, expanded, onToggle, autoTrade, variant,
}: SignalBubbleProps): JSX.Element {
  const layers = layersForTask(task, { autoTrade });
  const isImage = layers.kind === "image";
  const sourceClass = layers.kind === "parse_error" ? "neutral" : variant;
  const submitEnd = submitEndIso(
    task.message.received_at ?? task.message.posted_at,
    task.stage_timings?.parse ?? null,
    task.stage_timings?.submit ?? null,
  );
  // Rehydrate the persisted push chain when expanded — after a page reload the
  // store has no live WS events and the list endpoint omits push_events, so the
  // chain would otherwise show only the synthetic "已提交" node.
  useLazyPushEvents(task.id, task.status, pushEvents.length, expanded);

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
      {isImage ? (
        <div className="signal-summary">
          {layers.imageUrl && (
            <img
              className="signal-bubble-image"
              src={authedAssetUrl(layers.imageUrl)}
              alt=""
            />
          )}
          {layers.msg && (
            <div className="layer-msg" title={layers.msg}>{layers.msg}</div>
          )}
        </div>
      ) : (
        <>
          <div className="signal-summary">
            <div className="layer-msg" title={layers.msg}>{layers.msg}</div>

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
                      <span className="qty">× {layers.sig.quantity}{variant === "option" ? " 张" : ""}</span>
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

            {layers.ord && (
              <div className="layer-ord">
                <span className={`state-dot ${layers.ord.dot}`} />
                <span className="state-text">{layers.ord.text}</span>
                {layers.ord.cum && <span className="cum">{layers.ord.cum}</span>}
                <span className="expander">▾</span>
              </div>
            )}
          </div>

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
                    {variant === "option" && task.instruction.strike != null && (
                      <> · strike {task.instruction.strike}</>
                    )}
                    {variant === "option" && task.instruction.expiry && (
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
                    submitEndIso={submitEnd}
                  />
                </div>
              )}
              <LabelActions
                taskId={task.id}
                instruction={task.instruction}
                variant={variant}
              />
            </div>
          )}
        </>
      )}
    </div>
  );
}
