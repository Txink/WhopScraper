import { useEffect, useState } from "react";
import { listOrders, submitOrder, replaceOrder, cancelOrder } from "../../../api/orders";
import { useOrdersStore } from "../../../stores/orders";
import { useQuotesStore } from "../../../stores/quotes";
import { ConfirmModal } from "../ConfirmModal";
import { ActiveOrdersTable } from "./ActiveOrdersTable";
import { QuickOrderRow } from "./QuickOrderRow";
import { ReplaceOrderPopover } from "./ReplaceOrderPopover";
import { FullOrderModal } from "./FullOrderModal";
import type { OrderOut, SubmitOrderRequest, ReplaceOrderRequest } from "../../../api/orders";
import "./TradingPanel.css";

interface Props {
  ticker: string;
  symbol: string;
  /** Optional hook for callers (DetailPane) that want to host the
   *  cancel-confirm + full-order-modal themselves — so they render at
   *  the detail-pane level rather than inside the swipe-track's
   *  transformed subtree (which mis-positions absolute / fixed children).
   *  When omitted (e.g. standalone tests), TradingPanel falls back to
   *  rendering both modals itself. */
  onRequestCancel?: (order: OrderOut) => void;
  onRequestMore?: (defaults: { symbol: string; ticker: string; lastDone: number | null }) => void;
}

export function TradingPanel({ ticker, symbol, onRequestCancel, onRequestMore }: Props) {
  const orders = useOrdersStore((s) => s.byTicker[ticker]) ?? [];
  const setOrders = useOrdersStore((s) => s.setOrders);
  const removeOrder = useOrdersStore((s) => s.removeOrder);
  const quote = useQuotesStore((s) => s.quotesBySymbol[symbol]);
  const lastDone = quote?.last_done ?? null;
  const [activeOnly, setActiveOnly] = useState(false);
  const [replaceFor, setReplaceFor] = useState<OrderOut | null>(null);
  const [fallbackMoreOpen, setFallbackMoreOpen] = useState(false);
  const [fallbackCancel, setFallbackCancel] = useState<OrderOut | null>(null);

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

  const onCancel = (o: OrderOut) => {
    if (onRequestCancel) onRequestCancel(o);
    else setFallbackCancel(o);
  };
  const fallbackCancelFire = async () => {
    if (!fallbackCancel) return;
    try {
      await cancelOrder(fallbackCancel.order_id);
      removeOrder(ticker, fallbackCancel.order_id);
    } catch (e) {
      console.error("cancel failed", e);
    } finally {
      setFallbackCancel(null);
    }
  };

  const onMore = () => {
    if (onRequestMore) onRequestMore({ symbol, ticker, lastDone });
    else setFallbackMoreOpen(true);
  };

  const activeCount = orders.filter(
    (o) => !["FilledStatus", "Filled", "CancelledStatus", "Cancelled", "RejectedStatus", "Rejected"].includes(o.status),
  ).length;

  return (
    <div className="panel trading-panel">
      <div className="trading-panel-head">
        <div className="alerts-h">活跃订单 · {ticker} · 今日</div>
        <button className="row-btn" onClick={() => setActiveOnly((v) => !v)}>
          {activeOnly ? "全部" : "仅活跃"}
        </button>
      </div>
      <div className="trading-panel-body">
        <ActiveOrdersTable orders={orders} activeOnly={activeOnly} onReplace={onReplace} onCancel={onCancel} />
      </div>
      <QuickOrderRow
        symbol={symbol}
        ticker={ticker}
        presets={presets}
        lastDone={lastDone}
        onSubmit={onSubmit}
        onMore={onMore}
      />
      <div className="tab-foot">
        <span className="tab-foot-left">
          <button type="button" className="trade-menu-btn" aria-label="交易面板设置" title="交易面板设置（暂未启用）">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <circle cx="12" cy="12" r="3" />
              <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09a1.65 1.65 0 0 0-1-1.51 1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09a1.65 1.65 0 0 0 1.51-1 1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
            </svg>
          </button>
          <span>交易面板 · 活跃 {activeCount} / 共 {orders.length}</span>
        </span>
      </div>
      {replaceFor && (
        <ReplaceOrderPopover order={replaceFor} onSubmit={submitReplace} onClose={() => setReplaceFor(null)} />
      )}
      {/* Fallback in-pane modals used only when caller doesn't host them.
       *  These render inside the swipe-track's transformed subtree, which
       *  will mis-position fixed/absolute children — only safe when
       *  TradingPanel is mounted standalone (tests, future ad-hoc use). */}
      {fallbackMoreOpen && (
        <FullOrderModal
          symbol={symbol}
          ticker={ticker}
          lastDone={lastDone}
          onSubmit={(r) => { void onSubmit(r); setFallbackMoreOpen(false); }}
          onClose={() => setFallbackMoreOpen(false)}
        />
      )}
      {fallbackCancel && (
        <ConfirmModal
          title="撤销订单"
          description={`确认撤销 ${fallbackCancel.side} ${fallbackCancel.qty} ${fallbackCancel.ticker} @ ${fallbackCancel.price ?? "市价"}？`}
          confirmLabel="确认撤单"
          danger
          onConfirm={fallbackCancelFire}
          onCancel={() => setFallbackCancel(null)}
        />
      )}
    </div>
  );
}
