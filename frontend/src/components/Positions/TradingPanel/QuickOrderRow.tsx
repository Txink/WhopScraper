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

/** Single-row LIMIT-only quick-order form:
 *
 *   [BUY  SELL]   价 [___]   数 [___]▾   总价 $X   提交   更多 ▾
 *
 * Active BUY/SELL fills with the brand color (project theme), not
 * buy-green / sell-red. Submit is always primary-themed (filled
 * light-green background) regardless of side. MARKET + advanced
 * options live in the FullOrderModal (更多 ▾). */
export function QuickOrderRow({ symbol, presets, lastDone, onSubmit, onMore }: Props) {
  const [side, setSide] = useState<"BUY" | "SELL">("BUY");
  // Quick-order is LIMIT-only by design — MARKET (and other advanced
  // order types / TIFs) live in the FullOrderModal.
  const orderType = "LIMIT" as const;
  const [price, setPrice] = useState<string>(lastDone != null ? lastDone.toFixed(2) : "");
  const [qty, setQty] = useState<string>(String(presets.regular));
  const [presetsOpen, setPresetsOpen] = useState(false);
  const qtyMenuRef = useRef<HTMLDivElement | null>(null);

  // Sync price input with the live quote.
  useEffect(() => {
    if (lastDone != null) setPrice(lastDone.toFixed(2));
  }, [lastDone]);

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
    const p = parseFloat(price);
    const q = parseInt(qty, 10);
    if (!q || q <= 0 || !p || p <= 0) return;
    onSubmit({
      symbol, side, order_type: orderType, price: p, qty: q,
      time_in_force: "Day", note: null,
    });
  };

  const totalStr = (() => {
    const p = parseFloat(price);
    const q = parseInt(qty, 10) || 0;
    return p && q
      ? `$${(p * q).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
      : "—";
  })();

  const canSubmit = (() => {
    const q = parseInt(qty, 10);
    if (!q || q <= 0) return false;
    const p = parseFloat(price);
    return !!(p && p > 0);
  })();

  return (
    <div className="quick-order">
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

      <div className="qo-field">
        <span className="qo-k">价</span>
        <input
          aria-label="价"
          className="qo-input"
          type="text"
          value={price}
          onChange={(e) => setPrice(e.target.value)}
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
              <button type="button" onClick={() => { setQty(String(presets.regular)); setPresetsOpen(false); }}>
                <span className="qo-qty-menu-k">常规</span>
                <span className="qo-qty-menu-v">{presets.regular}</span>
              </button>
              <button type="button" onClick={() => { setQty(String(presets.half)); setPresetsOpen(false); }}>
                <span className="qo-qty-menu-k">半仓</span>
                <span className="qo-qty-menu-v">{presets.half}</span>
              </button>
              <button type="button" onClick={() => { setQty(String(presets.third)); setPresetsOpen(false); }}>
                <span className="qo-qty-menu-k">1/3仓</span>
                <span className="qo-qty-menu-v">{presets.third}</span>
              </button>
            </div>
          )}
        </div>
      </div>

      <span className="qo-total">
        <span className="qo-total-k">总价</span>
        <span className="qo-total-v">{totalStr}</span>
      </span>

      <div className="qo-actions">
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
