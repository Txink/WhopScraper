import type { PushEvent } from "../../api/domain-types";
import { fmtBeijingHmsMs } from "./cardHelpers";

// PushState (broker-faithful labels) → node color class.
// "info" = pre-exchange / pending modify; "ok" = live / filled;
// "cancel" = cancelled / expired; "err" = rejected / unknown.
function nodeClass(state: string): string {
  switch (state) {
    // Live on exchange / fills
    case "New":
    case "Filled":
    case "PartialFilled":
      return "ok";
    // Pre-exchange / replace pending / cancel pending
    case "WaitToNew":
    case "NotReported":
    case "WaitToReplace":
    case "PendingReplace":
    case "ReplacedNotReported":
    case "ProtectedNotReported":
    case "VarietiesNotReported":
    case "Replaced":
    case "PendingCancel":
    case "WaitToCancel":
      return "info";
    // Cancelled (terminal)
    case "Canceled":
    case "Expired":
    case "PartialWithdrawal":
      return "cancel";
    // Errors
    case "Rejected":
    case "Unknown":
    case "FAILED":
      return "err";
    default:
      return "info";
  }
}

function msDiff(a: string, b: string): number {
  return new Date(b).getTime() - new Date(a).getTime();
}

// For a Replaced event at ``idx``, find the prior live event (New/Replaced)
// so we can highlight which dimension(s) changed (price, qty, or both).
// Returns ``null`` if no prior live event exists (shouldn't happen — the
// backend only labels Replaced when a prior live event was present).
function priorLiveBefore(events: PushEvent[], idx: number): PushEvent | null {
  for (let i = idx - 1; i >= 0; i--) {
    const s = events[i].state;
    if (s === "New" || s === "Replaced") return events[i];
  }
  return null;
}

function formatDelta(ms: number): string {
  if (ms >= 60000) {
    const m = Math.floor(ms / 60000);
    const s = Math.round((ms % 60000) / 1000);
    return s > 0 ? `+${m}m${s}s` : `+${m}m`;
  }
  return `+${ms}ms`;
}

// Sub-label rendered under each node in the collapsed chain. Surfaces the
// most-relevant context per state — e.g. ``$7.32 ×1`` under ``New``,
// ``$7.31 → $7.32`` under ``Replaced``, ``×1 @$7.32`` under ``Filled``.
// Uses semantic spans (.v / .k / .arrow / .x / .pos) so CSS can highlight
// values, dim keys/connectors, and accent change indicators.
// Returns ``null`` when there's nothing useful to show (keeps the row tight).
function renderSubLabel(
  evt: PushEvent,
  events: PushEvent[],
  idx: number,
  totalQty: number | null | undefined,
): React.ReactNode {
  // Pre-exchange + initial live: show the standing limit ($price ×qty).
  if (
    evt.state === "WaitToNew"
    || evt.state === "New"
    || evt.state === "NotReported"
    || evt.state === "WaitToReplace"
    || evt.state === "PendingReplace"
    || evt.state === "ReplacedNotReported"
    || evt.state === "ProtectedNotReported"
    || evt.state === "VarietiesNotReported"
  ) {
    if (evt.submitted_price == null && evt.submitted_quantity == null) return null;
    return (
      <>
        {evt.submitted_price != null && (
          <span className="v">${evt.submitted_price.toFixed(2)}</span>
        )}
        {evt.submitted_price != null && evt.submitted_quantity != null && " "}
        {evt.submitted_quantity != null && (
          <>
            <span className="x">×</span>
            <span className="v">{evt.submitted_quantity}</span>
          </>
        )}
      </>
    );
  }

  // Modify: show the dimension(s) that changed against the prior live event.
  if (evt.state === "Replaced") {
    const prior = priorLiveBefore(events, idx);
    const priceChanged =
      evt.submitted_price != null
      && prior?.submitted_price != null
      && prior.submitted_price !== evt.submitted_price;
    const qtyChanged =
      evt.submitted_quantity != null
      && prior?.submitted_quantity != null
      && prior.submitted_quantity !== evt.submitted_quantity;
    if (!priceChanged && !qtyChanged) return null;
    return (
      <>
        {priceChanged && (
          <>
            <span className="v">${prior!.submitted_price!.toFixed(2)}</span>
            <span className="arrow">→</span>
            <span className="v">${evt.submitted_price!.toFixed(2)}</span>
          </>
        )}
        {priceChanged && qtyChanged && <span className="k">{" · "}</span>}
        {qtyChanged && (
          <>
            <span className="v">{prior!.submitted_quantity}</span>
            <span className="arrow">→</span>
            <span className="v">{evt.submitted_quantity}</span>
          </>
        )}
      </>
    );
  }

  // Partial fill: show this batch + cumulative. Denominator priority:
  // the push event's own ``submitted_quantity`` (the order quantity at the
  // moment this fill happened — accurate even after a mid-order qty modify)
  // → instruction-derived ``totalQty`` → "?". This avoids the stale "4/?"
  // case where instruction.quantity was never set.
  if (evt.state === "PartialFilled" && evt.delta_qty != null) {
    const denom = evt.submitted_quantity ?? totalQty ?? "?";
    return (
      <>
        <span className="pos">+{evt.delta_qty}</span>
        {evt.cumulative_qty != null && (
          <>
            <span className="k">{" · "}</span>
            <span className="v">{evt.cumulative_qty}/{denom}</span>
          </>
        )}
      </>
    );
  }

  // Final fill: show executed avg price + qty (same shape as live/Replaced
  // labels — ``$<price> ×<qty>`` — for visual consistency across the chain).
  if (evt.state === "Filled" && evt.cumulative_qty != null) {
    return (
      <>
        {evt.cumulative_avg_price != null && (
          <span className="v">${evt.cumulative_avg_price.toFixed(2)}</span>
        )}
        {evt.cumulative_avg_price != null && " "}
        <span className="x">×</span>
        <span className="v">{evt.cumulative_qty}</span>
      </>
    );
  }

  // Cancelled / expired: show what got cancelled (last live state).
  if (evt.state === "Canceled" || evt.state === "Expired" || evt.state === "PartialWithdrawal") {
    const prior = priorLiveBefore(events, idx);
    if (prior == null || (prior.submitted_price == null && prior.submitted_quantity == null)) {
      return null;
    }
    return (
      <>
        {prior.submitted_price != null && (
          <span className="v">${prior.submitted_price.toFixed(2)}</span>
        )}
        {prior.submitted_price != null && prior.submitted_quantity != null && " "}
        {prior.submitted_quantity != null && (
          <>
            <span className="x">×</span>
            <span className="v">{prior.submitted_quantity}</span>
          </>
        )}
      </>
    );
  }

  // Rejected / Unknown: surface broker note when present.
  if ((evt.state === "Rejected" || evt.state === "Unknown" || evt.state === "FAILED") && evt.note) {
    return <span className="v">{evt.note}</span>;
  }

  return null;
}

