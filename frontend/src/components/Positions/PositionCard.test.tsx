import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { PositionCard } from "./PositionCard";
import type { Position, Quote, Candlesticks } from "../../api/domain-types";

// Pin Date.now() to a known US weekday so effectiveSession in
// PositionCard doesn't downgrade live sessions to "closed" on weekends.
// 2026-05-14T14:30:00Z = Thursday 10:30 ET (mid-regular session).
const TEST_NOW = Date.parse("2026-05-14T14:30:00Z");
beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(TEST_NOW);
});
afterEach(() => {
  vi.useRealTimers();
});

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

describe("PositionCard — Day P/L uses quote.trading_day on holidays", () => {
  it("counts Friday fills as today's trades when quote.trading_day = Friday on a holiday Monday", () => {
    // 2026-05-25 = Memorial Day (US market closed). Broker reports
    // last_done = 7.240 (Friday's close), trade_session = "regular"
    // (state-machine bug, separate issue), trading_day = "2026-05-22"
    // (the actual session this quote belongs to). The dayPl reducer
    // must filter Friday's executions in, not skip them as "not today".
    vi.setSystemTime(Date.parse("2026-05-25T14:30:00Z")); // Mon 10:30 ET

    const conlPosition: Position = {
      symbol: "CONL.US",
      type: "stock",
      ticker: "CONL",
      quantity: 7002,
      avg_cost: 6.941,
      option_strike: null,
      option_expiry: null,
      option_type: null,
    };
    const conlQuote: Quote = {
      symbol: "CONL.US",
      last_done: 7.240,
      prev_close: 7.96,
      open: 7.80,
      high: 7.95,
      low: 7.20,
      volume: 0,
      turnover: 0,
      change: -0.72,
      change_pct: -9.05,
      trade_session: "regular",
      trading_day: "2026-05-22",
    } as Quote;
    // Friday fills: 6001 shares total, avg ~$7.50.
    // Pre-Friday position: 1001 shares (held overnight, baseline = $7.96).
    const executions = [
      { ts: "2026-05-22T11:01:05Z", symbol: "CONL.US", side: "BUY", qty: 1, price: 7.87 },
      { ts: "2026-05-22T14:20:41Z", symbol: "CONL.US", side: "BUY", qty: 2000, price: 7.60 },
      { ts: "2026-05-22T14:21:28Z", symbol: "CONL.US", side: "BUY", qty: 2000, price: 7.50 },
      { ts: "2026-05-22T18:45:30Z", symbol: "CONL.US", side: "BUY", qty: 2000, price: 7.38 },
    ];

    render(
      <PositionCard
        position={conlPosition}
        quote={conlQuote}
        intraday={undefined}
        executions={executions as never}
        onClick={() => {}}
      />,
    );

    // Expected: -2241 (1001×(7.24-7.96) + 2000×(7.24-7.60) + 2000×(7.24-7.50) + 2000×(7.24-7.38) + 1×(7.24-7.87))
    expect(screen.getByText(/-\$2,241/)).toBeInTheDocument();
  });

  it("falls back to wall-clock today when quote.trading_day is null", () => {
    // No trading_day on the quote → behaviour matches the pre-fix
    // path (currentOrLastTradingDay), so this is the regression guard.
    vi.setSystemTime(Date.parse("2026-05-14T14:30:00Z")); // Thu 10:30 ET

    const quoteNoTradingDay: Quote = { ...quote, trading_day: null } as Quote;
    const executions = [
      { ts: "2026-05-14T14:25:00Z", symbol: "TSLA.US", side: "BUY", qty: 40, price: 244 },
    ];
    const positionAfter = { ...position, quantity: 240 + 40 };

    render(
      <PositionCard
        position={positionAfter}
        quote={quoteNoTradingDay}
        intraday={undefined}
        executions={executions as never}
        onClick={() => {}}
      />,
    );
    // qtyStart = 240, last = 245.5, prev = 240, buys = 40 * 244 = 9760
    // Day P/L = 245.5 * 280 + 0 - 9760 - 240 * 240 = 68740 - 9760 - 57600 = 1380
    expect(screen.getByText(/\+\$1,380/)).toBeInTheDocument();
  });
});
