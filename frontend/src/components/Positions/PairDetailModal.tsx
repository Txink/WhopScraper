import { useEffect } from "react";
import type { TPair, Trade } from "../../api/domain-types";
import {
  pairAvgBuyPrice,
  pairAvgSellPrice,
  pairColor,
  pairMatchedQty,
} from "./pairMath";
import { fmtBjRel } from "./timeFmt";

interface Props {
  pair: TPair;
  /** Trades known on the client for this ticker. The modal only displays
   *  the per-allocation rows for trades it can find here — if a referenced
   *  trade hasn't been paged into the store yet, the row still renders
   *  with the qty but a placeholder for price. */
  trades: Trade[];
  /** Full pair list for the ticker — used to color the modal header
   *  consistently with the row chip the user clicked from. */
  allPairs: TPair[];
  onClose(): void;
  /** Triggered when the user clicks 解绑配对 in the footer. Caller is
   *  expected to run a confirm prompt + delete the pair via the
   *  backend + close this modal. */
  onUnbind(pairId: number): Promise<void> | void;
}

function fmt(n: number, d = 2): string {
  return n.toLocaleString("en-US", {
    minimumFractionDigits: d,
    maximumFractionDigits: d,
  });
}

/**
 * 做T pair detail modal. Surfaces the pair's summary (matched qty, avg
 * BUY / SELL price, realized P/L) and per-trade allocations.
 *
 * Opens when the user clicks a T-N chip in the trade list (DetailPane
 * binds the open state to ``detailView.activePairId``); ESC or backdrop
 * click closes by clearing that store field.
 */
export function PairDetailModal({ pair, trades, allPairs, onClose, onUnbind }: Props) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const tradeById = (id: string) => trades.find((t) => t.id === id);
  const matchedQty = pairMatchedQty(pair);
  const avgBuy = pairAvgBuyPrice(pair, trades);
  const avgSell = pairAvgSellPrice(pair, trades);
  const profit = pair.profit;
  const profitPct = avgBuy > 0 ? ((avgSell - avgBuy) / avgBuy) * 100 : 0;
  const color = pairColor(pair.id, allPairs);
  const buyQtyTotal = pair.buys.reduce((s, b) => s + b.qty, 0);
  const sellQtyTotal = pair.sells.reduce((s, b) => s + b.qty, 0);
  const partial = buyQtyTotal !== sellQtyTotal;

  return (
    <div className="pair-modal-backdrop" onClick={onClose} role="presentation">
      <div
        className="modal-card pair-modal"
        onClick={(e) => e.stopPropagation()}
        style={{ ["--pair-color" as never]: color }}
        role="dialog"
        aria-label={`T-${pair.id} 做T 详情`}
      >
        <header className="modal-head">
          <h3>
            <span className="pair-chip-mini" style={{ ["--pair-color" as never]: color }}>
              <span className="dotty" />T-{pair.id}
            </span>
            做T 详情
            {partial && <span className="partial-tag">部分</span>}
          </h3>
          <button
            type="button"
            className="modal-close"
            onClick={onClose}
            aria-label="关闭"
          >×</button>
        </header>

        <section className="pair-summary">
          <div className="ps-cell">
            <span className="k">配对量</span>
            <span className="v">{fmt(matchedQty, 0)} 股</span>
          </div>
          <div className="ps-cell">
            <span className="k">买入均价</span>
            <span className="v">${fmt(avgBuy, 3)}</span>
          </div>
          <div className="ps-cell">
            <span className="k">卖出均价</span>
            <span className="v">${fmt(avgSell, 3)}</span>
          </div>
          <div className="ps-cell">
            <span className="k">已实现</span>
            <span className={`v ${profit >= 0 ? "pos" : "neg"}`}>
              {profit >= 0 ? "+" : ""}${fmt(profit, 2)}
              <span className={`sub-pct ${profit >= 0 ? "pos" : "neg"}`}>
                {profit >= 0 ? " +" : " "}{fmt(profitPct, 2)}%
              </span>
            </span>
          </div>
        </section>

        <section className="pair-allocations">
          <h4>组成</h4>
          <table className="modal-tbl">
            <thead>
              <tr>
                <th>方向</th>
                <th>时间</th>
                <th style={{ textAlign: "right" }}>分配量</th>
                <th style={{ textAlign: "right" }}>成交价</th>
              </tr>
            </thead>
            <tbody>
              {pair.buys.map((b) => {
                const t = tradeById(b.trade_id);
                return (
                  <tr key={`b-${b.trade_id}`}>
                    <td><span className="cell-side buy">BUY</span></td>
                    <td className="tic">{t ? fmtBjRel(t.ts) : "—"}</td>
                    <td style={{ textAlign: "right" }}>{fmt(b.qty, 0)}</td>
                    <td style={{ textAlign: "right" }}>
                      {t ? `$${fmt(t.price, 3)}` : "—"}
                    </td>
                  </tr>
                );
              })}
              {pair.sells.map((s) => {
                const t = tradeById(s.trade_id);
                return (
                  <tr key={`s-${s.trade_id}`}>
                    <td><span className="cell-side sell">SELL</span></td>
                    <td className="tic">{t ? fmtBjRel(t.ts) : "—"}</td>
                    <td style={{ textAlign: "right" }}>{fmt(s.qty, 0)}</td>
                    <td style={{ textAlign: "right" }}>
                      {t ? `$${fmt(t.price, 3)}` : "—"}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </section>

        <footer className="pair-modal-foot">
          <button
            type="button"
            className="btn danger"
            onClick={() => void onUnbind(pair.id)}
          >
            解绑配对
          </button>
        </footer>
      </div>
    </div>
  );
}
