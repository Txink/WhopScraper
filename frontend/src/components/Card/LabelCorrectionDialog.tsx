import { useState } from "react";
import type { SyntheticEvent } from "react";
import type { Instruction, CorrectedInstruction } from "../../api/domain-types";
import "./LabelActions.css";

type Action = "BUY" | "SELL" | "CLOSE" | "MODIFY";
type CType = "stock" | "option";
type OptType = "CALL" | "PUT";

interface Props {
  variant: "stock" | "option";
  instruction: Instruction | null;
  existing: CorrectedInstruction | null;
  onSubmit(payload: CorrectedInstruction): void;
  onClose(): void;
}

const ACTIONS: Action[] = ["BUY", "SELL", "CLOSE", "MODIFY"];

function str(v: number | null | undefined): string {
  return v == null ? "" : String(v);
}
function numOrNull(s: string): number | null {
  const t = s.trim();
  if (t === "") return null;
  const n = Number(t);
  return Number.isFinite(n) ? n : null;
}

export function LabelCorrectionDialog({ variant, instruction, existing, onSubmit, onClose }: Props) {
  const seedType: CType = (existing?.type ?? (variant === "option" ? "option" : "stock"));
  const [type, setType] = useState<CType>(seedType);
  const [ticker, setTicker] = useState(existing?.ticker ?? instruction?.ticker ?? "");
  const [price, setPrice] = useState(str(existing?.price ?? instruction?.price));
  const [quantity, setQuantity] = useState(str(existing?.quantity ?? instruction?.quantity));
  const [action, setAction] = useState<Action>(
    (existing?.action ?? (instruction?.instruction_type as Action) ?? "BUY"),
  );
  const [strike, setStrike] = useState(str(existing?.strike ?? instruction?.strike));
  const [expiry, setExpiry] = useState(existing?.expiry ?? instruction?.expiry ?? "");
  const [optionType, setOptionType] = useState<OptType>(
    (existing?.option_type
      ?? ((instruction?.option_type as string)?.toUpperCase() as OptType)
      ?? "CALL"),
  );

  const submit = () => {
    const payload: CorrectedInstruction = {
      type, action,
      ticker: ticker.trim() || null,
      price: numOrNull(price),
      quantity: numOrNull(quantity),
      strike: type === "option" ? numOrNull(strike) : null,
      expiry: type === "option" ? (expiry.trim() || null) : null,
      option_type: type === "option" ? optionType : null,
    };
    onSubmit(payload);
  };

  const stop = (e: SyntheticEvent) => e.stopPropagation();

  return (
    <div className="label-dialog-backdrop" onClick={onClose}>
      <div className="label-dialog" role="dialog" aria-label="校正解析结果"
           onClick={stop} onKeyDown={stop}>
        <div className="label-dialog-title">校正解析结果</div>

        <label className="label-field">
          <span>type</span>
          <select aria-label="type" value={type}
                  onChange={(e) => setType(e.target.value as CType)}>
            <option value="stock">stock</option>
            <option value="option">option</option>
          </select>
        </label>

        <label className="label-field">
          <span>ticker</span>
          <input aria-label="ticker" value={ticker}
                 onChange={(e) => setTicker(e.target.value)} />
        </label>

        <label className="label-field">
          <span>action</span>
          <select aria-label="action" value={action}
                  onChange={(e) => setAction(e.target.value as Action)}>
            {ACTIONS.map((a) => <option key={a} value={a}>{a}</option>)}
          </select>
        </label>

        <label className="label-field">
          <span>price</span>
          <input aria-label="price" inputMode="decimal" value={price}
                 onChange={(e) => setPrice(e.target.value)} />
        </label>

        <label className="label-field">
          <span>quantity</span>
          <input aria-label="quantity" inputMode="numeric" value={quantity}
                 onChange={(e) => setQuantity(e.target.value)} />
        </label>

        {type === "option" && (
          <>
            <label className="label-field">
              <span>strike</span>
              <input aria-label="strike" inputMode="decimal" value={strike}
                     onChange={(e) => setStrike(e.target.value)} />
            </label>
            <label className="label-field">
              <span>expiry</span>
              <input aria-label="expiry" placeholder="YYYY-MM-DD" value={expiry}
                     onChange={(e) => setExpiry(e.target.value)} />
            </label>
            <label className="label-field">
              <span>option_type</span>
              <select aria-label="option_type" value={optionType}
                      onChange={(e) => setOptionType(e.target.value as OptType)}>
                <option value="CALL">CALL</option>
                <option value="PUT">PUT</option>
              </select>
            </label>
          </>
        )}

        <div className="label-dialog-actions">
          <button type="button" className="label-btn-ghost" onClick={onClose}>取消</button>
          <button type="button" className="label-btn-primary" onClick={submit}>保存</button>
        </div>
      </div>
    </div>
  );
}
