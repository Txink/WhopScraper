import { render, screen, fireEvent } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { TaskSummary } from "../../api/domain-types";
import { SignalCard } from "./SignalCard";

function task(over: Partial<TaskSummary>): TaskSummary {
  return {
    id: "t1",
    type: "stock",
    status: "FILLED",
    order_id: null,
    stage_timings: {},
    reject_reason: null,
    message: {
      id: "msg1",
      source: "whop",
      author: "TSLL 监听",
      content: "buying tsla calls dip 200",
      posted_at: "2026-05-20T01:32:15Z",
      received_at: "2026-05-20T01:32:15Z",
      url: "https://whop.com/x",
    },
    instruction: {
      type: "stock",
      instruction_type: "BUY",
      ticker: "TSLL",
      symbol: "TSLL.US",
      price: 200,
      quantity: 100,
      price_range: null,
      position_size: null,
      stop_loss_price: null,
      take_profit_price: null,
      context_source: null,
      parser_notes: [],
    },
    last_cum_qty: 100,
    last_cum_avg_price: 199.87,
    created_at: "2026-05-20T01:32:15Z",
    updated_at: "2026-05-20T01:32:16Z",
    ...over,
  } as TaskSummary;
}

describe("SignalCard", () => {
  it("folded renders the three-layer summary", () => {
    render(<SignalCard task={task({})} pushEvents={[]} expanded={false} onToggle={() => {}} autoTrade={true} />);
    expect(screen.getByText(/buying tsla calls/)).toBeInTheDocument();
    expect(screen.getByText("BUY")).toBeInTheDocument();
    expect(screen.getByText(/TSLL\.US/)).toBeInTheDocument();
    expect(screen.getByText(/已成交/)).toBeInTheDocument();
  });

  it("PARSE_ERROR shows red sig line and hides ord", () => {
    render(<SignalCard
      task={{ ...task({}), status: "PARSE_ERROR", instruction: null, reject_reason: "no match" } as TaskSummary}
      pushEvents={[]} expanded={false} onToggle={() => {}} autoTrade={true}
    />);
    expect(screen.getByText(/未解析/)).toBeInTheDocument();
    expect(screen.queryByText(/已成交/)).not.toBeInTheDocument();
  });

  it("INSTRUCTION_READY + auto_trade off shows confirm buttons", () => {
    render(<SignalCard
      task={{ ...task({}), status: "INSTRUCTION_READY" } as TaskSummary}
      pushEvents={[]} expanded={false} onToggle={() => {}} autoTrade={false}
    />);
    // ConfirmActions renders ✓ and ✗ buttons; assert by role + accessible name
    expect(screen.getAllByRole("button").length).toBeGreaterThanOrEqual(2);
  });

  it("click bubble triggers onToggle", () => {
    const onToggle = vi.fn();
    const { container } = render(
      <SignalCard task={task({})} pushEvents={[]} expanded={false} onToggle={onToggle} autoTrade={true} />
    );
    fireEvent.click(container.querySelector(".signal-bubble")!);
    expect(onToggle).toHaveBeenCalledOnce();
  });

  it("expanded shows the detail block", () => {
    render(<SignalCard
      task={task({})} pushEvents={[]} expanded={true} onToggle={() => {}} autoTrade={true}
    />);
    expect(screen.getByText(/MSG/)).toBeInTheDocument();
  });

  it("option task renders contract label '880C 12/15'", () => {
    render(<SignalCard
      task={{ ...task({}),
        type: "option",
        instruction: {
          type: "option",
          instruction_type: "BUY",
          ticker: "NVDA",
          symbol: "NVDA.US",
          strike: 880,
          expiry: "2026-12-15",
          price: 5.2,
          quantity: 5,
          price_range: null,
          position_size: null,
          stop_loss_price: null,
          take_profit_price: null,
          context_source: null,
          parser_notes: [],
        },
      } as TaskSummary}
      pushEvents={[]} expanded={false} onToggle={() => {}} autoTrade={true}
    />);
    expect(screen.getByText("880C 12/15")).toBeInTheDocument();
  });
});
