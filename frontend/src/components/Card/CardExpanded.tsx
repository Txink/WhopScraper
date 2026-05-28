import { useState } from "react";
import type { TaskSummary, PushEvent } from "../../api/domain-types";
import { useLazyPushEvents } from "../../hooks/useLazyPushEvents";
import { TypeBadge } from "../common/TypeBadge";
import { StatusPill } from "../common/StatusPill";
import { OrderSubmit } from "./OrderSubmit";
import { PushChain } from "./PushChain";
import { PushDetail } from "./PushDetail";
import { ConfirmActions } from "./ConfirmActions";
import {
  formatTitle,
  fmtElapsed,
  elapsedMs,
  fmtBeijingTimeWithMsFromOffset,
  fmtBeijingFull,
  submitEndOffsetMs,
  submitEndIso as computeSubmitEndIso,
} from "./cardHelpers";
import "./Card.css";

export interface CardExpandedProps {
  task: TaskSummary;
  pushEvents: PushEvent[];
  autoTrade: boolean;
  onCollapse: () => void;
}

// Statuses that imply broker-side activity has occurred — anything past
export function CardExpanded({ task, pushEvents, autoTrade, onCollapse }: CardExpandedProps) {
  const [pushExpanded, setPushExpanded] = useState(false);

  // Rehydrate the push chain from persisted detail when the store has none
  // (e.g. after a page reload) — the list endpoint omits push_events.
  useLazyPushEvents(task.id, task.status, pushEvents.length);

  const {
    type,
    status,
    instruction,
    message,
    order_id,
    stage_timings,
    reject_reason,
    submit_order_type,
    submit_order_context,
    submit_quote_last_done,
    submit_price,
  } = task;
  const badgeType = type === "option" ? "option" : "stock";
  const title = formatTitle(instruction);

  const side = instruction?.instruction_type;
  const sideClass = side?.toLowerCase().includes("sell") ? "side-sell" : "side-buy";
  const sideLabel = side?.toLowerCase().includes("sell") ? "SELL" : (side ? "BUY" : null);

  // Compute total elapsed (from when the message was posted, not received)
  const totalMs = task.updated_at && message.posted_at
    ? elapsedMs(message.posted_at, task.updated_at)
    : null;

  // Stage: 解析指令 — present if instruction exists
  const hasInstruction = instruction != null;
  const hasOrder = order_id != null;
  const hasSkipReason = status === "SKIPPED" && Boolean(reject_reason);
  const canManualConfirm = autoTrade === false && status === "INSTRUCTION_READY" && hasInstruction;

  // Stage marker class helper
  const isPastStage = (s: string) =>
    ["FILLED", "PARTIAL", "CANCELLED", "REJECTED", "SUBMIT_FAILED",
      "INSTRUCTION_READY", "SUBMITTING", "PENDING", "SUBMITTED",
      "NEW", "MODIFIED"].includes(s);

  const parseMarkerClass =
    status === "PARSE_ERROR" ? "err"
    : hasInstruction ? "done"
    : "active";

  // Push block summary. Source the cumulative fill values from the most
  // recent broker event that carries them — Filled (terminal) takes
  // precedence, then PartialFilled. Pre-fill events leave both as null.
  const totalQty = instruction?.quantity;
  const lastFillEvent = [...pushEvents]
    .reverse()
    .find((e) => e.state === "Filled" || e.state === "PartialFilled");
  const cumQty = lastFillEvent?.cumulative_qty;
  const cumAvg = lastFillEvent?.cumulative_avg_price;

  const parseMs = stage_timings?.parse ?? null;
  const submitMs = stage_timings?.submit ?? null;
  const anchorIso = message.received_at ?? message.posted_at;
  const parseEndClock =
    parseMs != null ? fmtBeijingTimeWithMsFromOffset(anchorIso, parseMs) : "—";
  const submitOffsetMs = submitEndOffsetMs(parseMs, submitMs);
  const submitEndClock =
    submitOffsetMs != null
      ? fmtBeijingTimeWithMsFromOffset(anchorIso, submitOffsetMs)
      : "—";
  const submitEndIso = computeSubmitEndIso(anchorIso, parseMs, submitMs);

  return (
    <article className="card expanded">
      {/* Header acts as the collapse hit-target: click anywhere on the row
          to toggle back to the compact form. role + tabIndex give keyboard
          users the same affordance. */}
      <div
        className="card-header"
        role="button"
        tabIndex={0}
        aria-label="收起"
        onClick={onCollapse}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            onCollapse();
          }
        }}
      >
        <TypeBadge type={badgeType} />
        <span className="card-symbol">{title}</span>
        {sideLabel && (
          <span className={`card-side ${sideClass}`}>{sideLabel}</span>
        )}
        <span className="header-spacer" />
        <StatusPill status={status} />
      </div>

      {/* Raw message */}
      <div className="raw">
        <span className="src">{message.source}</span>
        {message.content}
      </div>

      {/* Local stages */}
      <div className="stages">
        {/* Stage 1: 原始消息 */}
        <div className="stage done">
          <div className="stage-marker" />
          <div className="stage-body">
            <strong>原始消息</strong>
            <div className="msg-meta">
              <span className="k">ts</span>
              <span className="v">{fmtBeijingFull(message.posted_at)}</span>
              <span className="k">domID</span>
              <span className="v">{message.id}</span>
            </div>
          </div>
          <div className="stage-delta">—</div>
        </div>

        {/* Stage 2: 解析指令 */}
        {(hasInstruction || status === "PARSE_ERROR" || isPastStage(status)) && (
          <div className={`stage ${parseMarkerClass}`}>
            <div className="stage-marker" />
            <div className="stage-body">
              <div className="stage-title-line">
                <span>
                  <strong>解析指令</strong>
                  {parseMs != null && (
                    <span className={`stage-title-timing${parseMs > 500 ? " slow" : ""}`}>
                      [+{parseMs.toFixed(3)}ms]
                    </span>
                  )}
                </span>
              </div>
              {instruction && (
                <div className="parse-inline">
                  {(instruction.ticker || instruction.symbol) && (
                    <span className="parse-ticker">{instruction.ticker ?? instruction.symbol}</span>
                  )}
                  {instruction.price != null && (
                    <span className="parse-price">${instruction.price.toFixed(2)}</span>
                  )}
                  {instruction.quantity != null && (
                    <span className="parse-qty">× {instruction.quantity}</span>
                  )}
                  {instruction.strike != null && (
                    <span className="parse-extra">strike {instruction.strike}</span>
                  )}
                  {instruction.expiry && (
                    <span className="parse-extra">{instruction.expiry.replace(/-/g, "")}</span>
                  )}
                  {instruction.stop_loss_price != null && (
                    <span className="parse-extra">stop ${instruction.stop_loss_price.toFixed(2)}</span>
                  )}
                  {instruction.context_source && (
                    <span className="parse-ctx">ctx={instruction.context_source}</span>
                  )}
                </div>
              )}
              {status === "PARSE_ERROR" && reject_reason && (
                <div className="stage-meta" style={{ color: "var(--err)" }}>{reject_reason}</div>
              )}
              {hasSkipReason && (
                <div className="stage-meta stage-meta-warn">{reject_reason}</div>
              )}
              {canManualConfirm && (
                <div className="confirm-actions-row">
                  <ConfirmActions taskId={task.id} variant="expanded" />
                  <span className="confirm-hint">auto_trade 已关闭 · 待人工确认</span>
                </div>
              )}
            </div>
            <div className="stage-delta stage-delta-clock">{parseEndClock}</div>
          </div>
        )}

        {/* Stage 3: 提交订单 — shown for any task that reached the submit
            stage, including synchronous broker rejections (SUBMIT_FAILED)
            where no order_id was issued. The error message comes from
            task.reject_reason which trader._format_broker_error populated
            from the broker exception (e.g. "broker [603301] The symbol
            currently does not support short selling."). */}
        {instruction && (hasOrder || status === "SUBMIT_FAILED") && (
          <OrderSubmit
            instruction={instruction}
            orderId={order_id ?? null}
            delta={stage_timings?.submit ?? null}
            error={status === "SUBMIT_FAILED" ? reject_reason : null}
            submitOrderType={submit_order_type ?? null}
            submitOrderContext={submit_order_context ?? null}
            submitQuoteLastDone={submit_quote_last_done ?? null}
            submitPrice={submit_price ?? null}
            wallClockAtSubmitEnd={submitEndClock}
            filledQty={cumQty ?? null}
            filledAvgPrice={cumAvg ?? null}
            isFilled={status === "FILLED"}
          />
        )}
      </div>

      {/* Push block */}
      {(pushEvents.length > 0 || hasOrder) && (
        <div className={`push-block${pushExpanded ? " is-expanded" : ""}`}>
          <div className="push-block-head">
            <span className="push-label">
              订单推送
              <span className="count">broker · {pushEvents.length} 事件</span>
              <button
                className="push-toggle"
                onClick={() => setPushExpanded((v) => !v)}
              >
                {pushExpanded ? "收起 ▴" : "展开 ▾"}
              </button>
            </span>
            {(cumQty != null || cumAvg != null) && (
              <span className="push-aggregate">
                {cumQty != null && totalQty != null && (
                  <>
                    <span className="k">cum</span>
                    <span className="v">{cumQty}/{totalQty}</span>
                    {" · "}
                  </>
                )}
                {cumAvg != null && (
                  <>
                    <span className="k">avg</span>
                    <span className="v">${cumAvg.toFixed(3)}</span>
                  </>
                )}
              </span>
            )}
          </div>

          {pushExpanded ? (
            <PushDetail
              events={pushEvents}
              taskStatus={status}
              totalQty={totalQty}
              submitOrderId={order_id ?? null}
              submitEndIso={submitEndIso}
            />
          ) : (
            <PushChain
              events={pushEvents}
              taskStatus={status}
              totalQty={totalQty}
              submitOrderId={order_id ?? null}
              submitEndIso={submitEndIso}
            />
          )}
        </div>
      )}

      {/* Card foot */}
      <div className="card-foot">
        <span>源 · {type} · {message.source}</span>
        <span className="total">
          {totalMs != null ? `总耗时 ${fmtElapsed(totalMs)}` : ""}
          {" · 状态 "}{status}
        </span>
      </div>
    </article>
  );
}
