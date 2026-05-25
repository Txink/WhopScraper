import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { OptionCard } from "./OptionCard";
import type { Position, Quote } from "../../api/domain-types";

const TEST_NOW = Date.parse("2026-05-14T14:30:00Z");
beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(TEST_NOW);
});
afterEach(() => {
  vi.useRealTimers();
});

describe("OptionCard — Day P/L uses quote.trading_day on holidays", () => {
  it("counts Friday fills as today's trades when quote.trading_day = Friday", () => {
    vi.setSystemTime(Date.parse("2026-05-25T14:30:00Z")); // Mon holiday

    const optPosition: Position = {
      symbol: "TSLA250620C300000.US",
      type: "option",
      ticker: "TSLA",
      quantity: 5,
      avg_cost: 4.20,
      option_strike: 300,
      option_expiry: "2025-06-20",
      option_type: "call",
    };
    const optQuote: Quote = {
      symbol: "TSLA250620C300000.US",
      last_done: 4.50,
      prev_close: 5.00,
      open: 4.80,
      high: 4.95,
      low: 4.30,
      volume: 0,
      turnover: 0,
      change: -0.50,
      change_pct: -10.0,
      trade_session: "regular",
      trading_day: "2026-05-22",
    } as Quote;
    // 3 contracts bought on Friday at $4.50, 2 held overnight from
    // prev_close $5.00.
    const executions = [
      { ts: "2026-05-22T14:30:00Z", symbol: "TSLA250620C300000.US", side: "BUY", qty: 3, price: 4.50 },
    ];

    render(
      <OptionCard
        position={optPosition}
        quote={optQuote}
        history={undefined}
        executions={executions as never}
        onClick={() => {}}
      />,
    );
    // qtyStart = 5 - 3 = 2. Day P/L (×100):
    //   (4.50 * 5 + 0 - 4.50 * 3 - 5.00 * 2) * 100
    //   = (22.5 - 13.5 - 10) * 100
    //   = -100
    expect(screen.getByText(/-\$100/)).toBeInTheDocument();
  });
});
