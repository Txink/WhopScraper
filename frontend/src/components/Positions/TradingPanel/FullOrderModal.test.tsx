import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { FullOrderModal } from "./FullOrderModal";

describe("FullOrderModal", () => {
  it("renders TIF + notes + advanced fields", () => {
    render(<FullOrderModal symbol="AAPL.US" ticker="AAPL" lastDone={199} onSubmit={() => {}} onClose={() => {}} />);
    expect(screen.getByText(/TIF/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/备注/)).toBeInTheDocument();
  });
  it("submit fires onSubmit with full request", async () => {
    const onSubmit = vi.fn();
    render(<FullOrderModal symbol="AAPL.US" ticker="AAPL" lastDone={199} onSubmit={onSubmit} onClose={() => {}} />);
    await userEvent.click(screen.getByRole("button", { name: "提交订单" }));
    expect(onSubmit).toHaveBeenCalled();
  });
});
