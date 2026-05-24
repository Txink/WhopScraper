import { useEffect, useState } from "react";
import { listOrders, submitOrder, replaceOrder, cancelOrder } from "../../../api/orders";
import { useOrdersStore } from "../../../stores/orders";
import { useQuotesStore } from "../../../stores/quotes";
import { ActiveOrdersTable } from "./ActiveOrdersTable";
import { QuickOrderRow } from "./QuickOrderRow";
import { ReplaceOrderPopover } from "./ReplaceOrderPopover";
import { FullOrderModal } from "./FullOrderModal";
import type { OrderOut, SubmitOrderRequest, ReplaceOrderRequest } from "../../../api/orders";
import "./TradingPanel.css";

interface Props { ticker: string; symbol: string }

export function TradingPanel({ ticker, symbol }: Props) {
  const orders = useOrdersStore((s) => s.byTicker[ticker]) ?? [];
  const setOrders = useOrdersStore((s) => s.setOrders);
  const removeOrder = useOrdersStore((s) => s.removeOrder);
  const quote = useQuotesStore((s) => s.quotesBySymbol[symbol]);
  const lastDone = quote?.last_done ?? null;
  const [activeOnly, setActiveOnly] = useState(false);
  const [replaceFor, setReplaceFor] = useState<OrderOut | null>(null);
  const [moreOpen, setMoreOpen] = useState(false);
  const [confirmCancel, setConfirmCancel] = useState<OrderOut | null>(null);

  // TODO: source presets from page settings; fallback for now.
  const presets = { regular: 200, half: 100, third: 67 };

  useEffect(() => {
    listOrders(ticker).then((r) => setOrders(ticker, r.orders))
      .catch((e) => console.warn("orders fetch failed", e));
  }, [ticker, setOrders]);

  const onSubmit = async (req: SubmitOrderRequest) => {
    try {
      const o = await submitOrder(req);
      useOrdersStore.getState().upsertOrder(o.ticker, o);
    } catch (e) {
      console.error("submit failed", e);
    }
  };

  const onReplace = (o: OrderOut) => setReplaceFor(o);

  const submitReplace = async (req: ReplaceOrderRequest) => {
    if (!replaceFor) return;
    try {
      await replaceOrder(replaceFor.order_id, req);
      setReplaceFor(null);
    } catch (e) {
      console.error("replace failed", e);
    }
  };

  const onCancel = (o: OrderOut) => setConfirmCancel(o);

  const confirmCancelFire = async () => {
    if (!confirmCancel) return;
    try {
      await cancelOrder(confirmCancel.order_id);
      removeOrder(ticker, confirmCancel.order_id);
      setConfirmCancel(null);
    } catch (e) {
      console.error("cancel failed", e);
    }
  };

  return (
    <div className="trading-panel">
      <div className="trading-panel-head">
        <div className="alerts-h">活跃订单 · {ticker} · 今日</div>
        <button className="row-btn" onClick={() => setActiveOnly((v) => !v)}>
          {activeOnly ? "全部" : "仅活跃"}
        </button>
      </div>
      <ActiveOrdersTable orders={orders} activeOnly={activeOnly} onReplace={onReplace} onCancel={onCancel} />
      <QuickOrderRow symbol={symbol} ticker={ticker} presets={presets} lastDone={lastDone} onSubmit={onSubmit} onMore={() => setMoreOpen(true)} />
      {replaceFor && <ReplaceOrderPopover order={replaceFor} onSubmit={submitReplace} onClose={() => setReplaceFor(null)} />}
      {moreOpen && <FullOrderModal symbol={symbol} ticker={ticker} lastDone={lastDone} onSubmit={(r) => { void onSubmit(r); setMoreOpen(false); }} onClose={() => setMoreOpen(false)} />}
      {confirmCancel && (
        <div className="modal-backdrop" onClick={() => setConfirmCancel(null)} role="presentation">
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <h3>撤销订单</h3>
            <p>确认撤销 {confirmCancel.side} {confirmCancel.qty} {confirmCancel.ticker} @ {confirmCancel.price}？</p>
            <div className="modal-foot">
              <button onClick={() => setConfirmCancel(null)}>取消</button>
              <button className="row-btn danger" onClick={() => { void confirmCancelFire(); }}>确认撤单</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
