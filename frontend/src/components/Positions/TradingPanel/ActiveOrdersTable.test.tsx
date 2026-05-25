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
    expect(screen.getByText("BUY")).toBeInTheDocument();
    expect(screen.getByText("LIMIT")).toBeInTheDocument();
  });

  it("committing a new price calls onReplace with {price}", async () => {
    const onReplace = vi.fn();
    render(<ActiveOrdersTable orders={[row()]} onReplace={onReplace} onCancel={() => {}} />);
    const priceInput = screen.getByLabelText(/^价格/) as HTMLInputElement;
    await userEvent.clear(priceInput);
    await userEvent.type(priceInput, "199.50");
    priceInput.blur();
    expect(onReplace).toHaveBeenCalledWith(
      expect.objectContaining({ order_id: "ord-1" }),
      { price: 199.5 },
    );
  });

  it("committing a new qty calls onReplace with {qty}", async () => {
    const onReplace = vi.fn();
    render(<ActiveOrdersTable orders={[row()]} onReplace={onReplace} onCancel={() => {}} />);
    const qtyInput = screen.getByLabelText(/^数量/) as HTMLInputElement;
    await userEvent.clear(qtyInput);
    await userEvent.type(qtyInput, "300");
    qtyInput.blur();
    expect(onReplace).toHaveBeenCalledWith(
      expect.objectContaining({ order_id: "ord-1" }),
      { qty: 300 },
    );
  });

  it("Escape reverts an in-flight edit without calling onReplace", async () => {
    const onReplace = vi.fn();
    render(<ActiveOrdersTable orders={[row()]} onReplace={onReplace} onCancel={() => {}} />);
    const qtyInput = screen.getByLabelText(/^数量/) as HTMLInputElement;
    await userEvent.clear(qtyInput);
    await userEvent.type(qtyInput, "999");
    await userEvent.keyboard("{Escape}");
    expect(onReplace).not.toHaveBeenCalled();
    expect(qtyInput.value).toBe("200");
  });

  it("disables inputs and 撤 button for filled orders", () => {
    render(<ActiveOrdersTable orders={[row({ status: "FilledStatus", filled_qty: 200 })]} onReplace={() => {}} onCancel={() => {}} />);
    expect(screen.queryByLabelText(/^价格/)).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/^数量/)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "撤" })).toBeDisabled();
  });

  it("does not render a 改 button", () => {
    render(<ActiveOrdersTable orders={[row()]} onReplace={() => {}} onCancel={() => {}} />);
    expect(screen.queryByRole("button", { name: "改" })).not.toBeInTheDocument();
  });

  it("dedupes by order_id keeping the last entry (defense against backend leaks)", () => {
    render(
      <ActiveOrdersTable
        orders={[
          row({ order_id: "X", status: "SUBMITTING", submitted_at: "2026-05-25T10:00:00Z" }),
          row({ order_id: "X", status: "NotReported", submitted_at: "2026-05-25T10:00:00Z" }),
          row({ order_id: "Y", status: "Canceled", submitted_at: "2026-05-25T09:00:00Z" }),
        ]}
        onReplace={() => {}}
        onCancel={() => {}}
      />,
    );
    expect(screen.queryByText("SUBMITTING")).not.toBeInTheDocument();
    expect(screen.getByText("NotReported")).toBeInTheDocument();
    expect(screen.getByText("Canceled")).toBeInTheDocument();
  });

  it("sorts visible rows by submitted_at descending (newest first)", () => {
    render(
      <ActiveOrdersTable
        orders={[
          row({ order_id: "old", submitted_at: "2026-05-25T09:00:00Z", status: "S1" }),
          row({ order_id: "new", submitted_at: "2026-05-25T11:00:00Z", status: "S2" }),
          row({ order_id: "mid", submitted_at: "2026-05-25T10:00:00Z", status: "S3" }),
        ]}
        onReplace={() => {}}
        onCancel={() => {}}
      />,
    );
    const statusCells = screen.getAllByText(/^S[123]$/).map((n) => n.textContent);
    expect(statusCells).toEqual(["S2", "S3", "S1"]);
  });

  it("activeOnly filter hides terminal-status rows", () => {
    render(<ActiveOrdersTable orders={[
      row({ order_id: "a", status: "NewStatus" }),
      row({ order_id: "b", status: "FilledStatus", filled_qty: 200 }),
    ]} activeOnly onReplace={() => {}} onCancel={() => {}} />);
    expect(screen.queryByText(/ord-b/)).not.toBeInTheDocument();
  });

  // status reaches the FE in three spellings depending on origin:
  //   "OrderStatus.Canceled" (raw LongPort SDK enum), "Canceled" (post-
  //   prefix-strip), and "CANCELLED" (our Python Status StrEnum, UK
  //   double-L). All three must be treated as terminal — the modify UI
  //   should be hidden and the cancel button disabled.
  it.each([
    ["LongPort raw", "OrderStatus.Canceled"],
    ["LongPort stripped", "Canceled"],
    ["our enum", "CANCELLED"],
  ])("treats cancelled status (%s) as terminal", (_label, status) => {
    render(<ActiveOrdersTable orders={[row({ status })]} onReplace={() => {}} onCancel={() => {}} />);
    expect(screen.queryByLabelText(/^价格/)).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/^数量/)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "撤" })).toBeDisabled();
  });

  // Orders whose cancel is already in flight (WaitToCancel / PendingCancel)
  // aren't terminal yet — they remain visible in the active list — but
  // the user must not be able to fire a second cancel or a modify on top
  // of the racing broker request. EditableNumCell collapses to a plain
  // span when disabled, so the assertion matches the "filled" case.
  it.each([
    ["WaitToCancel raw", "OrderStatus.WaitToCancel"],
    ["PendingCancel raw", "OrderStatus.PendingCancel"],
  ])("locks row actions for in-flight cancel (%s)", (_label, status) => {
    render(<ActiveOrdersTable orders={[row({ status })]} onReplace={() => {}} onCancel={() => {}} />);
    expect(screen.queryByLabelText(/^价格/)).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/^数量/)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "撤" })).toBeDisabled();
  });

  // The "仅活跃" toggle hides only true terminal orders. An in-flight
  // cancel is still on the broker's book and should remain visible so
  // the user can see "yes, my cancel is processing" — only its action
  // controls are locked. The status cell's text is the per-row marker
  // available in the rendered output.
  it("activeOnly keeps in-flight-cancel rows visible (they aren't terminal yet)", () => {
    render(<ActiveOrdersTable orders={[
      row({ order_id: "a", status: "OrderStatus.WaitToCancel" }),
      row({ order_id: "b", status: "OrderStatus.Canceled" }),
    ]} activeOnly onReplace={() => {}} onCancel={() => {}} />);
    expect(screen.getByText("WaitToCancel")).toBeInTheDocument();
    expect(screen.queryByText("Canceled")).not.toBeInTheDocument();
  });
});
