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

  // Parsed symbol takes priority. When absent (PARSE_ERROR or pre-parse states),
  // we show the original message preview in the same cell — never the domID.
  const parsedSymbol = !isParseError ? formatTitle(instruction) : null;
  const messagePreview = parsedSymbol ? null : truncate(message.content || "", 120);

  // Time: use posted_at
  const ts = fmtTime(message.posted_at);

  const elapsed =
    task.updated_at && message.posted_at
      ? fmtElapsed(elapsedMs(message.posted_at, task.updated_at))
      : "—";

  // Build details line — only used when we have a parsed instruction
  let detailContent: React.ReactNode = null;
  if (parsedSymbol && instruction) {
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
  } else if (!isParseError && task.reject_reason) {
    detailContent = task.reject_reason;
  }

  const side = instruction?.instruction_type;
  const sideClass = side?.toLowerCase().includes("sell") ? "side-sell" : "side-buy";
  const sideLabel = side?.toLowerCase().includes("sell") ? "SELL" : (side ? "BUY" : "");

  // Symbol cell:
  //   parsed → "TSLL.US" mono
  //   PARSE_ERROR → 黄色"未识别" + message preview (wrapped, smaller font)
  //   pre-parse / no symbol → message preview only (wrapped, smaller font)
  const symbolCell = parsedSymbol ? (
    <span className="card-symbol">{parsedSymbol}</span>
  ) : (
    <span className="card-symbol has-message">
      {isParseError && <span className="unidentified-tag">未识别</span>}
      {messagePreview && <span className="msg-preview-inline">{messagePreview}</span>}
    </span>
  );

  return (
    <div className="card compact" onClick={onExpand} role="button" tabIndex={0}
      onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") onExpand(); }}>
      <TypeBadge type={badgeType} />
      {symbolCell}
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
