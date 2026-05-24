import { useState } from "react";
import type { SubmitOrderRequest } from "../../../api/orders";

interface Props {
  symbol: string;
  ticker: string;
  lastDone: number | null;
  onSubmit: (req: SubmitOrderRequest) => void;
  onClose: () => void;
}

export function FullOrderModal({ symbol, lastDone, onSubmit, onClose }: Props) {
  const [side, setSide] = useState<"BUY" | "SELL">("BUY");
  const [orderType, setOrderType] = useState<"LIMIT" | "MARKET">("LIMIT");
  const [price, setPrice] = useState<string>(lastDone != null ? lastDone.toFixed(2) : "");
  const [qty, setQty] = useState<string>("100");
  const [tif] = useState<"Day">("Day");
  const [note, setNote] = useState<string>("");

  const submit = () => {
    const p = orderType === "LIMIT" ? parseFloat(price) : null;
    const q = parseInt(qty, 10);
    if (!q) return;
    if (orderType === "LIMIT" && !p) return;
    onSubmit({ symbol, side, order_type: orderType, price: p, qty: q, time_in_force: tif, note: note || null });
  };

  return (
    <div className="modal-backdrop" onClick={onClose} role="presentation">
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <h3>下单（高级）<button onClick={onClose}>×</button></h3>
        <div className="modal-field">
          <label>方向</label>
          <div>
            <button onClick={() => setSide("BUY")} className={side === "BUY" ? "active" : ""}>BUY</button>
            <button onClick={() => setSide("SELL")} className={side === "SELL" ? "active" : ""}>SELL</button>
          </div>
        </div>
        <div className="modal-field">
          <label>类型</label>
          <div>
            <button onClick={() => setOrderType("LIMIT")} className={orderType === "LIMIT" ? "active" : ""}>LIMIT</button>
            <button onClick={() => setOrderType("MARKET")} className={orderType === "MARKET" ? "active" : ""}>MARKET</button>
          </div>
        </div>
        <div className="modal-field">
          <label htmlFor="fom-price">价格</label>
          <input id="fom-price" type="text" value={price} onChange={(e) => setPrice(e.target.value)} disabled={orderType === "MARKET"} />
        </div>
        <div className="modal-field">
          <label htmlFor="fom-qty">数量</label>
          <input id="fom-qty" type="text" value={qty} onChange={(e) => setQty(e.target.value)} />
        </div>
        <div className="modal-field">
          <label>TIF</label>
          <button className="active">Day</button>
        </div>
        <div className="modal-field">
          <label htmlFor="fom-note">备注</label>
          <input id="fom-note" aria-label="备注" type="text" value={note} onChange={(e) => setNote(e.target.value)} />
        </div>
        <div className="modal-foot">
          <button onClick={onClose}>取消</button>
          <button onClick={submit}>提交订单</button>
        </div>
      </div>
    </div>
  );
}
