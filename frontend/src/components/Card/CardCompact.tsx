import type { TaskSummary } from "../../api/domain-types";
import { TypeBadge } from "../common/TypeBadge";
import { StatusPill } from "../common/StatusPill";
import { formatTitle, fmtTime, fmtElapsed, elapsedMs } from "./cardHelpers";
import "./Card.css";

export interface CardCompactProps {
  task: TaskSummary;
  onExpand: () => void;
}

function truncate(text: string, maxLen: number): string {
  if (text.length <= maxLen) return text;
  return text.slice(0, maxLen) + "…";
}

export function CardCompact({ task, onExpand }: CardCompactProps) {
  const { type, status, instruction, message } = task;
  const badgeType = type === "option" ? "option" : "stock";
  const isParseError = status === "PARSE_ERROR";

  // Symbol: "未识别" in yellow for PARSE_ERROR, otherwise formatted title
  const symbolText = isParseError ? "未识别" : (formatTitle(instruction) || task.id);
  const symbolClass = isParseError ? "card-symbol unidentified" : "card-symbol";

  // Time: use posted_at
  const ts = fmtTime(message.posted_at);

  const elapsed =
    task.updated_at && message.posted_at
      ? fmtElapsed(elapsedMs(message.posted_at, task.updated_at))
      : "—";

  // Build details line
  let detailContent: React.ReactNode = null;
  if (isParseError) {
    // Show truncated original message content for PARSE_ERROR
    detailContent = (
      <span className="msg-preview">{truncate(message.content, 60)}</span>
    );
  } else if (instruction) {
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
      <span className={symbolClass}>{symbolText}</span>
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
