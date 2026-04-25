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
 * Format HH:MM:SS from ISO date string.
 *
 * Uses UTC methods because backend stores Whop's wall-clock time as
 * a UTC ISO string (e.g. "Yesterday 11:24 PM" → "2026-04-24T23:24:00Z").
 * Local timezone conversion would shift the displayed hour by tz offset
 * and no longer match what the user sees in Whop. CardExpanded does the
 * same — it strips T/Z without conversion.
 */
export function fmtTime(iso: string): string {
  const d = new Date(iso);
  const hh = String(d.getUTCHours()).padStart(2, "0");
  const mm = String(d.getUTCMinutes()).padStart(2, "0");
  const ss = String(d.getUTCSeconds()).padStart(2, "0");
  return `${hh}:${mm}:${ss}`;
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