export interface PushChainProps {
  events: PushEvent[];
  taskStatus: string;
  totalQty?: number | null;
  /** Order id returned by the broker after submit; renders a "已提交" node before the broker push events. */
  submitOrderId?: string | null;
  /** ISO instant of the submit-completion moment (received_at + parseMs + submitMs); drives the synthetic node's timestamp. */
  submitEndIso?: string | null;
}

export function PushChain({ events, taskStatus, totalQty, submitOrderId, submitEndIso }: PushChainProps) {
  const isWaiting = ["PENDING", "PARTIAL", "SUBMITTED", "NEW"].includes(taskStatus);
  const showSubmitNode = !!submitOrderId;

  return (
    <div className="push-chain">
      {showSubmitNode && (
        <span key="__submit__" className="chain-item">
          <span className="node-stack">
            <span className="node info" data-ts={submitEndIso ? fmtBeijingHmsMs(submitEndIso) : "?"}>
              <span className="dot" />
              <span className="name">已提交</span>
            </span>
            <span className="node-label" />
          </span>
        </span>
      )}
      {events.map((evt, idx) => {
        const cls = nodeClass(evt.state);
        const ts = fmtBeijingHmsMs(evt.received_at);
        // A "previous" node exists if this isn't the first event OR if the
        // synthetic submit node is rendered before us. The connector should
        // always render when there is a prev — fall back to "?" if the
        // timestamp arithmetic isn't possible (synthetic node missing iso).
        const hasPrev = idx > 0 || showSubmitNode;
        const prevIso =
          idx > 0
            ? events[idx - 1].received_at
            : showSubmitNode
              ? (submitEndIso ?? null)
              : null;
        const deltaMs = prevIso != null ? msDiff(prevIso, evt.received_at) : null;
        const subLabel = renderSubLabel(evt, events, idx, totalQty);

        return (
          <span key={evt.id} className="chain-item">
            {hasPrev && (
              <span className={`delta${deltaMs != null && deltaMs > 1000 ? " slow" : ""}`}>
                {deltaMs != null ? formatDelta(deltaMs) : "?"}
              </span>
            )}
            <span className="node-stack">
              <span className={`node ${cls}`} data-ts={ts}>
                <span className="dot" />
                <span className="name">{evt.state}</span>
              </span>
              <span className="node-label">{subLabel}</span>
            </span>
          </span>
        );
      })}
      {isWaiting && (events.length > 0 || showSubmitNode) && (() => {
        // Wait time is meaningful only when measured against a real broker
        // event (the latest push). When the only "previous" anchor is the
        // synthetic '已提交' node, Date.now() − submit isn't a real wait
        // for a fill — show "?" instead so the user isn't misled.
        let waitMs: number | null = null;
        if (events.length > 0) {
          waitMs = Date.now() - new Date(events[events.length - 1].received_at).getTime();
        }
        return (
          <span key="__waiting__" className="chain-item">
            <span className={`delta${waitMs != null && waitMs > 1000 ? " slow" : ""}`}>
              {waitMs != null ? `${formatDelta(waitMs)}…` : "?"}
            </span>
            <span className="node-stack">
              <span className="node waiting">
                <span className="dot" />
                <span className="name">等待成交</span>
              </span>
              <span className="node-label" />
            </span>
          </span>
        );
      })()}
    </div>
  );
}
