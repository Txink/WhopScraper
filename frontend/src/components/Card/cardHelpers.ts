import type { Instruction } from "../../api/domain-types";

/**
 * Format option title for display.
 * e.g. NVDA260424C135000.US → "NVDA 135 CALL · 20260424"
 */
export function formatOptionTitle(inst: Instruction): string {
  if (inst.type !== "option") return inst.symbol ?? inst.ticker ?? "?";
  const exp = inst.expiry ? inst.expiry.replace(/-/g, "") : "????????";
  return `${inst.ticker} ${inst.strike} ${inst.option_type} · ${exp}`;
}

/**
 * Format stock symbol for display (e.g. "TSLL.US")
 */
export function formatStockTitle(inst: Instruction): string {
  return inst.symbol ?? (inst.ticker ? `${inst.ticker}.US` : "?");
}

/**
 * Get display title for an instruction (stock or option).
 */
export function formatTitle(inst: Instruction | null): string {
  if (!inst) return "[未识别]";
  if (inst.type === "option") return formatOptionTitle(inst);
  return formatStockTitle(inst);
}

/**
 * Format a real-UTC ISO timestamp as Beijing HH:MM:SS.
 *
 * Backend stores all timestamps as real UTC (e.g. "2026-04-25T06:30:00Z").
 * We render in Asia/Shanghai because the project is operated from Beijing
 * and the user reads Whop wall-clock in that zone — pinning the formatter
 * keeps the display consistent regardless of the browser's local timezone.
 */
const _BJ_HMS = new Intl.DateTimeFormat("en-GB", {
  timeZone: "Asia/Shanghai",
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
  hour12: false,
});

export function fmtTime(iso: string): string {
  const d = new Date(iso);
  // en-GB with hour12=false yields "HH:mm:ss"; some Node/JSC builds emit
  // "24:00:00" for midnight — normalize to "00:00:00".
  return _BJ_HMS.format(d).replace(/^24:/, "00:");
}

/**
 * Beijing wall time HH:MM:SS.mmm from a real-UTC ISO instant.
 * Milliseconds come from getUTCMilliseconds (timezone-independent).
 */
export function fmtBeijingHmsMs(iso: string): string {
  const d = new Date(iso);
  const hms = _BJ_HMS.format(d).replace(/^24:/, "00:");
  const ms = String(d.getUTCMilliseconds()).padStart(3, "0");
  return `${hms}.${ms}`;
}

/**
 * Beijing wall time HH:MM:SS.mmm from a real-UTC ISO instant + offset milliseconds.
 * Used for stage footers (approximate completion from received_at + stage timings).
 */
export function fmtBeijingTimeWithMsFromOffset(baseIso: string, offsetMs: number): string {
  const t = new Date(baseIso).getTime() + offsetMs;
  return fmtBeijingHmsMs(new Date(t).toISOString());
}

/**
 * Format elapsed milliseconds as a compact string.
 */
export function fmtElapsed(ms: number): string {
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(2)}s`;
}

/**
 * Compute elapsed ms between two ISO timestamps.
 */
export function elapsedMs(from: string, to: string): number {
  return new Date(to).getTime() - new Date(from).getTime();
}

/**
 * Dollar price shown for compact card / totals.
 *
 * Priority:
 * 1. MARKET → ``submit_quote_last_done`` (the broker reference quote)
 * 2. ``submit_price`` (actual LIMIT price the trader submitted; may differ
 *    from the parsed signal price when the live quote was more favorable)
 * 3. ``instruction.price`` fallback (older tasks predating ``submit_price``)
 */
export function displaySubmitPriceDollars(
  instruction: Instruction,
  submitOrderType?: string | null,
  submitPrice?: number | null,
  submitQuoteLastDone?: number | null,
): number | null {
  const isMarket = submitOrderType === "MARKET";
  if (isMarket && submitQuoteLastDone != null && Number.isFinite(submitQuoteLastDone)) {
    return submitQuoteLastDone;
  }
  if (submitPrice != null && Number.isFinite(submitPrice)) {
    return submitPrice;
  }
  if (instruction.price != null) {
    return instruction.price;
  }
  return null;
}

const _BJ_FULL = new Intl.DateTimeFormat("en-CA", {
  timeZone: "Asia/Shanghai",
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
  hour12: false,
});

/**
 * Format a real-UTC ISO timestamp as Beijing "YYYY-MM-DD HH:MM:SS".
 * Use for display contexts where the full date+time is shown verbatim.
 */
export function fmtBeijingFull(iso: string): string {
  const d = new Date(iso);
  // en-CA gives "YYYY-MM-DD, HH:mm:ss"; normalize separator to a space.
  return _BJ_FULL.format(d).replace(", ", " ").replace(/^24:/, "00:");
}

const _BJ_DATE = new Intl.DateTimeFormat("en-CA", {
  timeZone: "Asia/Shanghai",
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
});

/**
 * Format a real-UTC ISO timestamp as Beijing "YYYY-MM-DD".
 * Use for date-only grouping and labels — "today" / "yesterday" comparisons
 * must use this so they reflect the user's Beijing calendar day, not UTC.
 */
export function fmtBeijingDate(iso: string): string {
  return _BJ_DATE.format(new Date(iso));
}

/**
 * Resolve a broker-canonical symbol's market segment.
 *   "TSLA.US"   → "US"
 *   "0700.HK"   → "HK"
 *   "600519.SH" → "CN"
 *   "000001.SZ" → "CN"
 *   unknown     → "US" (default — US is the most common; misroute is
 *                 harmless for the session-window resolver since HK/CN
 *                 share a window shape distinct from US's).
 */
export function marketOf(symbol: string): "US" | "HK" | "CN" {
  const m = symbol.match(/\.([A-Z]+)$/);
  if (!m) return "US";
  const code = m[1];
  if (code === "HK") return "HK";
  if (code === "SH" || code === "SZ") return "CN";
  return "US";
}
