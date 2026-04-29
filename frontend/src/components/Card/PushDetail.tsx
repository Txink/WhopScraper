import type { PushEvent } from "../../api/domain-types";
import { fmtBeijingHmsMs } from "./cardHelpers";

function nodeClass(state: string): string {
  switch (state) {
    case "NEW":
    case "FILLED":
      return "ok";
    case "PARTIAL":
      return "ok";
    case "SUBMITTED":
    case "MODIFIED":
      return "info";
    case "CANCELLED":
      return "cancel";
    case "REJECTED":
      return "err";
    default:
      return "info";
  }
}

function msDiff(a: string, b: string): number {
  return new Date(b).getTime() - new Date(a).getTime();
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
  /** Order id returned by broker after submit. Renders a "已提交" row before broker pushes. */
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
          <span className="row-state">已提交</span>
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
        if (evt.state === "PARTIAL" && evt.delta_qty != null) {
          detail = (
            <span className="row-detail">
              <span className="diff-pos">+{evt.delta_qty}</span>
              {evt.delta_price != null && (
                <> @ <span className="v">${evt.delta_price.toFixed(2)}</span></>
              )}
              {evt.cumulative_qty != null && (
                <> · <span className="k">cum</span>{" "}
                <span className="v">{evt.cumulative_qty}/{totalQty ?? "?"}</span></>
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
      {/* Suppress '等待成交' row when only the synthetic '已提交' row exists
          with no real broker pushes — it's redundant with 已提交 in that
          state. See PushChain for the full rationale. */}
      {isWaiting && events.length > 0 && (
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
