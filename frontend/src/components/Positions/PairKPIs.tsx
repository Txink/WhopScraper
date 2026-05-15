import { useEffect, useState } from "react";
import { api } from "../../api/http";
import type { PairAggregate } from "../../api/domain-types";

function fmt(n: number, d = 0): string {
  return n.toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d });
}

interface Props {
  ticker: string;
  /** Re-fetch trigger — caller passes the current pairs-list length so a
   *  create/extend/delete mutation forces the aggregate to refresh.
   *  Any change to this value re-fires the underlying ``GET
   *  /api/pairs/aggregate`` request. */
  pairsCount: number;
}

/** 4-cell KPI strip above the trade table: count / realized total /
 *  per-pair average / win rate. Sourced from
 *  ``GET /api/pairs/aggregate`` — backend does the SUM/COUNT in SQL so
 *  the frontend never has to materialize the full pair list just for
 *  totals. The "待做T" 5th cell that used to live here moved to its
 *  own section (consumes ``/api/broker/executions/pending``). */
export function PairKPIs({ ticker, pairsCount }: Props) {
  const [agg, setAgg] = useState<PairAggregate | null>(null);

  useEffect(() => {
    let alive = true;
    api.pairAggregate(ticker)
      .then((r) => { if (alive) setAgg(r); })
      .catch((e) => console.warn("pair aggregate fetch failed", e));
    return () => { alive = false; };
  }, [ticker, pairsCount]);

  const count = agg?.count ?? 0;
  const profitTotal = agg?.profit_total ?? 0;
  const winCount = agg?.win_count ?? 0;
  // Average over all pairs (including partial / one-sided which contribute 0).
  // Simpler and matches a "what is one做T worth on average" read.
  const avg = count > 0 ? profitTotal / count : 0;
  const losses = Math.max(0, count - winCount);
  const winRate = count > 0 ? (winCount / count) * 100 : 0;

  const totalSign = profitTotal >= 0 ? "pos" : "neg";

  return (
    <div className="kpi-strip">
      <div className="kpi-cell">
        <span className="k">做T 次数</span>
        <span className="v">{count}</span>
      </div>
      <div className="kpi-cell">
        <span className="k">累计已实现</span>
        <span className={`v ${totalSign}`}>
          {profitTotal >= 0 ? "+" : ""}${fmt(profitTotal)}
        </span>
      </div>
      <div className="kpi-cell">
        <span className="k">平均单笔</span>
        <span className={`v ${avg >= 0 ? "pos" : "neg"}`}>
          {avg >= 0 ? "+" : ""}${fmt(avg)}
        </span>
      </div>
      <div className="kpi-cell">
        <span className="k">胜率</span>
        <span className="v">
          {count > 0 ? `${winRate.toFixed(0)}%` : "—"}
        </span>
        <span className="sub">
          {count > 0 ? `${winCount} 盈 / ${losses} 平亏` : ""}
        </span>
      </div>
    </div>
  );
}
