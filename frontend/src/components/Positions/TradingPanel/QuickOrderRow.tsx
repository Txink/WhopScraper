import { useEffect, useRef, useState } from "react";
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

/** Two-row quick-order form:
 *
 *   ┌──────────────┬──────────────┬────────────────────────────────────┐
 *   │  BUY  SELL   │ 价：[___]    │                                    │
 *   │ LIMIT MARKET │ 数：[___] ▾  │  总价 $X   提交   更多 ▾  (center) │
 *   └──────────────┴──────────────┴────────────────────────────────────┘
 *
 * Active BUY/SELL + LIMIT/MARKET fill with the brand color (project
 * theme), not buy-green / sell-red. Submit is always primary-themed
 * (filled light-green background) regardless of side. */
export function QuickOrderRow({ symbol, presets, lastDone, onSubmit, onMore }: Props) {
  const [side, setSide] = useState<"BUY" | "SELL">("BUY");
  const [orderType, setOrderType] = useState<"LIMIT" | "MARKET">("LIMIT");
  const [price, setPrice] = useState<string>(lastDone != null ? lastDone.toFixed(2) : "");
  const [qty, setQty] = useState<string>(String(presets.regular));
  const [presetsOpen, setPresetsOpen] = useState(false);
  const qtyMenuRef = useRef<HTMLDivElement | null>(null);

  // Sync price input with the live quote when in LIMIT mode.
  useEffect(() => {
    if (orderType === "LIMIT" && lastDone != null) setPrice(lastDone.toFixed(2));
  }, [lastDone, orderType]);

  // Outside-click closes the qty preset menu.
  useEffect(() => {
    if (!presetsOpen) return;
    const onDoc = (e: MouseEvent) => {
      if (qtyMenuRef.current && !qtyMenuRef.current.contains(e.target as Node)) {
        setPresetsOpen(false);
      }
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [presetsOpen]);

  const submit = () => {
    const p = orderType === "LIMIT" ? parseFloat(price) : null;
    const q = parseInt(qty, 10);
    if (!q || q <= 0) return;
    if (orderType === "LIMIT" && (!p || p <= 0)) return;
    onSubmit({
      symbol, side, order_type: orderType, price: p, qty: q,
      time_in_force: "Day", note: null,
    });
  };

  const totalStr = (() => {
    const p = orderType === "LIMIT" ? parseFloat(price) : (lastDone ?? 0);
    const q = parseInt(qty, 10) || 0;
    return p && q
      ? `$${(p * q).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
      : "—";
  })();

  const canSubmit = (() => {
    const q = parseInt(qty, 10);
    if (!q || q <= 0) return false;
    if (orderType === "MARKET") return true;
    const p = parseFloat(price);
    return !!(p && p > 0);
  })();

  return (
    <div className="quick-order">
      {/* Column 1 — stacked toggles */}
      <div className="qo-toggles">
        <div className="qo-seg">
          <button
            type="button"
            className={`qo-seg-btn ${side === "BUY" ? "active" : ""}`}
            onClick={() => setSide("BUY")}
          >BUY</button>
          <button
            type="button"
            className={`qo-seg-btn ${side === "SELL" ? "active" : ""}`}
            onClick={() => setSide("SELL")}
          >SELL</button>
        </div>
        <div className="qo-seg">
          <button
            type="button"
            className={`qo-seg-btn ${orderType === "LIMIT" ? "active" : ""}`}
            onClick={() => setOrderType("LIMIT")}
          >LIMIT</button>
          <button
            type="button"
            className={`qo-seg-btn ${orderType === "MARKET" ? "active" : ""}`}
            onClick={() => setOrderType("MARKET")}
          >MARKET</button>
        </div>
      </div>

      {/* Column 2 — labeled inputs */}
      <div className="qo-fields">
        <div className="qo-field">
          <span className="qo-k">价</span>
          <input
            aria-label="价"
            className="qo-input"
            type="text"
            value={price}
            disabled={orderType === "MARKET"}
            onChange={(e) => setPrice(e.target.value)}
            placeholder={orderType === "MARKET" ? "市价" : ""}
          />
        </div>
        <div className="qo-field">
          <span className="qo-k">数</span>
          <input
            aria-label="数"
            className="qo-input qo-input-qty"
            type="text"
            value={qty}
            onChange={(e) => setQty(e.target.value)}
          />
          <div className="qo-qty-menu-wrap" ref={qtyMenuRef}>
            <button
              type="button"
              className="qo-qty-caret"
              aria-label="数量预设"
              onClick={() => setPresetsOpen((o) => !o)}
            >
              <svg width="9" height="9" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round">
                <polyline points="6 9 12 15 18 9" />
              </svg>
            </button>
            {presetsOpen && (
              <div className="qo-qty-menu" role="menu">
                <button type="button" onClick={() => { setQty(String(presets.regular)); setPresetsOpen(false); }}>常规 {presets.regular}</button>
                <button type="button" onClick={() => { setQty(String(presets.half)); setPresetsOpen(false); }}>半仓 {presets.half}</button>
                <button type="button" onClick={() => { setQty(String(presets.third)); setPresetsOpen(false); }}>1/3 {presets.third}</button>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Column 3 — centered action group */}
      <div className="qo-actions">
        <span className="qo-total">
          <span className="qo-total-k">总价</span>
          <span className="qo-total-v">{totalStr}</span>
        </span>
        <button
          type="button"
          className="qo-submit"
          onClick={submit}
          disabled={!canSubmit}
        >提交</button>
        <button
          type="button"
          className="qo-more"
          onClick={onMore}
        >
          <span>更多</span>
          <svg width="9" height="9" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round">
            <polyline points="6 9 12 15 18 9" />
          </svg>
        </button>
      </div>
    </div>
  );
}
