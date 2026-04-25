import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { RightRail } from "./RightRail";

describe("RightRail", () => {
  it("shows three section titles", () => {
    render(<RightRail />);
    expect(screen.getByText(/今日/)).toBeInTheDocument();
    expect(screen.getByText(/正股持仓/)).toBeInTheDocument();
    expect(screen.getByText(/期权持仓/)).toBeInTheDocument();
  });
});
