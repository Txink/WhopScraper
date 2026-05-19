import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { OptionQuantityEditor } from "./OptionQuantityEditor";

const baseValue = {
  option_buy_quantity_enabled: false,
  option_buy_quantity: null,
  option_total_price_limit_enabled: false,
  option_total_price_limit: null,
};

describe("OptionQuantityEditor", () => {
  it("renders both toggle rows", () => {
    render(<OptionQuantityEditor value={baseValue} onChange={() => {}} />);
    expect(screen.getByText(/启用期权购买张数/)).toBeInTheDocument();
    expect(screen.getByText(/启用期权总价上限/)).toBeInTheDocument();
  });

  it("qty input is disabled until its toggle is on", () => {
    const { container } = render(
      <OptionQuantityEditor value={baseValue} onChange={() => {}} />
    );
    const qtyInput = container.querySelector(
      'input[placeholder="期权购买张数"]'
    ) as HTMLInputElement;
    expect(qtyInput).toBeDisabled();
  });

  it("toggling buy_quantity_enabled fires onChange with the new bool", () => {
    const onChange = vi.fn();
    render(<OptionQuantityEditor value={baseValue} onChange={onChange} />);
    fireEvent.click(screen.getByText(/启用期权购买张数/));
    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({ option_buy_quantity_enabled: true })
    );
  });

  it("editing qty fires onChange with the parsed number", () => {
    const onChange = vi.fn();
    const enabledValue = { ...baseValue, option_buy_quantity_enabled: true };
    const { container } = render(
      <OptionQuantityEditor value={enabledValue} onChange={onChange} />
    );
    const qtyInput = container.querySelector(
      'input[placeholder="期权购买张数"]'
    )!;
    fireEvent.change(qtyInput, { target: { value: "5" } });
    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({ option_buy_quantity: 5 })
    );
  });

  it("clearing qty fires onChange with null", () => {
    const onChange = vi.fn();
    const enabledValue = {
      ...baseValue,
      option_buy_quantity_enabled: true,
      option_buy_quantity: 5,
    };
    const { container } = render(
      <OptionQuantityEditor value={enabledValue} onChange={onChange} />
    );
    const qtyInput = container.querySelector(
      'input[placeholder="期权购买张数"]'
    )!;
    fireEvent.change(qtyInput, { target: { value: "" } });
    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({ option_buy_quantity: null })
    );
  });

  it("disabled prop disables all interactive elements", () => {
    const { container } = render(
      <OptionQuantityEditor value={baseValue} onChange={() => {}} disabled />
    );
    const checkboxes = container.querySelectorAll('input[type="checkbox"]');
    checkboxes.forEach((cb) => expect(cb).toBeDisabled());
  });
});
