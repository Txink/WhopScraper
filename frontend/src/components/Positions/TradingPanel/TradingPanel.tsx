import { useEffect, useState } from "react";
import { listOrders, submitOrder, replaceOrder, cancelOrder, isOrderTerminal } from "../../../api/orders";
import { useOrdersStore } from "../../../stores/orders";
import { useQuotesStore } from "../../../stores/quotes";
import { ConfirmModal } from "../ConfirmModal";
import { notice } from "../../../stores/notices";
import { ActiveOrdersTable } from "./ActiveOrdersTable";
import { QuickOrderRow } from "./QuickOrderRow";
import { FullOrderModal } from "./FullOrderModal";
import type { OrderOut, SubmitOrderRequest } from "../../../api/orders";
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
      notice.success(`已提交 ${req.side} ${req.qty} ${req.symbol} @ $${req.price?.toFixed(2) ?? "市价"}`, "detail");
    } catch (e) {
      console.error("submit failed", e);
      notice.error(`下单失败：${e instanceof Error ? e.message : String(e)}`, "detail");
    }
  };

  // Inline edit commit: at most one of {price, qty} changed per event.
  // We forward only the changed field as `null` for the other — the
  // service treats null as "leave unchanged".
  const onReplaceField = async (
    o: OrderOut,
    change: { price?: number | null; qty?: number | null },
  ) => {
    try {
      await replaceOrder(o.order_id, {
        price: change.price ?? null,
        qty: change.qty ?? null,
      });
      notice.success("改单已提交", "detail");
      // Refetch to pick up authoritative price/qty (and any broker echo).
      listOrders(ticker)
        .then((r) => setOrders(ticker, r.orders))
        .catch(() => {});
    } catch (e) {
      console.error("replace failed", e);
      notice.error(`改单失败：${e instanceof Error ? e.message : String(e)}`, "detail");
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
      notice.success("已撤单", "detail");
    } catch (e) {
      console.error("cancel failed", e);
      notice.error(`撤单失败：${e instanceof Error ? e.message : String(e)}`, "detail");
    } finally {
      setFallbackCancel(null);
    }
  };

  const onMore = () => {
    if (onRequestMore) onRequestMore({ symbol, ticker, lastDone });
    else setFallbackMoreOpen(true);
  };

  const activeCount = orders.filter((o) => !isOrderTerminal(o)).length;

  return (
    <div className="panel trading-panel">
      <div className="trading-panel-head">
        <div className="alerts-h">活跃订单 · {ticker} · 今日</div>
        <button className="row-btn" onClick={() => setActiveOnly((v) => !v)}>
          {activeOnly ? "全部" : "仅活跃"}
        </button>
      </div>
      <div className="trading-panel-body">
        <ActiveOrdersTable orders={orders} activeOnly={activeOnly} onReplace={onReplaceField} onCancel={onCancel} />
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
