import { useMemo } from "react";
import type { Position } from "../../api/domain-types";
import { useQuotesStore } from "../../stores/quotes";
import { usePrivacyModeStore } from "../../stores/privacyMode";
import { toUsd } from "../../utils/currency";

function fmt(n: number, d = 0): string {
  return n.toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d });
}
function pct(n: number): string {
  return `${n >= 0 ? "+" : ""}${n.toFixed(2)}%`;
}

interface Props {
  /** Stock positions — drive the 2-cell stock summary. */
  stocks: Position[];
  /** Option positions — when non-empty AND stocks empty, the panel shows
   *  the option-flavored summary. Option contracts settle on 100 shares so
   *  market-value math multiplies by ``MULT``. */
  options?: Position[];
}

/**
 * Top-of-panel portfolio summary. Two cells: 总市值 / 浮盈.
 *
 * 做T-related aggregates ("做T 已实现", "待做T") are intentionally NOT
 * shown here — the stock list page no longer references做T at all. Pair
 * accounting lives entirely in the per-stock detail pane (DetailSummary's
 *做T row + the做T detail popup), keeping the dashboard scan-friendly and avoiding cross-tab
 * coupling on the trades / pairs stores.
 */
export function PortfolioSummary({ stocks, options = [] }: Props) {
  const quotesBySymbol = useQuotesStore((s) => s.quotesBySymbol);
  const privacy = usePrivacyModeStore((s) => s.enabled);

  const isOptionsView = options.length > 0 && stocks.length === 0;

  const optionStats = useMemo(() => {
    let value = 0;
    let cost = 0;
    let pl = 0;
    // US equity option contracts settle on 100 shares of underlying.
    const MULT = 100;
    for (const p of options) {
      // HK options would be HKD-denominated; toUsd normalizes.
      const last = toUsd(p.symbol, quotesBySymbol[p.symbol]?.last_done);
      const avg = toUsd(p.symbol, p.avg_cost) ?? 0;
      if (last != null) {
        value += last * p.quantity * MULT;
        pl += (last - avg) * p.quantity * MULT;
      }
      cost += avg * p.quantity * MULT;
    }
    const plPct = cost > 0 ? (pl / cost) * 100 : 0;
    return { value, pl, plPct };
  }, [options, quotesBySymbol]);

  const stockStats = useMemo(() => {
    let value = 0;
    let cost = 0;
    let pl = 0;

    for (const p of stocks) {
      // toUsd is a pass-through for *.US symbols and divides HK prices
      // by the static USD/HKD rate. Mixed-region portfolio aggregates
      // are therefore in a single currency.
      const last = toUsd(p.symbol, quotesBySymbol[p.symbol]?.last_done);
      const avg = toUsd(p.symbol, p.avg_cost) ?? 0;
      if (last != null) {
        value += last * p.quantity;
        pl += (last - avg) * p.quantity;
      }
      cost += avg * p.quantity;
    }
    const plPct = cost > 0 ? (pl / cost) * 100 : 0;
    return { value, pl, plPct };
  }, [stocks, quotesBySymbol]);

  const s = isOptionsView ? optionStats : stockStats;
  return (
    <div className="portfolio-summary two-col">
      <div className="ps-cell">
        <span className="lbl">总市值</span>
        <span className="val">{privacy ? "***" : `$${fmt(s.value)}`}</span>
      </div>
      <div className="ps-cell">
        <span className="lbl">浮盈</span>
        <span className={`val ${privacy ? "" : s.pl >= 0 ? "pos" : "neg"}`}>
          {privacy ? (
            "***"
          ) : (
            <>
              {s.pl >= 0 ? "+" : ""}${fmt(s.pl)}
              <small className="sub">{pct(s.plPct)}</small>
            </>
          )}
        </span>
      </div>
    </div>
  );
}
