import { useMemo } from "react";
import type { Position, Quote, Candlesticks, Execution } from "../../api/domain-types";
import { IntradaySpark } from "./IntradaySpark";
import { marketOf } from "../Card/cardHelpers";
import { effectiveSession } from "./sessionWindow";
import { toUsd } from "../../utils/currency";
import { tradingDayOfET, currentOrLastTradingDay } from "./timeFmt";

interface Props {
  position: Position;
  quote: Quote | undefined;
  intraday: Candlesticks | undefined;
  /** Today's broker-side fills (across all symbols — card filters by
   *  symbol). Includes manual orders placed in the LongBridge app, so
   *  Day P/L reflects reality, not just signal-station's own activity. */
  executions?: Execution[];
  onClick(): void;
}

// Default 3 — only ``fmt(avg)`` uses the default in this file (a price).
// last is already explicit ``fmt(last, 3)``; qty / day P/L / market
// value / pl all pass d=0 explicitly.
function fmt(n: number | null | undefined, d = 3): string {
  if (n == null || Number.isNaN(n)) return "—";
  return n.toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d });
}
function pct(n: number): string {
  return `${n >= 0 ? "+" : ""}${fmt(n, 2)}%`;
}

/** Map the market suffix in a symbol ("TSLA.US" → "US") to its display
 *  label. We surface a tiny pill next to the ticker so the user can tell
 *  a 600.SH from a 600.HK at a glance without parsing the symbol. */
function marketBadge(symbol: string): { code: string; label: string } | null {
  const m = symbol.match(/\.([A-Z]+)$/);
  if (!m) return null;
  const code = m[1];
  const labels: Record<string, string> = {
    US: "美股",
    HK: "港股",
    SH: "沪 A",
    SZ: "深 A",
  };
  return { code, label: labels[code] ?? code };
}

/** Map LongBridge ``trade_session`` to its Chinese display label.
 *  Backend resolves this against the live MarketContext + clock so the
 *  pill correctly says 休市 for HK at BJ 19:32 etc. */
const SESSION_LABEL: Record<string, string> = {
  regular: "盘中",
  pre: "盘前",
  post: "盘后",
  overnight: "夜盘",
  closed: "休市",
};

/** Single stock position tile. Shows current price + sparkline + key stats.
 *  Click → open detail pane.  做T allocation state is shown only inside
 *  the detail pane (see PairList) — the card stays focused on price /
 *  P&L so a crowded portfolio still scans at a glance. */
