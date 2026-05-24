import { useEffect, useState } from "react";
import type { SubmitOrderRequest } from "../../../api/orders";

interface Presets { regular: number; half: number; third: number }
interface Props {
  symbol: string;
  ticker: string;
  presets: Presets;
  lastDone: number | null;
  onSubmit: (req: SubmitOrderRequest) => void;
  onMore: () => void;
}

export function QuickOrderRow({ symbol, presets, lastDone, onSubmit, onMore }: Props) {
  const [side, setSide] = useState<"BUY" | "SELL">("BUY");
  const [orderType, setOrderType] = useState<"LIMIT" | "MARKET">("LIMIT");
  const [price, setPrice] = useState<string>(lastDone != null ? lastDone.toFixed(2) : "");
  const [qty, setQty] = useState<string>(String(presets.regular));
  const [presetsOpen, setPresetsOpen] = useState(false);

  useEffect(() => {
    if (orderType === "LIMIT" && lastDone != null) setPrice(lastDone.toFixed(2));
  }, [lastDone, orderType]);

  const submit = () => {
    const p = orderType === "LIMIT" ? parseFloat(price) : null;
    const q = parseInt(qty, 10);
    if (!q || q <= 0) return;
    if (orderType === "LIMIT" && (!p || p <= 0)) return;
    onSubmit({ symbol, side, order_type: orderType, price: p, qty: q, time_in_force: "Day", note: null });
  };

  const total = (() => {
    const p = orderType === "LIMIT" ? parseFloat(price) : lastDone ?? 0;
    const q = parseInt(qty, 10) || 0;
    return p && q ? (p * q).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : "—";
  })();

  return (
    <div className="quick-order">
      <div className="toggle-group">
        <button className={`toggle-btn buy ${side === "BUY" ? "active" : ""}`} onClick={() => setSide("BUY")}>BUY</button>
        <button className={`toggle-btn sell ${side === "SELL" ? "active" : ""}`} onClick={() => setSide("SELL")}>SELL</button>
      </div>
      <div className="toggle-group">
        <button className={`toggle-btn neutral ${orderType === "LIMIT" ? "active" : ""}`} onClick={() => setOrderType("LIMIT")}>LIMIT</button>
        <button className={`toggle-btn neutral ${orderType === "MARKET" ? "active" : ""}`} onClick={() => setOrderType("MARKET")}>MKT</button>
      </div>
      <div className="field">
        <label htmlFor="qo-price" className="k">价</label>
        <input
          id="qo-price"
          aria-label="价"
          className="num-input"
          type="text"
          value={price}
          disabled={orderType === "MARKET"}
          onChange={(e) => setPrice(e.target.value)}
        />
      </div>
      <div className="field" style={{ position: "relative" }}>
        <label htmlFor="qo-qty" className="k">数</label>
        <input
          id="qo-qty"
          aria-label="数"
          className="num-input qty-input"
          type="text"
          value={qty}
          onChange={(e) => setQty(e.target.value)}
        />
        <button
          className="row-btn"
          style={{ padding: "2px 6px", fontSize: 10 }}
          aria-label="数量预设"
          onClick={() => setPresetsOpen((o) => !o)}
        >
          数 ▾
        </button>
        {presetsOpen && (
          <div style={{ position: "absolute", top: "100%", right: 0, background: "var(--bg-2)", border: "1px solid var(--line-strong)", borderRadius: "var(--radius-card)", padding: 4, zIndex: 5 }}>
            <button className="row-btn" onClick={() => { setQty(String(presets.regular)); setPresetsOpen(false); }}>常规 {presets.regular}</button>
            <button className="row-btn" onClick={() => { setQty(String(presets.half)); setPresetsOpen(false); }}>半仓 {presets.half}</button>
            <button className="row-btn" onClick={() => { setQty(String(presets.third)); setPresetsOpen(false); }}>1/3 {presets.third}</button>
          </div>
        )}
      </div>
      <button className={`submit-btn ${side === "SELL" ? "sell" : ""}`} onClick={submit}>提交</button>
      <button className="more-btn" onClick={onMore}>更多 ▾</button>
      <div className="quick-summary">SIDE <b>{side}</b> · 总额 <b>${total}</b></div>
    </div>
  );
}
