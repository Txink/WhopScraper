import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { PositionCard } from "./PositionCard";
import type { Position, Quote, Candlesticks } from "../../api/domain-types";

const position: Position = {
  symbol: "TSLA.US",
  type: "stock",
  ticker: "TSLA",
  quantity: 240,
  avg_cost: 232.18,
  option_strike: null,
  option_expiry: null,
  option_type: null,
};

const quote: Quote = {
  symbol: "TSLA.US",
  last_done: 245.50,
  prev_close: 240.00,
  open: 241.00,
  high: 246.00,
  low: 239.50,
  volume: 10_000_000,
  turnover: 2_450_000_000,
  change: 5.50,
  change_pct: 2.29,
  trade_session: "regular",
};

const intraday: Candlesticks = {
  symbol: "TSLA.US",
  period: "today",
  bars: [
    { timestamp: "2026-05-14T09:30:00", open: 241, high: 242, low: 240, close: 241.5, volume: 100, turnover: 24150 },
    { timestamp: "2026-05-14T09:35:00", open: 241.5, high: 243, low: 241, close: 242.5, volume: 110, turnover: 26675 },
  ],
};

describe("PositionCard", () => {
  it("renders ticker, price, and change pct from the quote", () => {
    render(
      <PositionCard
        position={position}
        quote={quote}
        intraday={intraday}
        onClick={vi.fn()}
      />,
    );
    expect(screen.getByText("TSLA")).toBeInTheDocument();
    // Price renders with 3 decimals + $ prefix — TSLL-class tickers
    // trade in sub-dollar increments where the third digit is significant.
    expect(screen.getByText("$245.500")).toBeInTheDocument();
    expect(screen.getByText(/\+2\.29%/)).toBeInTheDocument();
  });

  it("computes floating P/L %  from (last - avg) / avg", () => {
    render(
      <PositionCard
        position={position}
        quote={quote}
        intraday={intraday}
        onClick={vi.fn()}
      />,
    );
    // (245.50 - 232.18) / 232.18 ≈ +5.74%
    expect(screen.getByText(/\+5\.74%/)).toBeInTheDocument();
  });

  it("falls back to '—' in the price slot when quote is missing", () => {
    const { container } = render(
      <PositionCard
        position={position}
        quote={undefined}
        intraday={undefined}
        onClick={vi.fn()}
      />,
    );
    expect(container.querySelector(".pcard-price")?.textContent).toBe("—");
  });

  it("invokes onClick when card is clicked", () => {
    const onClick = vi.fn();
    render(
      <PositionCard
        position={position}
        quote={quote}
        intraday={intraday}
        onClick={onClick}
      />,
    );
    fireEvent.click(screen.getByText("TSLA").closest(".pcard")!);
    expect(onClick).toHaveBeenCalledTimes(1);
  });

  it("computes intraday-aware Day P/L from today's trades", () => {
    // Scenario: yesterday held 240 shares. Today bought 60 @ 242 then sold
    // 100 @ 246. qty_now = 240 + 60 − 100 = 200. last = 245.50.
    //   qty_start = 200 − 60 + 100 = 240
    //   Day P/L = 245.50 × 200 + 100×246 − 60×242 − 240 × 240
    //           = 49100 + 24600 − 14520 − 57600 = 1580
    const today = new Date();
    const executions = [
      {
        order_id: "o-b",
        symbol: "TSLA.US",
        ticker: "TSLA",
        side: "BUY" as const,
        qty: 60,
        price: 242,
        ts: today.toISOString(),
      },
      {
        order_id: "o-s",
        symbol: "TSLA.US",
        ticker: "TSLA",
        side: "SELL" as const,
        qty: 100,
        price: 246,
        ts: today.toISOString(),
      },
    ];
    const quoteWithPrev = { ...quote, prev_close: 240 };
    const positionAfter = { ...position, quantity: 200 };

    const { container } = render(
      <PositionCard
        position={positionAfter}
        quote={quoteWithPrev}
        intraday={intraday}
        executions={executions}
        onClick={vi.fn()}
      />,
    );
    // dayPl chip text format: "+$1,580" (signed, no decimals, $ prefix).
    const text = container.querySelector(".pcard-day-pl")?.textContent ?? "";
    expect(text).toMatch(/\+\$1,580/);
  });
});

describe("PositionCard — session-aware Day P/L baseline", () => {
  it("uses today_close as baseline in post session", () => {
    const postQuote: Quote = {
      ...quote,
      trade_session: "post",
      prev_close: 240,
      today_close: 245,
      last_done: 246,
      change: 1,
      change_pct: 0.41,
    };
    // No today trades — qty_start == qty_now == 240
    // Day P/L = 246 × 240 + 0 - 0 - 245 × 240 = 240
    render(
      <PositionCard
        position={position}
        quote={postQuote}
        intraday={intraday}
        executions={[]}
        onClick={vi.fn()}
      />,
    );
    expect(screen.getByText(/\+\$240/)).toBeInTheDocument();
  });

  it("falls back to prev_close in regular session", () => {
    render(
      <PositionCard
        position={position}
        quote={quote}
        intraday={intraday}
        executions={[]}
        onClick={vi.fn()}
      />,
    );
    // Day P/L = (245.50 - 240) × 240 = 1320
    expect(screen.getByText(/\+\$1,320/)).toBeInTheDocument();
  });
});

describe("PositionCard — IntradaySpark wiring", () => {
  it("mounts IntradaySpark when intraday bars are present", () => {
    const { container } = render(
      <PositionCard
        position={position}
        quote={quote}
        intraday={intraday}
        onClick={vi.fn()}
      />,
    );
    expect(container.querySelector(".ispark")).not.toBeNull();
    expect(container.querySelector(".minline")).toBeNull();
  });

  it("passes session=closed when quote.trade_session is closed", () => {
    const closedQuote: Quote = { ...quote, trade_session: "closed" };
    const { container } = render(
      <PositionCard
        position={position}
        quote={closedQuote}
        intraday={intraday}
        onClick={vi.fn()}
      />,
    );
    expect(container.querySelector(".ispark.is-closed")).not.toBeNull();
  });
});
