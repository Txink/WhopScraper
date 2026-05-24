import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ReplaceOrderPopover } from "./ReplaceOrderPopover";
import type { OrderOut } from "../../../api/orders";

const order: OrderOut = {
  order_id: "ord-1", task_id: null, ticker: "AAPL", symbol: "AAPL.US",
  side: "BUY", order_type: "LIMIT", price: 199.0,
  qty: 200, filled_qty: 0, status: "New", source: "manual",
  submitted_at: null, last_replaced_at: null,
};

describe("ReplaceOrderPopover", () => {
  it("submitting requires at least one changed field", async () => {
    const onSubmit = vi.fn();
    render(<ReplaceOrderPopover order={order} onSubmit={onSubmit} onClose={() => {}} />);
    await userEvent.click(screen.getByRole("button", { name: "确认" }));
    expect(onSubmit).not.toHaveBeenCalled();
  });
  it("submits price change only", async () => {
    const onSubmit = vi.fn();
    render(<ReplaceOrderPopover order={order} onSubmit={onSubmit} onClose={() => {}} />);
    const priceInput = screen.getByLabelText("价") as HTMLInputElement;
    await userEvent.clear(priceInput);
    await userEvent.type(priceInput, "199.50");
    await userEvent.click(screen.getByRole("button", { name: "确认" }));
    expect(onSubmit).toHaveBeenCalledWith({ price: 199.5, qty: null });
  });
});
