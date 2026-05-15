import { useEffect, useState } from "react";
import { api } from "../../api/http";
import type { PendingExecutions } from "../../api/domain-types";
import { fmtBjRel } from "./timeFmt";

function fmt(n: number, d = 0): string {
  return n.toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d });
}

interface Props {
  ticker: string;
  /** Re-fetch trigger — caller passes the pairs-list length so a做T
   *  create/extend/delete mutation forces the pending list to refresh. */
  pairsCount: number;
}

/**
 * "待做T" — broker fills whose qty exceeds the qty already allocated to
 * any做T pair. Sourced from ``GET /api/broker/executions/pending``; the
 * server computes ``allocated_qty`` from each row's ``t_pair_tags``
 * column so neither client nor server has to scan every pair.
 *
 * Collapsed by default — top-row summary shows the BUY/SELL pending qty
 * totals, expand to see the actual list of trade rows.
 */
export function PendingTrades({ ticker, pairsCount }: Props) {
  const [data, setData] = useState<PendingExecutions | null>(null);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    let alive = true;
    api.pendingExecutions(ticker)
      .then((r) => { if (alive) setData(r); })
      .catch((e) => console.warn("pending executions fetch failed", e));
    return () => { alive = false; };
  }, [ticker, pairsCount]);

  if (!data) return null;
  const buyQty = data.pending_buy_qty;
  const sellQty = data.pending_sell_qty;
  const total = buyQty + sellQty;
  if (total === 0) {
    // Everything is paired up — no need to clutter the pane.
    return null;
  }

  return (
    <div className="panel pending-panel">
      <div className="panel-head">
        <h4>
          <button
            className="pending-toggle"
            onClick={() => setOpen((v) => !v)}
            aria-expanded={open}
            type="button"
          >
            <span className="caret">{open ? "▾" : "▸"}</span>
            待做T
          </button>
        </h4>
        <span className="meta">
          {buyQty > 0 && <span className="pending-pill buy">BUY {fmt(buyQty)}</span>}
          {sellQty > 0 && <span className="pending-pill sell">SELL {fmt(sellQty)}</span>}
        </span>
      </div>
      {open && data.trades.length > 0 && (
        <table className="trade-tbl">
          <thead>
            <tr>
              <th>时间</th>
              <th>方向</th>
              <th style={{ textAlign: "right" }}>数量</th>
              <th style={{ textAlign: "right" }}>已绑</th>
              <th style={{ textAlign: "right" }}>剩余</th>
              <th style={{ textAlign: "right" }}>成交价</th>
            </tr>
          </thead>
          <tbody>
            {data.trades.map((t) => (
              <tr key={t.order_id} className="t-row">
                <td className="tic">{fmtBjRel(t.ts)}</td>
                <td>
                  <span className={`cell-side ${t.side.toLowerCase()}`}>{t.side}</span>
                </td>
                <td style={{ textAlign: "right" }}>{fmt(t.qty)}</td>
                <td style={{ textAlign: "right", color: "var(--fg-3)" }}>
                  {fmt(t.allocated_qty)}
                </td>
                <td style={{ textAlign: "right", color: "var(--warn)" }}>
                  {fmt(t.pending_qty)}
                </td>
                <td style={{ textAlign: "right" }}>{t.price.toFixed(3)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
