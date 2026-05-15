import type { TPair, Trade } from "../../api/domain-types";

/**
 * Pure helpers for做T pair calculations. The backend allocates qty FIFO at
 * create / extend time; these functions read the resulting `TPair` shape
 * and compute realized profit, partial-status, and remainder figures for
 * the UI.
 *
 * Every helper is total-pure (no I/O, no class state) so they can be tested
 * directly and shared across detail-pane subcomponents.
 */

const tradeIndex = (trades: Trade[]): Record<string, Trade> =>
  Object.fromEntries(trades.map((t) => [t.id, t]));

export function pairTotalBuyQty(pair: TPair): number {
  return pair.buys.reduce((s, b) => s + b.qty, 0);
}
export function pairTotalSellQty(pair: TPair): number {
  return pair.sells.reduce((s, b) => s + b.qty, 0);
}
export function pairBuyCost(pair: TPair, trades: Trade[]): number {
  const idx = tradeIndex(trades);
  return pair.buys.reduce((s, b) => s + b.qty * (idx[b.trade_id]?.price ?? 0), 0);
}
export function pairSellRevenue(pair: TPair, trades: Trade[]): number {
  const idx = tradeIndex(trades);
  return pair.sells.reduce((s, b) => s + b.qty * (idx[b.trade_id]?.price ?? 0), 0);
}
export function pairAvgBuyPrice(pair: TPair, trades: Trade[]): number {
  const q = pairTotalBuyQty(pair);
  return q > 0 ? pairBuyCost(pair, trades) / q : 0;
}
export function pairAvgSellPrice(pair: TPair, trades: Trade[]): number {
  const q = pairTotalSellQty(pair);
  return q > 0 ? pairSellRevenue(pair, trades) / q : 0;
}
export function pairMatchedQty(pair: TPair): number {
  return Math.min(pairTotalBuyQty(pair), pairTotalSellQty(pair));
}
export function pairIsPartial(pair: TPair): boolean {
  return pairTotalBuyQty(pair) !== pairTotalSellQty(pair);
}

/** Realized profit on the matched portion (= min(BUY, SELL) qty in pair). */
export function pairProfit(pair: TPair, trades: Trade[]): number {
  const m = pairMatchedQty(pair);
  if (m === 0) return 0;
  return m * (pairAvgSellPrice(pair, trades) - pairAvgBuyPrice(pair, trades));
}
export function pairProfitPct(pair: TPair, trades: Trade[]): number {
  const ab = pairAvgBuyPrice(pair, trades);
  if (ab === 0 || pairMatchedQty(pair) === 0) return 0;
  return ((pairAvgSellPrice(pair, trades) - ab) / ab) * 100;
}

export interface PairRemainder {
  side: "BUY" | "SELL";
  qty: number;
  need: "SELL" | "BUY";
}
export function pairRemainder(pair: TPair): PairRemainder | null {
  const b = pairTotalBuyQty(pair);
  const s = pairTotalSellQty(pair);
  if (b > s) return { side: "BUY", qty: b - s, need: "SELL" };
  if (s > b) return { side: "SELL", qty: s - b, need: "BUY" };
  return null;
}

/** Sum allocated qty for a trade across all pairs for its ticker. */
export function tradeAllocatedQty(tradeId: string, pairs: TPair[]): number {
  let q = 0;
  for (const p of pairs) {
    for (const b of p.buys) if (b.trade_id === tradeId) q += b.qty;
    for (const s of p.sells) if (s.trade_id === tradeId) q += s.qty;
  }
  return q;
}
export function tradeAvailableQty(trade: Trade, pairs: TPair[]): number {
  return Math.max(0, trade.qty - tradeAllocatedQty(trade.id, pairs));
}
export interface TradePairAlloc {
  pair: TPair;
  qty: number;
}
/** Return every (pair, qty) tuple this trade has allocations into. */
export function tradePairsForTrade(tradeId: string, pairs: TPair[]): TradePairAlloc[] {
  const out: TradePairAlloc[] = [];
  for (const p of pairs) {
    let qty = 0;
    for (const b of p.buys) if (b.trade_id === tradeId) qty += b.qty;
    for (const s of p.sells) if (s.trade_id === tradeId) qty += s.qty;
    if (qty > 0) out.push({ pair: p, qty });
  }
  return out;
}

/** Pair color palette — visually distinct, avoiding the BUY-green / SELL-red
 * channel so做T connecting lines remain disambiguated from per-trade markers. */
const PAIR_COLORS = [
  "#c688ff", "#5aa0ff", "#3fb5c5", "#e7a73d", "#f08f8f", "#9be3a0",
];
export function pairColor(pairId: number, allPairs: TPair[]): string {
  const idx = allPairs.findIndex((p) => p.id === pairId);
  if (idx < 0) {
    // Pair not in the current list yet — fall back to a stable hash of
    // the id so the chip color doesn't flicker during creation race.
    return PAIR_COLORS[pairId % PAIR_COLORS.length]!;
  }
  return PAIR_COLORS[idx % PAIR_COLORS.length]!;
}
