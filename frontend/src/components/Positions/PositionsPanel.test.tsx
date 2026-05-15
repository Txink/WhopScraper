import { describe, it, expect, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { PositionsPanel } from "./PositionsPanel";
import { usePositionsStore } from "../../stores/positions";
import { useDetailViewStore } from "../../stores/detailView";

describe("PositionsPanel", () => {
  beforeEach(() => {
    usePositionsStore.setState({ stocks: [], options: [] });
    useDetailViewStore.getState().selectSymbol(null);
  });

  it("renders both tabs with counts", () => {
    usePositionsStore.getState().setAll({
      stocks: [
        { symbol: "TSLA.US", type: "stock", ticker: "TSLA", quantity: 100, avg_cost: 240 },
      ],
      options: [
        {
          symbol: "TSLA 240620 250C",
          type: "option",
          ticker: "TSLA",
          quantity: 5,
          avg_cost: 6.4,
          option_strike: 250,
          option_expiry: "2024-06-20",
          option_type: "CALL",
        },
        {
          symbol: "AAPL 240920 200P",
          type: "option",
          ticker: "AAPL",
          quantity: 2,
          avg_cost: 3.2,
          option_strike: 200,
          option_expiry: "2024-09-20",
          option_type: "PUT",
        },
      ],
    });

    render(<PositionsPanel />);
    const stocksTab = screen.getByRole("tab", { name: /正股/ });
    const optionsTab = screen.getByRole("tab", { name: /期权/ });
    expect(stocksTab).toHaveAttribute("aria-selected", "true");
    expect(stocksTab.textContent).toContain("1");
    expect(optionsTab.textContent).toContain("2");
  });

  it("switches to options view when 期权 tab is clicked", () => {
    usePositionsStore.getState().setAll({
      stocks: [
        { symbol: "TSLA.US", type: "stock", ticker: "TSLA", quantity: 100, avg_cost: 240 },
      ],
      options: [
        {
          symbol: "AAPL 240920 200P",
          type: "option",
          ticker: "AAPL",
          quantity: 2,
          avg_cost: 3.2,
          option_strike: 200,
          option_expiry: "2024-09-20",
          option_type: "PUT",
        },
      ],
    });

    render(<PositionsPanel />);
    // initial: stocks view
    expect(screen.queryByText("AAPL")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("tab", { name: /期权/ }));
    expect(screen.getByText("AAPL")).toBeInTheDocument();
    expect(screen.getByText("P")).toBeInTheDocument();
    // Strike is rendered as integer (no decimals) per user spec — option
    // strikes in real Longbridge data are always whole dollars.
    expect(screen.getByText("200")).toBeInTheDocument();
  });

  it("shows option-specific empty state when no options held", () => {
    usePositionsStore.getState().setAll({
      stocks: [
        { symbol: "TSLA.US", type: "stock", ticker: "TSLA", quantity: 100, avg_cost: 240 },
      ],
      options: [],
    });

    render(<PositionsPanel />);
    fireEvent.click(screen.getByRole("tab", { name: /期权/ }));
    expect(screen.getByText("暂无期权持仓")).toBeInTheDocument();
  });

  it("shows stock-specific empty state when no stocks held", () => {
    usePositionsStore.getState().setAll({ stocks: [], options: [] });

    render(<PositionsPanel />);
    expect(screen.getByText("暂无正股持仓")).toBeInTheDocument();
  });
});
