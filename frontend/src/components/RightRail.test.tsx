import { describe, expect, it, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { RightRail } from "./RightRail";
import { useStatsStore } from "../stores/stats";
import { usePositionsStore } from "../stores/positions";

describe("RightRail", () => {
  beforeEach(() => {
    useStatsStore.setState({ stats: null });
    usePositionsStore.setState({ stocks: [], options: [] });
  });

  it("shows three section titles", () => {
    render(<RightRail />);
    expect(screen.getByText(/今日/)).toBeInTheDocument();
    expect(screen.getByText(/正股持仓/)).toBeInTheDocument();
    expect(screen.getByText(/期权持仓/)).toBeInTheDocument();
  });

  it("shows empty-state fallback when no data", () => {
    render(<RightRail />);
    const empties = screen.getAllByText("暂无数据");
    expect(empties.length).toBe(3);
  });

  it("renders live stats when available", () => {
    useStatsStore.getState().setStats({
      msg_count: 127, parse_ok: 114, parse_rate: 0.898,
      orders: 38, filled: 36, rejected: 2,
    });
    render(<RightRail />);
    expect(screen.getByText("127")).toBeInTheDocument();
    expect(screen.getByText("114")).toBeInTheDocument();
    expect(screen.getByText(/89.8%/)).toBeInTheDocument();
  });

  it("renders positions list when available", () => {
    usePositionsStore.getState().setAll({
      stocks: [
        { symbol: "TSLL.US", type: "stock", ticker: "TSLL", quantity: 1500, avg_cost: 22.85 },
      ],
      options: [],
    });
    render(<RightRail />);
    expect(screen.getByText(/TSLL\.US/)).toBeInTheDocument();
    expect(screen.getByText("1,500")).toBeInTheDocument();
  });

  it("renders option positions with strike, type, expiry", () => {
    usePositionsStore.getState().setAll({
      stocks: [],
      options: [
        {
          symbol: "TSLA 240620 250C",
          type: "option",
          ticker: "TSLA",
          quantity: 10,
          avg_cost: 5.5,
          option_strike: 250,
          option_expiry: "2024-06-20",
          option_type: "CALL",
        },
      ],
    });
    render(<RightRail />);
    expect(screen.getByText("10")).toBeInTheDocument();
  });
});
