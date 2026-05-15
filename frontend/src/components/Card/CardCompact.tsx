import type { TaskSummary } from "../../api/domain-types";
import { StatusPill } from "../common/StatusPill";
import { ConfirmActions } from "./ConfirmActions";
import { formatTitle, fmtTime, fmtElapsed, elapsedMs, displaySubmitPriceDollars } from "./cardHelpers";
import "./Card.css";

export interface CardCompactProps {
  task: TaskSummary;
  autoTrade: boolean;
  onExpand: () => void;
}

function truncate(text: string, maxLen: number): string {
  if (text.length <= maxLen) return text;
  return text.slice(0, maxLen) + "…";
}

export function CardCompact({ task, autoTrade, onExpand }: CardCompactProps) {
  const { type, status, instruction, message } = task;
  const isOption = type === "option";
  const isParseError = status === "PARSE_ERROR";
  const isSkipped = status === "SKIPPED";

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

  // Build details line — only used when we have a parsed instruction.
  // Show price-only / qty-only / both, whichever the parser produced.
  //
  // Price/qty source priority (so the collapsed card matches what really
  // happened, not just the original signal):
  //   1. Cumulative fill (last_cum_qty > 0) → real fill avg × cum qty.
  //      Covers FILLED and PartialWithdrawal-style cancels with fills.
  //   2. Latest broker-side state (last_submitted_*) → catches post-modify
  //      values for CANCELLED/REJECTED orders that were edited before exit.
  //   3. Trader-submitted price + parsed qty → existing pre-push display.
  let detailContent: React.ReactNode = null;
  if (isSkipped && task.reject_reason) {
    detailContent = task.reject_reason;
  } else if (parsedSymbol && instruction) {
    const hasFills =
      task.last_cum_qty != null && task.last_cum_qty > 0
      && task.last_cum_avg_price != null && Number.isFinite(task.last_cum_avg_price);
    const hasLastSubmit =
      task.last_submitted_price != null && Number.isFinite(task.last_submitted_price);

    let priceVal: number | null;
    let qtyVal: number | null;
    if (hasFills) {
      priceVal = task.last_cum_avg_price!;
      qtyVal = task.last_cum_qty!;
    } else if (hasLastSubmit) {
      priceVal = task.last_submitted_price!;
      qtyVal = task.last_submitted_qty ?? instruction.quantity ?? null;
    } else {
      priceVal = displaySubmitPriceDollars(
        instruction,
        task.submit_order_type,
        task.submit_price,
        task.submit_quote_last_done,
      );
      qtyVal = instruction.quantity ?? null;
    }

    const price = priceVal != null ? `$${priceVal.toFixed(3)}` : null;
    const qty = qtyVal != null ? String(qtyVal) : null;
    if (price || qty) {
      detailContent = (
        <>
          {price && <span className="v">{price}</span>}
          {price && qty && " × "}
          {qty && <span className="v">{qty}</span>}
        </>
      );
    } else if (task.reject_reason) {
      detailContent = task.reject_reason;
    }
  } else if (!isParseError && task.reject_reason) {
    detailContent = task.reject_reason;
  }

  const showConfirmActions =
    !autoTrade && status === "INSTRUCTION_READY" && instruction != null;

  const side = instruction?.instruction_type;
  const sideClass = side?.toLowerCase().includes("sell") ? "side-sell" : "side-buy";
  const sideLabel = side?.toLowerCase().includes("sell") ? "SELL" : (side ? "BUY" : "");

  // Raw message preview always shows (even when we have a parsed signal),
  // truncated to one line with ellipsis. Sits between the TypeBadge and
  // the parsed cluster; provides the original-text context every row.
  const rawMessageText = truncate(message.content || "", 200);

  // Symbol cell:
  //   parsed → "TSLL.US" mono, with inline "OPT" chip for option contracts
  //   PARSE_ERROR → 黄色"未识别" tag (the message text itself is in the
  //   raw-msg cell on the left, no need to repeat)
  //   pre-parse / no symbol → empty cell
  //
  // The leading STOCK/OPTION TypeBadge column was removed to give the
  // raw-message cell more horizontal room; aggregate STOCK/OPTION counts
  // surface in the panel header instead. For option rows we still need
  // a per-row marker (rare, but visually distinct from stock) — a small
  // "OPT" chip sits inline with the symbol.
  const symbolCell = parsedSymbol ? (
    <span className="card-symbol">
      {isOption && <span className="option-marker">OPT</span>}
      {parsedSymbol}
    </span>
  ) : (
    <span className="card-symbol has-message">
      {isParseError && <span className="unidentified-tag">未识别</span>}
    </span>
  );

  return (
    <div className="card compact" onClick={onExpand} role="button" tabIndex={0}
      onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") onExpand(); }}>
      <span className="raw-msg" title={message.content}>{rawMessageText}</span>
      {symbolCell}
      {sideLabel ? (
        <span className={`card-side ${sideClass}`}>{sideLabel}</span>
      ) : (
        <span />
      )}
      <span className="details">{detailContent}</span>
      <span className="ts">{ts}</span>
      <span className="elapsed">{elapsed}</span>
      {showConfirmActions
        ? <ConfirmActions taskId={task.id} variant="compact" />
        : <StatusPill status={status} />
      }
    </div>
  );
}
