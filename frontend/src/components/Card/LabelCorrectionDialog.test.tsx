import { render, fireEvent, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { LabelCorrectionDialog } from "./LabelCorrectionDialog";
import type { InstructionOut } from "../../api/domain-types";

const stockInst = {
  type: "stock", instruction_type: "BUY", ticker: "AAPL",
  price: 188, quantity: 50, price_range: null, position_size: null,
  stop_loss_price: null, take_profit_price: null, context_source: null,
  parser_notes: [], symbol: "AAPL.US",
} as unknown as InstructionOut;

describe("LabelCorrectionDialog", () => {
  it("prefills from instruction", () => {
    render(
      <LabelCorrectionDialog
        variant="stock" instruction={stockInst} existing={null}
        onSubmit={() => {}} onClose={() => {}}
      />,
    );
    expect((screen.getByLabelText("ticker") as HTMLInputElement).value).toBe("AAPL");
    expect((screen.getByLabelText("action") as HTMLSelectElement).value).toBe("BUY");
  });

  it("shows option fields only when type=option", () => {
    render(
      <LabelCorrectionDialog
        variant="option" instruction={null} existing={null}
        onSubmit={() => {}} onClose={() => {}}
      />,
    );
    expect(screen.queryByLabelText("strike")).not.toBeNull();
  });

  it("hides option fields for stock", () => {
    render(
      <LabelCorrectionDialog
        variant="stock" instruction={null} existing={null}
        onSubmit={() => {}} onClose={() => {}}
      />,
    );
    expect(screen.queryByLabelText("strike")).toBeNull();
  });

  it("submits a corrected_payload", () => {
    const onSubmit = vi.fn();
    render(
      <LabelCorrectionDialog
        variant="stock" instruction={stockInst} existing={null}
        onSubmit={onSubmit} onClose={() => {}}
      />,
    );
    fireEvent.click(screen.getByText("保存"));
    expect(onSubmit).toHaveBeenCalledWith(
      expect.objectContaining({ type: "stock", action: "BUY", ticker: "AAPL", quantity: 50 }),
    );
  });
});