export function PositionCard({ position, quote, intraday, executions, onClick }: Props) {
  // All numeric values that come from the broker carry the position's
  // local currency (HKD for *.HK, USD for *.US). Normalize at the
  // boundary so every downstream computation and display is in USD.
  const sym = position.symbol;
  const last = toUsd(sym, quote?.last_done);
  const change = toUsd(sym, quote?.change);
  const changePct = quote?.change_pct ?? 0;
  const isPos = (change ?? 0) >= 0;

  const qty = position.quantity;
  const avg = toUsd(sym, position.avg_cost);
  const pl = last != null && avg != null ? (last - avg) * qty : null;
  const plPct = last != null && avg != null && avg !== 0 ? ((last - avg) / avg) * 100 : null;

  const prevClose = toUsd(sym, quote?.prev_close);

  // Trade session — guarded against backend cache bugs that misreport
  // weekend ET 04:00 as "pre" (cached weekday session windows match
  // today's wall-clock-of-day). effectiveSession downgrades to "closed"
  // when the date in market tz isn't a real trading weekday.
  const rawSession = quote?.trade_session ?? "regular";
  const tradeSession = effectiveSession(marketOf(position.symbol), rawSession, Date.now());

  // Day P/L baseline matches the backend's session-aware change_pct rule:
  //   pre / regular / closed → yesterday's RTH close (prev_close)
  //   post / overnight       → today's RTH close (today_close, frozen at
  //                            16:00 ET when post starts)
  // today_close is null in non-post/overnight sessions; we fall back to
  // prev_close to keep the dayPl formula well-defined even on transient
  // data gaps.
  const todayClose = toUsd(sym, quote?.today_close);
  const dayBaseline =
    (tradeSession === "post" || tradeSession === "overnight") && todayClose != null
      ? todayClose
      : prevClose;

  // Intraday-aware Day P/L:
  //   Day P/L = last × qty_now + ∑sells_proceeds − ∑buys_cost
  //             − dayBaseline × qty_start
  // where qty_start = qty_now − ∑buys_qty + ∑sells_qty (today's trades),
  // and dayBaseline is the session-aware reference close (see above).
  //
  // Trades arrive in account currency (HKD for HK fills, USD for US fills);
  // we normalize the prices to USD via toUsd so the formula stays
  // currency-consistent. Falls back to (change × qty) when either
  // dayBaseline is missing or last is missing.
  const dayPl = useMemo(() => {
    if (last == null || dayBaseline == null) {
      return change != null ? change * qty : null;
    }
    // Use last-trading-day fallback so Friday's executions count toward
    // Day P/L on a Saturday view (vanilla currentTradingDay returns the
    // calendar date, which would filter Friday's trades out and leave
    // qtyStart over-stated).
    const todayKey = currentOrLastTradingDay();
    let buysCost = 0;
    let sellsProceeds = 0;
    let buysQty = 0;
    let sellsQty = 0;
    for (const e of executions ?? []) {
      // Filter to THIS stock symbol AND today's trading day. Broker
      // returns the whole account's fills in a flat list.
      if (e.symbol !== sym) continue;
      if (tradingDayOfET(e.ts) !== todayKey) continue;
      const price = toUsd(sym, e.price) ?? 0;
      if (e.side === "BUY") {
        buysCost += price * e.qty;
        buysQty += e.qty;
      } else if (e.side === "SELL") {
        sellsProceeds += price * e.qty;
        sellsQty += e.qty;
      }
    }
    const qtyStart = qty - buysQty + sellsQty;
    return last * qty + sellsProceeds - buysCost - dayBaseline * qtyStart;
  }, [last, dayBaseline, change, qty, executions, sym]);

  const marketValue = last != null ? last * qty : null;

  return (
    <article
      className="pcard"
      onClick={onClick}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") onClick(); }}
    >
      <div className="pcard-top">
        <span className="pcard-ticker">{position.ticker}</span>
        {(() => {
          const m = marketBadge(position.symbol);
          return m ? (
            <span className={`pcard-market mkt-${m.code.toLowerCase()}`}>
              {m.label}
            </span>
          ) : null;
        })()}
        {/* Session pill — uses the *effective* session (guarded against
            weekend cache bugs in the backend), not the raw broker value,
            so the pill matches the chart's actual state. */}
        {tradeSession && (
          <span className={`pcard-session sess-${tradeSession}`}>
            {SESSION_LABEL[tradeSession] ?? tradeSession}
          </span>
        )}
        <span className="pcard-arrow" aria-hidden>→</span>
      </div>
      {position.name && (
        <div className="pcard-name" title={position.name}>
          {position.name}
        </div>
      )}

      <div className="pcard-price-row">
        {/* 3 decimals: TSLL et al. trade in sub-dollar increments where the
            third digit is informative — 2 decimals would collapse e.g.
            $9.235 and $9.237 into the same display. */}
        <span className="pcard-price">{last != null ? `$${fmt(last, 3)}` : "—"}</span>
        {change != null && (
          <span className={`pcard-change ${isPos ? "pos" : "neg"}`}>
            {isPos ? "▲" : "▼"} {pct(changePct)}
          </span>
        )}
        {dayPl != null && (
          <span className={`pcard-day-pl ${dayPl >= 0 ? "pos" : "neg"}`}>
            {dayPl >= 0 ? "+" : ""}${fmt(dayPl, 0)}
          </span>
        )}
      </div>

      <div className="pcard-chart">
        <IntradaySpark
          symbol={position.symbol}
          market={marketOf(position.symbol)}
          bars={intraday?.bars}
          session={tradeSession}
          lastDone={last}
          openPrice={quote?.open ?? null}
        />
      </div>

      <div className="pcard-meta four">
        <div>
          <div className="k">持仓</div>
          <div className="v">{fmt(qty, 0)}</div>
        </div>
        <div>
          <div className="k">均价</div>
          <div className="v">{fmt(avg)}</div>
        </div>
        <div>
          <div className="k">总市值</div>
          <div className="v">{marketValue != null ? `$${fmt(marketValue, 0)}` : "—"}</div>
        </div>
        <div>
          <div className="k">浮盈</div>
          <div className={`v ${pl != null && pl >= 0 ? "pos" : "neg"}`}>
            {pl != null
              ? `${pl >= 0 ? "+" : "-"}$${fmt(Math.abs(pl), 0)}`
              : "—"}
            {plPct != null && <small> {pct(plPct)}</small>}
          </div>
        </div>
      </div>

    </article>
  );
}
