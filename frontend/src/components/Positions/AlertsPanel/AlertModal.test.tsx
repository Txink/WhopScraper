import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { AlertModal } from "./AlertModal";

describe("AlertModal", () => {
  it("switching to pct_change shows baseline picker", async () => {
    render(<AlertModal ticker="AAPL" symbol="AAPL.US" onSubmit={() => {}} onClose={() => {}} />);
    await userEvent.click(screen.getByRole("button", { name: /涨跌幅/ }));
    expect(screen.getAllByText(/今开|昨收/).length).toBeGreaterThan(0);
  });
  it("submit posts price create payload", async () => {
    const onSubmit = vi.fn();
    render(<AlertModal ticker="AAPL" symbol="AAPL.US" onSubmit={onSubmit} onClose={() => {}} />);
    await userEvent.click(screen.getByRole("button", { name: /创建告警/ }));
    expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({
      ticker: "AAPL", symbol: "AAPL.US", condition_type: "price",
    }));
  });
});
