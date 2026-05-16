/** Broker-side session label as carried on Quote.trade_session. */
export type TradeSession = "pre" | "regular" | "post" | "overnight" | "closed";

/** Value accepted by ``/api/candlesticks?sessions=...``.
 *  "all" returns the full pre + regular + post + overnight set in one
 *  call — what US always asks for now that the card shows the unified
 *  24h day window. */
export type SessionsParam = "regular" | "pre" | "post" | "overnight" | "all";

/**
 * Decide which candlestick window to fetch for a card given its market
 * + live ``trade_session`` field.
 *
 * - US always fetches ``sessions=all`` — the card renders a unified
 *   24h x-axis (pre / regular / post / overnight together), so a single
 *   broker call covers every region the user sees. The live session
 *   only affects styling (active-region highlight, closed-state dim),
 *   not which bars to fetch.
 * - HK / CN have only a regular session; ``"regular"`` covers it.
 */
export function resolveSessionParam(
  market: "US" | "HK" | "CN",
  _session: TradeSession,
): SessionsParam {
  if (market === "US") return "all";
  return "regular";
}
