import type { Position, Quote } from "../../api/domain-types";

// Default precision is 3 because this file's only ``fmt(x)`` callsites
// are prices (last_done / avg_cost). Quantity / P&L / market value pass
// d=0 explicitly; the pct() helper passes d=2 explicitly.
function fmt(n: number | null | undefined, d = 3): string {
  if (n == null || Number.isNaN(n)) return "—";
  return n.toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d });
}
function pct(n: number): string {
  return `${n >= 0 ? "+" : ""}${fmt(n, 2)}%`;
}

interface Props {
  position: Position;
  quote: Quote | undefined;
}

/** Top-of-detail summary card: ticker, current price, change, key stats. */
export function DetailSummary({ position, quote }: Props) {
  const last = quote?.last_done ?? null;
  const change = quote?.change ?? null;
  const changePct = quote?.change_pct ?? 0;
  const isPos = (change ?? 0) >= 0;
  const avg = position.avg_cost;
  const value = last != null ? last * position.quantity : null;
  const pl = last != null && avg != null ? (last - avg) * position.quantity : null;
  const plPct = last != null && avg != null && avg !== 0 ? ((last - avg) / avg) * 100 : null;

  return (
    <div className="detail-summary single-row">
      {/* Left cluster: ticker + symbol + live price + change pill — all on
       *  one baseline so the eye reads "what is this and where is it now". */}
      <div className="ds-left">
        <span className="detail-ticker">{position.ticker}</span>
        {last != null && (
          <span
            className={`detail-price ${change != null ? (isPos ? "pos" : "neg") : ""}`}
          >
            {fmt(last)}
          </span>
        )}
        {change != null && (
          <span className={`detail-change ${isPos ? "pos" : "neg"}`}>
            {pct(changePct)}
          </span>
        )}
      </div>
      {/* Right cluster: position stats laid out as compact label/value pairs.
       *  No internal divider — the gap + lbl/val typography contrast carries
       *  enough separation in a single-row layout. */}
      <div className="ds-right">
        <div className="head-stat">
          <span className="lbl">持仓</span>
          <span className="val">{fmt(position.quantity, 0)}</span>
        </div>
        <div className="head-stat">
          <span className="lbl">均价</span>
          <span className="val">{fmt(avg)}</span>
        </div>
        <div className="head-stat">
          <span className="lbl">市值</span>
          <span className="val">{fmt(value, 0)}</span>
        </div>
        <div className="head-stat">
          <span className="lbl">浮盈</span>
          <span className={`val ${(pl ?? 0) >= 0 ? "pos" : "neg"}`}>
            {pl != null && (pl >= 0 ? "+" : "")}{fmt(pl, 0)}
            {plPct != null && <small className="ds-pl-pct">({pct(plPct)})</small>}
          </span>
        </div>
      </div>
    </div>
  );
}
