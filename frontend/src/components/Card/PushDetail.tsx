import type { PushEvent } from "../../api/domain-types";
import { fmtBeijingHmsMs } from "./cardHelpers";

// PushState (broker-faithful labels) → row color class.
function nodeClass(state: string): string {
  switch (state) {
    case "New":
    case "Filled":
    case "PartialFilled":
      return "ok";
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
    case "Canceled":
    case "Expired":
    case "PartialWithdrawal":
      return "cancel";
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
// so we can highlight which dimension(s) changed. Mirrors PushChain.
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

export interface PushDetailProps {
  events: PushEvent[];
  taskStatus: string;
  totalQty?: number | null;
  /** Order id returned by broker after submit. Renders a "Push" row before broker pushes. */
  submitOrderId?: string | null;
  /** ISO instant of the submit-completion moment; drives the row's timestamp. */
  submitEndIso?: string | null;
}

export function PushDetail({ events, taskStatus, totalQty, submitOrderId, submitEndIso }: PushDetailProps) {
  const isWaiting = ["PENDING", "PARTIAL", "SUBMITTED", "NEW"].includes(taskStatus);
  const showSubmitRow = !!submitOrderId;

  return (
    <div className="push-detail-list">
      {showSubmitRow && (
        <div className="push-row info" key="__submit__">
          <span className="spacer" />
          <span className="row-state">Push</span>
          <span className="row-detail">
            <span className="k">ord</span>{" "}
            <span className="v">{submitOrderId}</span>
          </span>
          <span className="row-ts">{submitEndIso ? fmtBeijingHmsMs(submitEndIso) : "?"}</span>
        </div>
      )}
      {events.map((evt, idx) => {
        const cls = nodeClass(evt.state);
        const ts = fmtBeijingHmsMs(evt.received_at);
        const prevTs =
          idx > 0
            ? events[idx - 1].received_at
            : showSubmitRow && submitEndIso
              ? submitEndIso
              : null;
        const deltaMs = prevTs != null ? msDiff(prevTs, evt.received_at) : null;

        let detail: React.ReactNode = null;
        if (evt.state === "PartialFilled" && evt.delta_qty != null) {
          // Denominator: prefer the push event's own submitted_quantity (the
          // order quantity at the moment of this fill — survives mid-order
          // qty modifications); fall back to instruction's totalQty.
          const denom = evt.submitted_quantity ?? totalQty ?? "?";
          detail = (
            <span className="row-detail">
              <span className="diff-pos">+{evt.delta_qty}</span>
              {evt.delta_price != null && (
                <> @ <span className="v">${evt.delta_price.toFixed(2)}</span></>
              )}
              {evt.cumulative_qty != null && (
                <> · <span className="k">cum</span>{" "}
                <span className="v">{evt.cumulative_qty}/{denom}</span></>
              )}
            </span>
          );
        } else if (evt.state === "Filled") {
          // Final fill: show actual cumulative price/qty so the row reflects
          // what really executed (not the original limit).
          detail = (
            <span className="row-detail">
              {evt.cumulative_qty != null && (
                <>
                  <span className="k">qty</span>{" "}
                  <span className="v">{evt.cumulative_qty}/{totalQty ?? "?"}</span>
                </>
              )}
              {evt.cumulative_avg_price != null && (
                <> · <span className="k">avg</span>{" "}
                <span className="v">${evt.cumulative_avg_price.toFixed(3)}</span></>
              )}
            </span>
          );
        } else if (evt.state === "Replaced") {
          // Modification: show whichever dimension changed against the
          // prior live event — price, qty, or both.
          const prior = priorLiveBefore(events, idx);
          const priceChanged =
            evt.submitted_price != null
            && prior?.submitted_price != null
            && prior.submitted_price !== evt.submitted_price;
          const qtyChanged =
            evt.submitted_quantity != null
            && prior?.submitted_quantity != null
            && prior.submitted_quantity !== evt.submitted_quantity;
          detail = (
            <span className="row-detail">
              {priceChanged && (
                <>
                  <span className="k">price</span>{" "}
                  <span className="v">
                    ${prior!.submitted_price!.toFixed(3)} → ${evt.submitted_price!.toFixed(3)}
                  </span>
                </>
              )}
              {priceChanged && qtyChanged && " · "}
              {qtyChanged && (
                <>
                  <span className="k">qty</span>{" "}
                  <span className="v">
                    {prior!.submitted_quantity} → {evt.submitted_quantity}
                  </span>
                </>
              )}
            </span>
          );
        } else if (evt.note) {
          detail = (
            <span className="row-detail">
              <span className="note">{evt.note}</span>
            </span>
          );
        } else {
          detail = <span className="row-detail" />;
        }

        return (
          <div key={evt.id} className={`push-row ${cls}`}>
            <span className="spacer" />
            <span className="row-state">{evt.state}</span>
            {detail}
            <span className="row-ts">
              {ts}
              {deltaMs != null && (
                <span className="row-delta"> {formatDelta(deltaMs)}</span>
              )}
            </span>
          </div>
        );
      })}
      {isWaiting && (events.length > 0 || showSubmitRow) && (
        <div className="push-row waiting">
          <span className="spacer" />
          <span className="row-state">等待成交</span>
          <span className="row-detail">
            <span className="note">等待更多成交推送</span>
          </span>
          <span className="row-ts">—</span>
        </div>
      )}
    </div>
  );
}
