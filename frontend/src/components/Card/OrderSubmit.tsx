import type { Instruction } from "../../api/domain-types";

export interface OrderSubmitProps {
  instruction: Instruction;
  orderId: string;
  delta?: number | null; // stage_timings.submit in ms
}

export function OrderSubmit({ instruction, orderId, delta }: OrderSubmitProps) {
  const side = instruction.instruction_type?.toUpperCase() ?? "—";
  const price = instruction.price != null ? `$${instruction.price.toFixed(2)}` : "—";
  const qty = instruction.quantity ?? "—";
  const total =
    instruction.price != null && instruction.quantity != null
      ? `$${(instruction.price * instruction.quantity).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
      : "—";

  return (
    <div className="stage done order-submit">
      <div className="stage-marker" />
      <div className="stage-body">
        <strong>提交订单</strong>
        <div className="order-summary">
          <span className="order-tag">
            <span className="k">SIDE</span>
            <span className="v">{side.includes("BUY") || instruction.instruction_type === "buy" ? "BUY" : "SELL"}</span>
          </span>
          <span className="order-tag">
            <span className="k">TYPE</span>
            <span className="v">LIMIT</span>
          </span>
          <span className="order-tag">
            <span className="k">PRICE</span>
            <span className="v">{price}</span>
          </span>
          <span className="order-tag">
            <span className="k">QTY</span>
            <span className="v">{String(qty)}</span>
          </span>
          <span className="order-tag">
            <span className="k">TOTAL</span>
            <span className="v">{total}</span>
          </span>
        </div>
        <div className="order-id-row">
          <span className="k">order_id</span>
          <span className="v">{orderId}</span>
        </div>
      </div>
      <div className="stage-delta">
        {delta != null ? `+${delta}ms` : "—"}
      </div>
    </div>
  );
}
