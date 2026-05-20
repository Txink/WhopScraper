export interface OptionQtyValue {
  option_buy_quantity_enabled: boolean;
  option_buy_quantity: number | null;
  option_total_price_limit_enabled: boolean;
  option_total_price_limit: number | null;
}

interface Props {
  value: OptionQtyValue;
  onChange(next: OptionQtyValue): void;
  disabled?: boolean;
}

export function OptionQuantityEditor({ value, onChange, disabled }: Props) {
  return (
    <div className="option-qty-editor">
      <div className="option-rule-row">
        <label className="option-rule-toggle">
          <input
            type="checkbox"
            disabled={disabled}
            checked={value.option_buy_quantity_enabled}
            onChange={(e) =>
              onChange({ ...value, option_buy_quantity_enabled: e.target.checked })
            }
          />
          <span>启用期权购买张数</span>
        </label>
        <input
          type="number"
          min={1}
          step={1}
          disabled={disabled || !value.option_buy_quantity_enabled}
          value={value.option_buy_quantity ?? ""}
          placeholder="期权购买张数"
          className="option-rule-input"
          onChange={(e) => {
            const n = e.target.value === "" ? null : Number(e.target.value);
            onChange({ ...value, option_buy_quantity: n });
          }}
        />
        <p className="hint small option-rule-desc">固定按该张数下单</p>
      </div>

      <div className="option-rule-row">
        <label className="option-rule-toggle">
          <input
            type="checkbox"
            disabled={disabled}
            checked={value.option_total_price_limit_enabled}
            onChange={(e) =>
              onChange({ ...value, option_total_price_limit_enabled: e.target.checked })
            }
          />
          <span>启用期权总价上限（USD）</span>
        </label>
        <input
          type="number"
          min={0}
          step={0.01}
          disabled={disabled || !value.option_total_price_limit_enabled}
          value={value.option_total_price_limit ?? ""}
          placeholder="期权总价上限（USD）"
          className="option-rule-input"
          onChange={(e) => {
            const n = e.target.value === "" ? null : Number(e.target.value);
            onChange({ ...value, option_total_price_limit: n });
          }}
        />
        <p className="hint small option-rule-desc">按总价可覆盖的最大张数</p>
      </div>

      <p className="hint small">
        两项都不启用时，trader 会跳过下单并标记 SKIPPED；启用一项按该规则计算，启用两项按同时满足（取更小张数）计算。
      </p>
    </div>
  );
}
