import type { PushEvent } from "../../api/domain-types";
import { fmtBeijingHmsMs } from "./cardHelpers";

// PushState → node color class
function nodeClass(state: string): string {
  switch (state) {
    case "NEW":
    case "FILLED":
      return "ok";
    case "SUBMITTED":
    case "MODIFIED":
      return "info";
    case "PARTIAL":
      return "ok";
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
        <span key="__submit__">
          <span className="node info" data-ts={submitEndIso ? fmtBeijingHmsMs(submitEndIso) : ""}>
            <span className="dot" />
            <span className="name">已提交</span>
          </span>
        </span>
      )}
      {events.map((evt, idx) => {
        const cls = nodeClass(evt.state);
        const ts = fmtBeijingHmsMs(evt.received_at);
        // Build delta vs previous (synthetic submit node counts as "previous" for idx=0).
        const prevTs =
          idx > 0
            ? events[idx - 1].received_at
            : showSubmitNode && submitEndIso
              ? submitEndIso
              : null;
        const deltaMs = prevTs != null ? msDiff(prevTs, evt.received_at) : null;

        // Build inline content
        let inlineContent: React.ReactNode = null;
        if (evt.state === "PARTIAL" && evt.delta_qty != null) {
          inlineContent = (
            <span className="inline">
              <span className="diff-pos">+{evt.delta_qty}</span>
              {evt.delta_price != null && (
                <> @ <span className="v">${evt.delta_price.toFixed(2)}</span></>
              )}
              {evt.cumulative_qty != null && (
                <> <span className="k">cum</span>{" "}
                <span className="v">{evt.cumulative_qty}/{totalQty ?? "?"}</span></>
              )}
            </span>
          );
        }

        return (
          <span key={evt.id}>
            {deltaMs != null && (
              <span className={`delta${deltaMs > 1000 ? " slow" : ""}`}>
                {formatDelta(deltaMs)}
              </span>
            )}
            <span
              className={`node ${cls}`}
              data-ts={ts}
            >
              <span className="dot" />
              <span className="name">{evt.state}</span>
              {inlineContent}
            </span>
          </span>
        );
      })}
      {isWaiting && (
        <>
          {events.length > 0 && (() => {
            const lastEvt = events[events.length - 1];
            const waitMs = Date.now() - new Date(lastEvt.received_at).getTime();
            return (
              <span className={`delta${waitMs > 1000 ? " slow" : ""}`}>
                {formatDelta(waitMs)}…
              </span>
            );
          })()}
          <span className="node waiting">
            <span className="dot" />
            <span className="name">等待成交</span>
          </span>
        </>
      )}
    </div>
  );
}
