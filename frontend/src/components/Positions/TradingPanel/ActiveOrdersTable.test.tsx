import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ActiveOrdersTable } from "./ActiveOrdersTable";
import type { OrderOut } from "../../../api/orders";

const row = (overrides: Partial<OrderOut> = {}): OrderOut => ({
  order_id: "ord-1", task_id: null, ticker: "AAPL", symbol: "AAPL.US",
  side: "BUY", order_type: "LIMIT", price: 199, qty: 200, filled_qty: 0,
  status: "NewStatus", source: "manual",
  submitted_at: "2026-05-25T10:00:00Z", last_replaced_at: null,
  ...overrides,
});

describe("ActiveOrdersTable", () => {
  it("renders rows", () => {
    render(<ActiveOrdersTable orders={[row()]} onReplace={() => {}} onCancel={() => {}} />);
    expect(screen.getByText("AAPL")).toBeInTheDocument();
  });
  it("calls onReplace with order when 改 clicked", async () => {
    const onReplace = vi.fn();
    render(<ActiveOrdersTable orders={[row()]} onReplace={onReplace} onCancel={() => {}} />);
    await userEvent.click(screen.getByRole("button", { name: "改" }));
    expect(onReplace).toHaveBeenCalledWith(expect.objectContaining({ order_id: "ord-1" }));
  });
  it("disables 改/撤 for filled orders", () => {
    render(<ActiveOrdersTable orders={[row({ status: "FilledStatus", filled_qty: 200 })]} onReplace={() => {}} onCancel={() => {}} />);
    expect(screen.getByRole("button", { name: "改" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "撤" })).toBeDisabled();
  });
  it("activeOnly filter hides terminal-status rows", () => {
    render(<ActiveOrdersTable orders={[
      row({ order_id: "a", status: "NewStatus" }),
      row({ order_id: "b", status: "FilledStatus", filled_qty: 200 }),
    ]} activeOnly onReplace={() => {}} onCancel={() => {}} />);
    expect(screen.queryByText(/ord-b/)).not.toBeInTheDocument();
  });
});
