import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QuickOrderRow } from "./QuickOrderRow";

describe("QuickOrderRow", () => {
  it("toggling MKT disables price input", async () => {
    render(<QuickOrderRow symbol="AAPL.US" ticker="AAPL" presets={{ regular: 200, half: 100, third: 67 }} lastDone={199.0} onSubmit={() => {}} onMore={() => {}} />);
    await userEvent.click(screen.getByRole("button", { name: "MKT" }));
    expect(screen.getByLabelText("价")).toBeDisabled();
  });
  it("submit calls onSubmit with form state", async () => {
    const onSubmit = vi.fn();
    render(<QuickOrderRow symbol="AAPL.US" ticker="AAPL" presets={{ regular: 200, half: 100, third: 67 }} lastDone={199.0} onSubmit={onSubmit} onMore={() => {}} />);
    await userEvent.click(screen.getByRole("button", { name: "提交" }));
    expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({
      symbol: "AAPL.US", side: "BUY", order_type: "LIMIT", qty: 200, price: 199.0,
    }));
  });
  it("preset chip fills quantity", async () => {
    render(<QuickOrderRow symbol="AAPL.US" ticker="AAPL" presets={{ regular: 200, half: 100, third: 67 }} lastDone={199.0} onSubmit={() => {}} onMore={() => {}} />);
    await userEvent.click(screen.getByRole("button", { name: /数/ }));  // open dropdown
    await userEvent.click(screen.getByRole("button", { name: /半仓/ }));
    expect((screen.getByLabelText("数") as HTMLInputElement).value).toBe("100");
  });
});
