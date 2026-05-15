/** Currency conversion helpers — every numeric display on the right rail
 *  is rendered in USD so the user can scan a mixed-region portfolio
 *  without mentally adjusting for currency. HK prices/costs come from
 *  Longbridge in HKD; we divide by a static USD/HKD rate.
 *
 *  HKD is pegged to USD at 7.75–7.85, so a fixed mid-peg rate is good to
 *  ~0.5% for any practical display. The full-fidelity solution would
 *  fetch a live forex quote — out of scope here. A股 (SH/SZ) would need
 *  CNY→USD too but is parked until the user asks.
 */

const HKD_PER_USD = 7.8;

/** Convert a price-like value to USD based on the symbol's market suffix.
 *  Returns the input unchanged for non-HK symbols (US / unknown markets
 *  pass through). ``null`` / ``undefined`` propagates as ``null`` so
 *  callers can safely chain through optional values. */
export function toUsd(
  symbol: string | null | undefined,
  value: number | null | undefined,
): number | null {
  if (value == null || !Number.isFinite(value)) return null;
  if (symbol && symbol.endsWith(".HK")) return value / HKD_PER_USD;
  return value;
}
