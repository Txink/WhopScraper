import type { Instruction } from "../../api/domain-types";

export interface OrderSubmitProps {
  instruction: Instruction;
  /** Broker-assigned order_id when the submit succeeded. Null/undefined
   *  when the submit raised synchronously (status=SUBMIT_FAILED) — in
   *  that case ``error`` carries the broker's exception message. */
  orderId?: string | null;
  delta?: number | null; // stage_timings.submit in ms
  /** Synchronous broker error captured by trader.mark_submit_failed.
   *  Present iff orderId is null (SUBMIT_FAILED state). */
  error?: string | null;
  /** ``LIMIT`` | ``MARKET`` — from backend after auto-trade decision. */
  submitOrderType?: string | null;
  /** Backend rationale (Chinese), e.g. quote vs signal price. */
  submitOrderContext?: string | null;
}

export function OrderSubmit({
  instruction,
  orderId,
  delta,
  error,
  submitOrderType,
  submitOrderContext,
}: OrderSubmitProps) {
  const side = instruction.instruction_type?.toUpperCase() ?? "—";
  const price = instruction.price != null ? `$${instruction.price.toFixed(2)}` : "—";
  const qty = instruction.quantity ?? "—";
  const total =
    instruction.price != null && instruction.quantity != null
      ? `$${(instruction.price * instruction.quantity).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
      : "—";

  const failed = !!error || !orderId;
  const stageClass = failed ? "stage err order-submit" : "stage done order-submit";
  const typeLabel = submitOrderType ?? "—";

  return (
    <div className={stageClass}>
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
            <span className="v">{typeLabel}</span>
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
        {submitOrderContext ? (
          <div className="order-type-context" title={submitOrderContext}>
            {submitOrderContext}
          </div>
        ) : null}
        {failed ? (
          <div className="order-error-row">
            <span className="k">submit error</span>
            <span className="v" title={error ?? ""}>{error ?? "未知错误"}</span>
          </div>
        ) : (
          <div className="order-id-row">
            <span className="k">order_id</span>
            <span className="v">{orderId}</span>
          </div>
        )}
      </div>
      <div className="stage-delta">
        {delta != null ? `+${delta}ms` : "—"}
      </div>
    </div>
  );
}
