import { useEffect, useState } from "react";
import { api } from "../../api/http";
import type { PairAggregate, Position, Quote } from "../../api/domain-types";

/** Chevron-left back glyph. Inline SVG using ``currentColor`` so the
 *  parent button drives the visual state via plain CSS ``color``. Same
 *  authoring style as ``Dashboard/icons.tsx``. */
function ChevronLeftIcon({ size = 16 }: { size?: number }) {
  return (
    <svg
      viewBox="0 0 16 16"
      width={size}
      height={size}
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <polyline points="10 3 5 8 10 13" />
    </svg>
  );
}

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
  /** Pairs currently in the store for this ticker. Re-fetch trigger for
   *  the做T aggregate: a create/extend/delete mutation changes ``length``
   *  and forces a fresh ``GET /api/pairs/aggregate`` round-trip. */
  pairsCount: number;
  /** Click handler for the inline back button rendered before the ticker.
   *  Replaces the older standalone "返回持仓总览" pill above the card. */
  onBack(): void;
}

/** Top-of-detail summary card.
 *
 *  Left cluster keeps its original "ticker · price · change" single-line
 *  identity. The right cluster stacks two compact stat lines —
 *  position basics (持仓/均价/市值/浮盈) and做T 统计
 *  (做T次数/累计已实现/胜率) — sharing the panel's vertical
 *  centerline so total card height stays close to the prior single-row
 *  layout. Options render only the position line (做T binding is a
 *  stock-only concept). */
export function DetailSummary({ position, quote, pairsCount, onBack }: Props) {
  const isOption = position.type === "option";
  const last = quote?.last_done ?? null;
  const change = quote?.change ?? null;
  const changePct = quote?.change_pct ?? 0;
  const isPos = (change ?? 0) >= 0;
  const avg = position.avg_cost;
  const value = last != null ? last * position.quantity : null;
  const pl = last != null && avg != null ? (last - avg) * position.quantity : null;
  const plPct = last != null && avg != null && avg !== 0 ? ((last - avg) / avg) * 100 : null;

  // 做T aggregate — fetched per-ticker (skipped for option rows; backend
  // returns zeros anyway but the call would still cost an RTT).
  const [agg, setAgg] = useState<PairAggregate | null>(null);
  useEffect(() => {
    if (isOption) {
      setAgg(null);
      return;
    }
    let alive = true;
    api
      .pairAggregate(position.ticker)
      .then((r) => {
        if (alive) setAgg(r);
      })
      .catch((e) => console.warn("pair aggregate fetch failed", e));
    return () => {
      alive = false;
    };
  }, [position.ticker, pairsCount, isOption]);

  const pairCount = agg?.count ?? 0;
  const profitTotal = agg?.profit_total ?? 0;
  const winCount = agg?.win_count ?? 0;
  const losses = Math.max(0, pairCount - winCount);
  const winRate = pairCount > 0 ? (winCount / pairCount) * 100 : 0;
  const totalSign = profitTotal >= 0 ? "pos" : "neg";

  return (
    <div className="detail-summary">
      {/* Left cluster: ticker + live price + change pill — single line,
       *  original font sizes. Vertically centered against the stacked
       *  stats on the right via the parent flex ``align-items: center``. */}
      <div className="ds-left">
        <button
          type="button"
          className="ds-back"
          onClick={onBack}
          aria-label="返回持仓总览"
          title="返回持仓总览"
        >
          <ChevronLeftIcon size={18} />
        </button>
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
      {/* Right cluster: two compact stat strips stacked. Typography is
       *  shrunk vs. the original single-row layout so the panel doesn't
       *  grow taller. */}
      <div className="ds-right-stack">
        <div className="ds-stats-line">
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
        {!isOption && (
          <div className="ds-stats-line">
            <div className="head-stat">
              <span className="lbl">做T 次数</span>
              <span className="val">{pairCount}</span>
            </div>
            <div className="head-stat">
              <span className="lbl">累计已实现</span>
              <span className={`val ${totalSign}`}>
                {profitTotal >= 0 ? "+" : ""}${fmt(profitTotal, 0)}
              </span>
            </div>
            <div className="head-stat">
              <span className="lbl">胜率</span>
              <span className="val">
                {pairCount > 0 ? `${winRate.toFixed(0)}%` : "—"}
                {pairCount > 0 && (
                  <small className="ds-pl-pct">({winCount} 盈 / {losses} 平亏)</small>
                )}
              </span>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
