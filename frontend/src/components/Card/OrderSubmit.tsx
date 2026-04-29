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
  /** Broker last_done at decision (shown for PRICE when MARKET). */
  submitQuoteLastDone?: number | null;
  /** Precomputed UTC clock string for right column (HH:MM:SS.mmm). */
  wallClockAtSubmitEnd?: string;
}

export function OrderSubmit({
  instruction,
  orderId,
  delta,
  error,
  submitOrderType,
  submitOrderContext,
  submitQuoteLastDone,
  wallClockAtSubmitEnd,
}: OrderSubmitProps) {
  const side = instruction.instruction_type?.toUpperCase() ?? "—";
  const isMarket = submitOrderType === "MARKET";
  const ref = submitQuoteLastDone;
  const price =
    isMarket && ref != null && Number.isFinite(ref)
      ? `市价 @$${ref.toFixed(3)}`
      : instruction.price != null
        ? `$${instruction.price.toFixed(3)}`
        : "—";
  const qty = instruction.quantity ?? "—";
  const priceForTotal =
    isMarket && ref != null && Number.isFinite(ref) ? ref : instruction.price ?? null;
  const total =
    priceForTotal != null && instruction.quantity != null
      ? `$${(priceForTotal * instruction.quantity).toLocaleString("en-US", {
          minimumFractionDigits: 2,
          maximumFractionDigits: 2,
        })}`
      : "—";

  const failed = !!error || !orderId;
  const stageClass = failed ? "stage err order-submit" : "stage done order-submit";
  const typeLabel = submitOrderType ?? "—";
  const submitTiming =
    delta != null ? (
      <span className={`stage-title-timing${delta > 500 ? " slow" : ""}`}>
        [+{delta.toFixed(3)}ms]
      </span>
    ) : null;
  const rightClock = wallClockAtSubmitEnd && wallClockAtSubmitEnd !== "—" ? wallClockAtSubmitEnd : "—";

  return (
    <div className={stageClass}>
      <div className="stage-marker" />
      <div className="stage-body">
        <div className="stage-title-line">
          <span>
            <strong>提交订单</strong>
            {submitTiming}
          </span>
        </div>
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
      <div className="stage-delta stage-delta-clock">{rightClock}</div>
    </div>
  );
}
