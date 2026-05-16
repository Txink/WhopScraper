/** Broker-side session label as carried on Quote.trade_session. */
export type TradeSession = "pre" | "regular" | "post" | "overnight" | "closed";

/** Value accepted by ``/api/candlesticks?sessions=...``. */
export type SessionsParam = "regular" | "pre" | "post" | "overnight";

/**
 * Decide which candlestick window to fetch for a card given its market
 * + live ``trade_session`` field.
 *
 * - US active sessions pass through identically — backend serves
 *   ``sessions=all`` SDK data and lets us ET-filter, so passing the
 *   specific session is honored.
 * - US closed → fetch the prior trading day's post window so the card
 *   still shows the freshest tape (matches 富途 weekend behavior).
 * - HK / CN have only regular; anything else maps to regular as a safe
 *   fallback (HK never legitimately emits pre / post / overnight, but
 *   the type system can't prove that).
 */
export function resolveSessionParam(
  market: "US" | "HK" | "CN",
  session: TradeSession,
): SessionsParam {
  if (market === "US") {
    if (session === "closed") return "post";
    return session;
  }
  // HK / CN
  return "regular";
}
