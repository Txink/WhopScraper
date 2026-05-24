import { useState } from "react";
import type { OrderOut, ReplaceOrderRequest } from "../../../api/orders";

interface Props {
  order: OrderOut;
  onSubmit: (req: ReplaceOrderRequest) => void;
  onClose: () => void;
}

export function ReplaceOrderPopover({ order, onSubmit, onClose }: Props) {
  const [price, setPrice] = useState<string>(order.price != null ? order.price.toFixed(2) : "");
  const [qty, setQty] = useState<string>(String(order.qty));

  const submit = () => {
    const np = parseFloat(price);
    const nq = parseInt(qty, 10);
    const newPrice = Number.isFinite(np) && np !== order.price ? np : null;
    const newQty = Number.isFinite(nq) && nq !== order.qty ? nq : null;
    if (newPrice == null && newQty == null) return;
    onSubmit({ price: newPrice, qty: newQty });
  };

  return (
    <div className="replace-popover" onClick={(e) => e.stopPropagation()}>
      <div className="field">
        <label htmlFor="rp-price">价</label>
        <input id="rp-price" aria-label="价" type="text" value={price} onChange={(e) => setPrice(e.target.value)} />
      </div>
      <div className="field">
        <label htmlFor="rp-qty">量</label>
        <input id="rp-qty" aria-label="量" type="text" value={qty} onChange={(e) => setQty(e.target.value)} />
      </div>
      <div className="actions">
        <button onClick={onClose}>取消</button>
        <button onClick={submit}>确认</button>
      </div>
    </div>
  );
}
