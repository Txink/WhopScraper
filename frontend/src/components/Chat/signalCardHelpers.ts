import type { TaskSummary, Instruction } from "../../api/domain-types";

export type DotColor = "ok" | "warn" | "err" | "muted";
export type LayerKind = "normal" | "parse_error" | "neutral" | "image";

export interface SigLayer {
  side: "BUY" | "SELL" | null;
  ticker: string | null;
  contract: string | null;         // option-only: "880C MM/DD"
  price: number | null;
  quantity: number | null;
  showConfirmActions: boolean;     // auto_trade off + INSTRUCTION_READY
  error: string | null;            // PARSE_ERROR text
  ctx: string | null;
  parseDeltaMs: number | null;
}

export interface OrdLayer {
  dot: DotColor;
  text: string;                    // 已成交 / 部分成交 / 提交失败 …
  cum: string | null;              // "100/100 @ $199.87"
  statusPill: string | null;       // optional pill, e.g. "PARSE_ERROR"
}

export interface CardLayers {
  kind: LayerKind;
  /** raw whop text. Always present; folded view 1-line clips it, expanded wraps. */
  msg: string;
  sig: SigLayer | null;
  ord: OrdLayer | null;
  imageUrl: string | null;
}

function formatExpiryMMDD(iso: string): string {
  // "2026-12-15" → "12/15". Permissive against missing pieces.
  const [, mm = "", dd = ""] = iso.split("-");
  return `${mm}/${dd}`;
}

function formatContract(inst: Instruction): string | null {
  if (inst.strike == null || !inst.expiry) return null;
  const sideLetter = (inst.option_type ?? "").toUpperCase().startsWith("P") ? "P" : "C";
  return `${inst.strike}${sideLetter} ${formatExpiryMMDD(inst.expiry)}`;
}

function formatCum(task: TaskSummary): string | null {
  const cumQty = task.last_cum_qty;
  const avg = task.last_cum_avg_price;
  if (cumQty == null || avg == null) return null;
  const total = task.instruction?.quantity;
  const totalStr = total != null ? String(total) : "—";
  return `${cumQty}/${totalStr} @ $${avg.toFixed(2)}`;
}

export function layersForTask(
  task: TaskSummary,
  opts?: { autoTrade?: boolean },
): CardLayers {
  const autoTrade = opts?.autoTrade ?? true;
  const msg = task.message.content ?? "";
  const inst = task.instruction;

  if (task.message.image_url) {
    return { kind: "image", msg, sig: null, ord: null, imageUrl: task.message.image_url };
  }

  if (task.status === "PARSE_ERROR") {
    return {
      kind: "parse_error",
      msg,
      sig: {
        side: null, ticker: null, contract: null, price: null, quantity: null,
        showConfirmActions: false,
        error: "未解析 · 正则未匹配",
        ctx: null, parseDeltaMs: null,
      },
      ord: null,
      imageUrl: null,
    };
  }

  const sig: SigLayer | null = inst
    ? {
        side: (inst.instruction_type as "BUY" | "SELL") ?? null,
        ticker: inst.symbol ?? inst.ticker ?? null,
        contract: task.type === "option" ? formatContract(inst) : null,
        price: inst.price ?? null,
        quantity: inst.quantity ?? null,
        showConfirmActions:
          !autoTrade && task.status === "INSTRUCTION_READY",
        error: null,
        ctx: inst.context_source ?? null,
        parseDeltaMs: task.stage_timings?.["parse"] ?? null,
      }
    : null;

  let ord: OrdLayer | null = null;
  switch (task.status) {
    case "INSTRUCTION_READY":
      ord = {
        dot: "warn",
        text: "等待人工确认",
        cum: "auto_trade 已关闭",
        statusPill: null,
      };
      break;
    case "SUBMITTING":
    case "PENDING":
      ord = { dot: "warn", text: "等待成交", cum: null, statusPill: null };
      break;
    case "PARTIAL":
      ord = {
        dot: "warn",
        text: "部分成交",
        cum: formatCum(task),
        statusPill: null,
      };
      break;
    case "FILLED":
      ord = {
        dot: "ok",
        text: "已成交",
        cum: formatCum(task),
        statusPill: null,
      };
      break;
    case "CANCELLED":
    case "REJECTED":
      ord = {
        dot: "err",
        text: task.status,
        cum: task.reject_reason ?? null,
        statusPill: null,
      };
      break;
    case "SUBMIT_FAILED":
      ord = {
        dot: "err",
        text: `提交失败 · ${task.reject_reason ?? ""}`,
        cum: null,
        statusPill: null,
      };
      break;
    case "SKIPPED":
      ord = {
        dot: "warn",
        text: task.reject_reason ?? "已跳过",
        cum: null,
        statusPill: null,
      };
      break;
    default:
      ord = null;
  }

  return { kind: "normal", msg, sig, ord, imageUrl: null };
}
