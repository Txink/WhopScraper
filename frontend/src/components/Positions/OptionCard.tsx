import { useMemo } from "react";
import type { Position, Quote, Candlesticks, Execution } from "../../api/domain-types";
import { MiniLine } from "./MiniLine";
import { toUsd } from "../../utils/currency";
import { tradingDayOfET, currentTradingDay } from "./timeFmt";

/** US equity options: 1 contract = 100 shares of underlying. Premium is
 *  quoted per-share, so dollar economics multiply by this factor. */
const OPTION_MULT = 100;

interface Props {
  position: Position;
  quote: Quote | undefined;
  /** 30-day daily K-line history for the contract; renders a sparkline
   *  when present so users can see 1-month price drift at a glance. */
  history: Candlesticks | undefined;
  /** Today's broker-side fills (flat across all symbols). OptionCard
   *  filters by symbol — same ticker can have many distinct option
   *  contracts. Includes manual fills not submitted by signal-station. */
  executions?: Execution[];
  /** Click → drill into the contract's detail pane (K-line + trade
   *  history). 做T pair binding doesn't apply to options so the pane
   *  hides those affordances when ``position.type === "option"``. */
  onClick?(): void;
}

// Default 3 — default-precision callsites are ``fmt(last)`` and
// ``fmt(avg)``, both prices. Strike / quantity / day P/L all pass
// d=0 explicitly.
function fmt(n: number | null | undefined, d = 3): string {
  if (n == null || Number.isNaN(n)) return "—";
  return n.toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d });
}

function fmtSigned(n: number, d = 0): string {
  const v = n.toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d });
  return n >= 0 ? `+${v}` : v;
}

function fmtExpiry(s: string | null | undefined): string {
  if (!s) return "—";
  const m = s.match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (m) return `${m[1].slice(2)}/${m[2]}/${m[3]}`;
  if (/^\d{6}$/.test(s)) return `${s.slice(0, 2)}/${s.slice(2, 4)}/${s.slice(4, 6)}`;
  return s;
}

/** Days until expiry — small badge tail next to the date so the user can
 *  scan urgency at a glance. Negative when already expired. */
function daysToExpiry(s: string | null | undefined): number | null {
  if (!s) return null;
  const m = s.match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (!m) return null;
  const exp = new Date(`${m[1]}-${m[2]}-${m[3]}T00:00:00Z`);
  const today = new Date();
  const ms = exp.getTime() - today.getTime();
  return Math.ceil(ms / (1000 * 60 * 60 * 24));
}

/** Bucket a DTE value into one of six visual urgency tiers, escalating
 *  in steps that match how option traders mentally segment time-to-
 *  expiry: long-dated (>60d), watch (30-60d), caution (15-30d), urgent
 *  (7-15d), critical (≤7d), expired (≤0d). The corresponding CSS classes
 *  paint progressively louder color treatments. */
function dteTier(
  dte: number,
): "expired" | "critical" | "urgent" | "caution" | "watch" | "calm" {
  if (dte <= 0) return "expired";
  if (dte <= 7) return "critical";
  if (dte <= 15) return "urgent";
  if (dte <= 30) return "caution";
  if (dte <= 60) return "watch";
  return "calm";
}

