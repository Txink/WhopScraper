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
