import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { TypeBadge } from "./TypeBadge";

describe("TypeBadge", () => {
  it('stock type renders "正股" with .type-badge.stock class', () => {
    const { container } = render(<TypeBadge type="stock" />);
    expect(screen.getByText("正股")).toBeInTheDocument();
    expect(container.querySelector(".type-badge.stock")).toBeInTheDocument();
  });

  it('option type renders "期权" with .type-badge.option class', () => {
    const { container } = render(<TypeBadge type="option" />);
    expect(screen.getByText("期权")).toBeInTheDocument();
    expect(container.querySelector(".type-badge.option")).toBeInTheDocument();
  });
});