export function OptionCard({ position, quote, history, executions, onClick }: Props) {
  const cp = position.option_type;
  const cpShort = cp === "CALL" ? "C" : cp === "PUT" ? "P" : "";
  const cpClass = cp === "CALL" ? "call" : cp === "PUT" ? "put" : "";

  const sym = position.symbol;
  const qty = position.quantity;
  // Normalize HK quotes/costs to USD at the boundary so downstream
  // formulas stay currency-agnostic.
  const avg = toUsd(sym, position.avg_cost);
  const last = toUsd(sym, quote?.last_done);
  const prev = toUsd(sym, quote?.prev_close);

  // Floating P/L for an option contract: (current - cost) × qty × 100
  const pl = last != null && avg != null ? (last - avg) * qty * OPTION_MULT : null;
  const isPos = (pl ?? 0) >= 0;

  // Intraday-aware Day P/L (same formula as PositionCard, × 100 for the
  // option contract multiplier):
  //   Day P/L = (last × qty_now + ∑sells − ∑buys − prev × qty_start)
  //             × OPTION_MULT
  // where qty_start = qty_now − ∑buys_qty + ∑sells_qty. Trades are
  // filtered by symbol so adjacent contracts on the same ticker don't
  // pollute the calc.
  const dayPl = useMemo(() => {
    if (last == null || prev == null) return null;
    const todayKey = currentTradingDay();
    let buysCost = 0;
    let sellsProceeds = 0;
    let buysQty = 0;
    let sellsQty = 0;
    for (const e of executions ?? []) {
      // Filter to THIS contract — broker returns all of today's fills
      // flat; same ticker can have many option contracts.
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
    return (
      (last * qty + sellsProceeds - buysCost - prev * qtyStart) * OPTION_MULT
    );
  }, [last, prev, qty, executions, sym]);

  const dayPos = (dayPl ?? 0) >= 0;
  const changePct = quote?.change_pct ?? 0;
  const change = toUsd(sym, quote?.change);

  // Sparkline source: 30-day daily closes, oldest first. Use the very
  // first bar's close as the "open" reference so the line color reflects
  // whether the contract has appreciated or depreciated over the month
  // window — not just today's direction.
  const sparkValues = useMemo(
    () => history?.bars.map((b) => b.close) ?? [],
    [history],
  );
  const sparkOpen = sparkValues.length > 0 ? sparkValues[0] : null;

  // Strike is integer-valued for the vast majority of US options; render
  // with no decimals per user request even though the underlying value
  // carries OCC fractional precision.
  const strike = position.option_strike;
  const dte = daysToExpiry(position.option_expiry);

  return (
    <article
      className={`ocard${onClick ? " clickable" : ""}`}
      aria-label={`期权 ${position.ticker}`}
      role={onClick ? "button" : undefined}
      tabIndex={onClick ? 0 : undefined}
      onClick={onClick}
      onKeyDown={onClick ? (e) => { if (e.key === "Enter" || e.key === " ") onClick(); } : undefined}
    >
      <div className="ocard-head">
        <span className="ocard-id">
          <span className="ocard-ticker">{position.ticker}</span>
          {cpShort && <span className={`ocard-cp ${cpClass}`}>{cpShort}</span>}
        </span>
        <span className="ocard-strike">{fmt(strike ?? null, 0)}</span>
        <span className="ocard-expiry">
          <span className="ocard-expiry-date">{fmtExpiry(position.option_expiry)}</span>
          {dte !== null && (
            <span className={`ocard-dte tier-${dteTier(dte)}`}>
              {dte > 0 ? `${dte}d` : dte === 0 ? "今日" : "已过期"}
            </span>
          )}
        </span>
      </div>

      <div className="ocard-price-row">
        <span className="ocard-price">{last != null ? `$${fmt(last)}` : "—"}</span>
        {change != null && (
          <span className={`ocard-change ${dayPos ? "pos" : "neg"}`}>
            {dayPos ? "▲" : "▼"} {dayPos ? "+" : ""}{changePct.toFixed(2)}%
          </span>
        )}
        {dayPl != null && (
          <span className={`ocard-day-pl ${dayPos ? "pos" : "neg"}`}>
            {dayPos ? "+" : ""}${fmt(Math.abs(dayPl), 0)}
          </span>
        )}
      </div>

      <div className="ocard-chart">
        {sparkValues.length > 0 ? (
          <MiniLine values={sparkValues} openPrice={sparkOpen} />
        ) : (
          <div className="ocard-chart-skeleton" aria-label="加载 30 天 K 线…" />
        )}
      </div>

      <div className="ocard-meta">
        <div>
          <div className="k">持仓</div>
          <div className="v">{fmt(qty, 0)} 张</div>
        </div>
        <div>
          <div className="k">均价</div>
          <div className="v">{fmt(avg)}</div>
        </div>
        <div>
          <div className="k">浮盈</div>
          <div className={`v ${pl == null ? "" : isPos ? "pos" : "neg"}`}>
            {pl == null ? "—" : `$${fmtSigned(pl, 0)}`}
          </div>
        </div>
      </div>
    </article>
  );
}
