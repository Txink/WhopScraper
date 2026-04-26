import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { CardCompact } from "./CardCompact";
import type { TaskSummary } from "../../api/domain-types";
import * as httpModule from "../../api/http";

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
    render(<CardCompact task={stockTask} autoTrade={true} onExpand={vi.fn()} />);
    expect(screen.getByText("TSLL.US")).toBeInTheDocument();
  });

  it("renders BUY side pill", () => {
    const { container } = render(<CardCompact task={stockTask} autoTrade={true} onExpand={vi.fn()} />);
    expect(screen.getByText("BUY")).toBeInTheDocument();
    expect(container.querySelector(".side-buy")).toBeInTheDocument();
  });

  it("renders status pill", () => {
    const { container } = render(<CardCompact task={stockTask} autoTrade={true} onExpand={vi.fn()} />);
    expect(container.querySelector(".status-filled")).toBeInTheDocument();
  });

  it("renders price in details", () => {
    render(<CardCompact task={stockTask} autoTrade={true} onExpand={vi.fn()} />);
    expect(screen.getByText("$26.50")).toBeInTheDocument();
  });

  it("option task renders formatted title with ticker, strike, type, and expiry", () => {
    render(<CardCompact task={optionTask} autoTrade={true} onExpand={vi.fn()} />);
    expect(screen.getByText("NVDA 135 CALL · 20260426")).toBeInTheDocument();
  });

  it("option type badge shows 期权", () => {
    const { container } = render(<CardCompact task={optionTask} autoTrade={true} onExpand={vi.fn()} />);
    expect(screen.getByText("期权")).toBeInTheDocument();
    expect(container.querySelector(".type-badge.option")).toBeInTheDocument();
  });

  it("has compact grid class", () => {
    const { container } = render(<CardCompact task={stockTask} autoTrade={true} onExpand={vi.fn()} />);
    expect(container.querySelector(".card.compact")).toBeInTheDocument();
  });

  it("renders price alone when qty is null", () => {
    const priceOnly: TaskSummary = {
      ...stockTask,
      instruction: { ...stockTask.instruction!, quantity: null },
    };
    render(<CardCompact task={priceOnly} autoTrade={true} onExpand={vi.fn()} />);
    expect(screen.getByText("$26.50")).toBeInTheDocument();
    // No "×" separator should appear
    expect(screen.queryByText(/×/)).not.toBeInTheDocument();
  });

  it("renders qty alone when price is null", () => {
    const qtyOnly: TaskSummary = {
      ...stockTask,
      instruction: { ...stockTask.instruction!, price: null },
    };
    const { container } = render(<CardCompact task={qtyOnly} autoTrade={true} onExpand={vi.fn()} />);
    const details = container.querySelector(".details");
    expect(details?.textContent).toContain("500");
    expect(details?.textContent).not.toContain("$");
    expect(details?.textContent).not.toContain("×");
  });

  it("renders price × qty when both exist", () => {
    const { container } = render(<CardCompact task={stockTask} autoTrade={true} onExpand={vi.fn()} />);
    const details = container.querySelector(".details");
    expect(details?.textContent).toContain("$26.50");
    expect(details?.textContent).toContain("×");
    expect(details?.textContent).toContain("500");
  });

  it("shows skip reason in details for SKIPPED tasks", () => {
    const skippedTask: TaskSummary = {
      ...stockTask,
      status: "SKIPPED",
      reject_reason: "skip: old message from previous day",
    };
    render(<CardCompact task={skippedTask} autoTrade={true} onExpand={vi.fn()} />);
    expect(screen.getByText("skip: old message from previous day")).toBeInTheDocument();
  });

  const readyTask: TaskSummary = {
    ...stockTask,
    status: "INSTRUCTION_READY",
    order_id: null,
    reject_reason: "auto_trade disabled in config; awaiting manual confirmation",
  };

  it("renders ConfirmActions instead of status pill when autoTrade=false and INSTRUCTION_READY", () => {
    const { container } = render(
      <CardCompact task={readyTask} autoTrade={false} onExpand={vi.fn()} />
    );
    expect(container.querySelector(".confirm-actions.compact")).toBeInTheDocument();
    expect(container.querySelector(".card-status")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "确认下单" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "取消" })).toBeInTheDocument();
  });

  it("renders status pill when autoTrade=true even if INSTRUCTION_READY", () => {
    const { container } = render(
      <CardCompact task={readyTask} autoTrade={true} onExpand={vi.fn()} />
    );
    expect(container.querySelector(".confirm-actions")).not.toBeInTheDocument();
    expect(container.querySelector(".card-status")).toBeInTheDocument();
  });

  it("renders status pill when status is not INSTRUCTION_READY (autoTrade=false)", () => {
    const { container } = render(
      <CardCompact task={stockTask} autoTrade={false} onExpand={vi.fn()} />
    );
    expect(container.querySelector(".confirm-actions")).not.toBeInTheDocument();
    expect(container.querySelector(".card-status")).toBeInTheDocument();
  });

  it("clicking confirm/cancel buttons does not bubble to expand", () => {
    const onExpand = vi.fn();
    vi.spyOn(httpModule.api, "skipTask").mockResolvedValue(stockTask as never);
    render(<CardCompact task={readyTask} autoTrade={false} onExpand={onExpand} />);
    fireEvent.click(screen.getByRole("button", { name: "取消" }));
    expect(onExpand).not.toHaveBeenCalled();
  });
});
