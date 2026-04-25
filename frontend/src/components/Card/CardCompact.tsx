import type { TaskSummary } from "../../api/domain-types";
import { TypeBadge } from "../common/TypeBadge";
import { StatusPill } from "../common/StatusPill";
import { formatTitle, fmtTime, fmtElapsed, elapsedMs } from "./cardHelpers";
import "./Card.css";

export interface CardCompactProps {
  task: TaskSummary;
  onExpand: () => void;
}

export function CardCompact({ task, onExpand }: CardCompactProps) {
  const { type, status, instruction, message } = task;
  const badgeType = type === "option" ? "option" : "stock";
  const title = formatTitle(instruction);
  const ts = fmtTime(message.received_at);

  const elapsed =
    task.updated_at && message.received_at
      ? fmtElapsed(elapsedMs(message.received_at, task.updated_at))
      : "—";

  // Build details line
  let detailContent: React.ReactNode = null;
  if (instruction) {
    const price = instruction.price != null ? `$${instruction.price.toFixed(2)}` : null;
    const qty = instruction.quantity != null ? String(instruction.quantity) : null;
    if (price && qty) {
      detailContent = (
        <>
          <span className="v">{price}</span>
          {" × "}
          <span className="v">{qty}</span>
        </>
      );
    } else if (task.reject_reason) {
      detailContent = task.reject_reason;
    }
  } else if (task.reject_reason) {
    detailContent = task.reject_reason;
  }

  const side = instruction?.instruction_type;
  const sideClass = side?.toLowerCase().includes("sell") ? "side-sell" : "side-buy";
  const sideLabel = side?.toLowerCase().includes("sell") ? "SELL" : (side ? "BUY" : "");

  return (
    <div className="card compact" onClick={onExpand} role="button" tabIndex={0}
      onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") onExpand(); }}>
      <TypeBadge type={badgeType} />
      <span className="card-symbol">{title}</span>
      {sideLabel ? (
        <span className={`card-side ${sideClass}`}>{sideLabel}</span>
      ) : (
        <span />
      )}
      <span className="details">{detailContent}</span>
      <span className="ts">{ts}</span>
      <span className="elapsed">{elapsed}</span>
      <StatusPill status={status} />
      <span className="caret">▸</span>
    </div>
  );
}
