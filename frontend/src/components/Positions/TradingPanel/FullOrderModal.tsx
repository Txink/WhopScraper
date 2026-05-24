import { useEffect, useState } from "react";
import type { SubmitOrderRequest } from "../../../api/orders";
import "./FullOrderModal.css";

interface Props {
  symbol: string;
  ticker: string;
  lastDone: number | null;
  onSubmit: (req: SubmitOrderRequest) => void;
  onClose: () => void;
  /** "bottom" anchors the card near the bottom of .detail-pane so it
   *  pops up close to the QuickOrderRow that triggered it, rather than
   *  floating in the vertical middle. Default "center" for callers
   *  who want the standard centered placement. */
  placement?: "center" | "bottom";
}

/** Advanced order entry. Mirrors the project's PairDetailModal pattern
 *  (.pair-modal-backdrop + .modal-card) so it anchors inside the
 *  ``.detail-pane`` rather than the viewport — keeps the overlay
 *  visually scoped to the working area and avoids issues with
 *  position:fixed under transformed ancestors. */
export function FullOrderModal({ symbol, ticker, lastDone, onSubmit, onClose, placement = "center" }: Props) {
  const [side, setSide] = useState<"BUY" | "SELL">("BUY");
  const [orderType, setOrderType] = useState<"LIMIT" | "MARKET">("LIMIT");
  const [price, setPrice] = useState<string>(lastDone != null ? lastDone.toFixed(2) : "");
  const [qty, setQty] = useState<string>("100");
  const tif = "Day" as const;
  const [note, setNote] = useState<string>("");

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  const submit = () => {
    const p = orderType === "LIMIT" ? parseFloat(price) : null;
    const q = parseInt(qty, 10);
    if (!q || q <= 0) return;
    if (orderType === "LIMIT" && (!p || p <= 0)) return;
    onSubmit({
      symbol, side, order_type: orderType, price: p, qty: q,
      time_in_force: tif, note: note || null,
    });
  };

  const total = (() => {
    const p = orderType === "LIMIT" ? parseFloat(price) : (lastDone ?? 0);
    const q = parseInt(qty, 10) || 0;
    return p && q
      ? `$${(p * q).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
      : "—";
  })();

  return (
    <div
      className={`pair-modal-backdrop ${placement === "bottom" ? "placement-bottom" : ""}`}
      role="presentation"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="modal-card full-order-modal" role="dialog" aria-label="高级下单">
        <header className="modal-head">
          <h3>下单 · {ticker}</h3>
          <button type="button" className="modal-close" onClick={onClose} aria-label="关闭">×</button>
        </header>

        <div className="fom-grid">
          <div className="fom-field">
            <span className="fom-label">方向</span>
            <div className="fom-seg">
              <button
                type="button"
                className={`fom-seg-btn ${side === "BUY" ? "active" : ""}`}
                onClick={() => setSide("BUY")}
              >BUY</button>
              <button
                type="button"
                className={`fom-seg-btn ${side === "SELL" ? "active" : ""}`}
                onClick={() => setSide("SELL")}
              >SELL</button>
            </div>
          </div>
          <div className="fom-field">
            <span className="fom-label">类型</span>
            <div className="fom-seg">
              <button
                type="button"
                className={`fom-seg-btn ${orderType === "LIMIT" ? "active" : ""}`}
                onClick={() => setOrderType("LIMIT")}
              >LIMIT</button>
              <button
                type="button"
                className={`fom-seg-btn ${orderType === "MARKET" ? "active" : ""}`}
                onClick={() => setOrderType("MARKET")}
              >MARKET</button>
            </div>
          </div>
          <div className="fom-field">
            <label className="fom-label" htmlFor="fom-price">价格</label>
            <input
              id="fom-price"
              className="fom-input"
              type="text"
              value={price}
              onChange={(e) => setPrice(e.target.value)}
              disabled={orderType === "MARKET"}
              placeholder={orderType === "MARKET" ? "市价" : ""}
            />
          </div>
          <div className="fom-field">
            <label className="fom-label" htmlFor="fom-qty">数量</label>
            <input
              id="fom-qty"
              className="fom-input"
              type="text"
              value={qty}
              onChange={(e) => setQty(e.target.value)}
            />
          </div>
          <div className="fom-field">
            <span className="fom-label">TIF</span>
            <div className="fom-seg">
              <button type="button" className="fom-seg-btn active">Day</button>
            </div>
          </div>
          <div className="fom-field">
            <span className="fom-label">总价</span>
            <span className="fom-total">{total}</span>
          </div>
        </div>

        <div className="fom-field fom-note-field">
          <label className="fom-label" htmlFor="fom-note">备注</label>
          <input
            id="fom-note"
            aria-label="备注"
            className="fom-input"
            type="text"
            value={note}
            onChange={(e) => setNote(e.target.value)}
            placeholder="可选"
          />
        </div>

        <footer className="pair-modal-foot fom-foot">
          <button type="button" className="btn ghost" onClick={onClose}>取消</button>
          <button
            type="button"
            className="btn primary"
            onClick={submit}
          >提交订单</button>
        </footer>
      </div>
    </div>
  );
}
