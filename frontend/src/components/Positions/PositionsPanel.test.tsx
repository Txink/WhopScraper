import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { PositionsPanel } from "./PositionsPanel";
import { usePositionsStore } from "../../stores/positions";
import { useDetailViewStore } from "../../stores/detailView";
import { useQuotesStore } from "../../stores/quotes";
import { useCandlesticksStore } from "../../stores/candlesticks";
import { useExecutionsStore } from "../../stores/executions";
import { api } from "../../api/http";
import type { Quote, Position } from "../../api/domain-types";

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

describe("PositionsPanel — session-aware candle fetch", () => {
  // Minimal Quote fixture — fill missing fields with zeros so the
  // type-checker accepts it.
  const quoteFixture: Quote = {
    symbol: "TSLA.US", last_done: 100, prev_close: 100, today_close: null,
    open: 100, high: 100, low: 100, volume: 0, turnover: 0,
    change: 0, change_pct: 0, trade_session: "regular",
  };
  const stockFixture: Position = {
    symbol: "TSLA.US", ticker: "TSLA", quantity: 100, avg_cost: 100,
    type: "stock", option_strike: null, option_expiry: null, option_type: null,
  };

  beforeEach(() => {
    usePositionsStore.setState({ stocks: [], options: [] });
    useQuotesStore.setState({ quotesBySymbol: {}, lastUpdatedAt: null });
    useCandlesticksStore.setState({ byKey: {} });
    useExecutionsStore.setState({ executions: [], lastSyncedAt: null });
  });
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("fetches granularity=分时 with the current session on mount", async () => {
    const candleSpy = vi.spyOn(api, "candlesticks").mockResolvedValue({
      symbol: "TSLA.US", period: "today", bars: [],
    });
    vi.spyOn(api, "quotes").mockResolvedValue({ quotes: [] });
    vi.spyOn(api, "todayExecutions").mockResolvedValue({
      executions: [], total_count: 0, has_more: false, last_synced_at: null,
    });
    vi.spyOn(api, "watchQuotes").mockResolvedValue({ added: 0, removed: 0, total: 0 });

    usePositionsStore.setState({ stocks: [stockFixture], options: [] });
    useQuotesStore.setState({
      quotesBySymbol: { "TSLA.US": { ...quoteFixture, trade_session: "regular" } },
      lastUpdatedAt: Date.now(),
    });

    render(<PositionsPanel />);
    await waitFor(() => {
      expect(candleSpy).toHaveBeenCalledWith(
        "TSLA.US", "today",
        expect.objectContaining({ granularity: "分时", sessions: "regular" }),
      );
    });
  });

  it("refetches when trade_session transitions regular → post", async () => {
    const candleSpy = vi.spyOn(api, "candlesticks").mockResolvedValue({
      symbol: "TSLA.US", period: "today", bars: [],
    });
    vi.spyOn(api, "quotes").mockResolvedValue({ quotes: [] });
    vi.spyOn(api, "todayExecutions").mockResolvedValue({
      executions: [], total_count: 0, has_more: false, last_synced_at: null,
    });
    vi.spyOn(api, "watchQuotes").mockResolvedValue({ added: 0, removed: 0, total: 0 });

    usePositionsStore.setState({ stocks: [stockFixture], options: [] });
    useQuotesStore.setState({
      quotesBySymbol: { "TSLA.US": { ...quoteFixture, trade_session: "regular" } },
      lastUpdatedAt: Date.now(),
    });

    render(<PositionsPanel />);
    await waitFor(() => expect(candleSpy).toHaveBeenCalledTimes(1));

    // Simulate session transition: regular → post.
    useQuotesStore.setState({
      quotesBySymbol: { "TSLA.US": { ...quoteFixture, trade_session: "post" } },
      lastUpdatedAt: Date.now(),
    });

    await waitFor(() => {
      expect(candleSpy).toHaveBeenCalledTimes(2);
      expect(candleSpy).toHaveBeenLastCalledWith(
        "TSLA.US", "today",
        expect.objectContaining({ granularity: "分时", sessions: "post" }),
      );
    });
  });

  it("does NOT refetch on quote-push within the same session", async () => {
    const candleSpy = vi.spyOn(api, "candlesticks").mockResolvedValue({
      symbol: "TSLA.US", period: "today", bars: [],
    });
    vi.spyOn(api, "quotes").mockResolvedValue({ quotes: [] });
    vi.spyOn(api, "todayExecutions").mockResolvedValue({
      executions: [], total_count: 0, has_more: false, last_synced_at: null,
    });
    vi.spyOn(api, "watchQuotes").mockResolvedValue({ added: 0, removed: 0, total: 0 });

    usePositionsStore.setState({ stocks: [stockFixture], options: [] });
    useQuotesStore.setState({
      quotesBySymbol: { "TSLA.US": { ...quoteFixture, trade_session: "regular" } },
      lastUpdatedAt: Date.now(),
    });

    render(<PositionsPanel />);
    await waitFor(() => expect(candleSpy).toHaveBeenCalledTimes(1));

    // 5 same-session pushes (different last_done values) — should NOT refetch.
    for (let i = 0; i < 5; i++) {
      useQuotesStore.setState({
        quotesBySymbol: {
          "TSLA.US": { ...quoteFixture, trade_session: "regular", last_done: 100 + i },
        },
        lastUpdatedAt: Date.now(),
      });
    }
    await new Promise((r) => setTimeout(r, 50));
    expect(candleSpy).toHaveBeenCalledTimes(1);
  });
});
