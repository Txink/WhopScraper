import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QuickOrderRow } from "./QuickOrderRow";

describe("QuickOrderRow", () => {
  it("toggling MARKET disables price input", async () => {
    render(<QuickOrderRow symbol="AAPL.US" ticker="AAPL" presets={{ regular: 200, half: 100, third: 67 }} lastDone={199.0} onSubmit={() => {}} onMore={() => {}} />);
    await userEvent.click(screen.getByRole("button", { name: "MARKET" }));
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

  it("preset menu fills quantity from a chip", async () => {
    render(<QuickOrderRow symbol="AAPL.US" ticker="AAPL" presets={{ regular: 200, half: 100, third: 67 }} lastDone={199.0} onSubmit={() => {}} onMore={() => {}} />);
    await userEvent.click(screen.getByRole("button", { name: "数量预设" }));
    await userEvent.click(screen.getByRole("button", { name: /半仓/ }));
    expect((screen.getByLabelText("数") as HTMLInputElement).value).toBe("100");
  });

  it("submit button is disabled when qty is invalid", () => {
    render(<QuickOrderRow symbol="AAPL.US" ticker="AAPL" presets={{ regular: 0, half: 0, third: 0 }} lastDone={199.0} onSubmit={() => {}} onMore={() => {}} />);
    expect(screen.getByRole("button", { name: "提交" })).toBeDisabled();
  });

  it("BUY/SELL toggle reflects active state via .active class", async () => {
    render(<QuickOrderRow symbol="AAPL.US" ticker="AAPL" presets={{ regular: 200, half: 100, third: 67 }} lastDone={199.0} onSubmit={() => {}} onMore={() => {}} />);
    const sell = screen.getByRole("button", { name: "SELL" });
    expect(sell.className).not.toMatch(/active/);
    await userEvent.click(sell);
    expect(sell.className).toMatch(/active/);
  });
});
