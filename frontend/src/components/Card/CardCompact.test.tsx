import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { CardCompact } from "./CardCompact";
import type { TaskSummary } from "../../api/domain-types";

const baseMessage = {
  id: "msg-001",
  content: "TSLL 26.5 附近加一半",
  raw_content: "TSLL 26.5 附近加一半",
  author: null,
  source: "group",
  posted_at: "2026-04-25T10:42:15.000Z",
  received_at: "2026-04-25T10:42:15.082Z",
  quoted_message_id: null,
};

const stockTask: TaskSummary = {
  id: "task-001",
  type: "stock",
  status: "FILLED",
  order_id: "123456789",
  stage_timings: { parse: 18, submit: 412 },
  created_at: "2026-04-25T10:42:15.100Z",
  updated_at: "2026-04-25T10:42:17.300Z",
  reject_reason: null,
  message: baseMessage,
  instruction: {
    type: "stock",
    instruction_type: "buy",
    price: 26.5,
    price_range: null,
    quantity: 500,
    position_size: null,
    stop_loss_price: 25.8,
    take_profit_price: null,
    context_source: "group",
    parser_notes: [],
    ticker: "TSLL",
    symbol: "TSLL.US",
    sell_quantity: null,
    option_type: null,
    strike: null,
    expiry: null,
  },
};

const optionTask: TaskSummary = {
  id: "task-002",
  type: "option",
  status: "FILLED",
  order_id: "987654321",
  stage_timings: { parse: 22, submit: 380 },
  created_at: "2026-04-25T10:28:04.000Z",
  updated_at: "2026-04-25T10:28:05.610Z",
  reject_reason: null,
  message: {
    ...baseMessage,
    id: "msg-002",
    content: "NVDA 135C 进场",
    raw_content: "NVDA 135C 进场",
    received_at: "2026-04-25T10:28:04.000Z",
  },
  instruction: {
    type: "option",
    instruction_type: "buy",
    price: 2.13,
    price_range: null,
    quantity: 2,
    position_size: null,
    stop_loss_price: null,
    take_profit_price: null,
    context_source: "group",
    parser_notes: [],
    ticker: "NVDA",
    symbol: "NVDA260426C135000.US",
    sell_quantity: null,
    option_type: "CALL",
    strike: 135,
    expiry: "2026-04-26",
  },
};

describe("CardCompact", () => {
  it("renders stock ticker symbol", () => {
    render(<CardCompact task={stockTask} onExpand={vi.fn()} />);
    expect(screen.getByText("TSLL.US")).toBeInTheDocument();
  });

  it("renders BUY side pill", () => {
    const { container } = render(<CardCompact task={stockTask} onExpand={vi.fn()} />);
    expect(screen.getByText("BUY")).toBeInTheDocument();
    expect(container.querySelector(".side-buy")).toBeInTheDocument();
  });

  it("renders status pill", () => {
    const { container } = render(<CardCompact task={stockTask} onExpand={vi.fn()} />);
    expect(container.querySelector(".status-filled")).toBeInTheDocument();
  });

  it("renders price in details", () => {
    render(<CardCompact task={stockTask} onExpand={vi.fn()} />);
    expect(screen.getByText("$26.50")).toBeInTheDocument();
  });

  it("option task renders formatted title with ticker, strike, type, and expiry", () => {
    render(<CardCompact task={optionTask} onExpand={vi.fn()} />);
    expect(screen.getByText("NVDA 135 CALL · 20260426")).toBeInTheDocument();
  });

  it("option type badge shows 期权", () => {
    const { container } = render(<CardCompact task={optionTask} onExpand={vi.fn()} />);
    expect(screen.getByText("期权")).toBeInTheDocument();
    expect(container.querySelector(".type-badge.option")).toBeInTheDocument();
  });

  it("has compact grid class", () => {
    const { container } = render(<CardCompact task={stockTask} onExpand={vi.fn()} />);
    expect(container.querySelector(".card.compact")).toBeInTheDocument();
  });
});
