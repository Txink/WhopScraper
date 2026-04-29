import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { CardExpanded } from "./CardExpanded";
import type { TaskSummary, PushEvent } from "../../api/domain-types";

const baseMessage = {
  id: "msg-001",
  content: "TSLL 26.5 附近加一半，止损 25.8",
  raw_content: "TSLL 26.5 附近加一半，止损 25.8",
  author: null,
  source: "group",
  posted_at: "2026-04-25T10:42:15.000Z",
  received_at: "2026-04-25T10:42:15.082Z",
  quoted_message_id: null,
};

const baseInstruction = {
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
};

const task: TaskSummary = {
  id: "task-001",
  type: "stock",
  status: "FILLED",
  order_id: "729308570398740480",
  stage_timings: { parse: 18, submit: 412 },
  created_at: "2026-04-25T10:42:15.100Z",
  updated_at: "2026-04-25T10:42:17.300Z",
  reject_reason: null,
  message: baseMessage,
  instruction: baseInstruction,
};

const pushEvents: PushEvent[] = [
  {
    id: "pe-001",
    task_id: "task-001",
    order_id: "729308570398740480",
    state: "NEW",
    received_at: "2026-04-25T10:42:15.498Z",
    delta_qty: null,
    delta_price: null,
    cumulative_qty: null,
    cumulative_avg_price: null,
    note: "broker 确认订单已创建",
  },
  {
    id: "pe-002",
    task_id: "task-001",
    order_id: "729308570398740480",
    state: "PARTIAL",
    received_at: "2026-04-25T10:42:16.942Z",
    delta_qty: 100,
    delta_price: 26.47,
    cumulative_qty: 100,
    cumulative_avg_price: 26.47,
    note: null,
  },
];

describe("CardExpanded", () => {
  it("renders expanded card with header", () => {
    const { container } = render(
      <CardExpanded task={task} pushEvents={[]} autoTrade={true} onCollapse={vi.fn()} />
    );
    expect(container.querySelector(".card.expanded")).toBeInTheDocument();
    expect(container.querySelector(".card-header")).toBeInTheDocument();
  });

  it("renders symbol in header", () => {
    render(<CardExpanded task={task} pushEvents={[]} autoTrade={true} onCollapse={vi.fn()} />);
    expect(screen.getByText("TSLL.US")).toBeInTheDocument();
  });

  it("renders raw message content", () => {
    render(<CardExpanded task={task} pushEvents={[]} autoTrade={true} onCollapse={vi.fn()} />);
    expect(screen.getByText(/TSLL 26.5 附近加一半/)).toBeInTheDocument();
  });

  it("renders inline parse info on 解析指令 stage (ticker / price / qty / stop)", () => {
    const { container } = render(
      <CardExpanded task={task} pushEvents={[]} autoTrade={true} onCollapse={vi.fn()} />
    );
    // The old chips block should be gone
    expect(container.querySelector(".chips")).not.toBeInTheDocument();
    // The new inline block sits beneath the 解析指令 label
    const parseInline = container.querySelector(".parse-inline");
    expect(parseInline).toBeInTheDocument();
    expect(parseInline?.querySelector(".parse-ticker")?.textContent).toBe("TSLL");
    expect(parseInline?.querySelector(".parse-price")?.textContent).toBe("$26.50");
    expect(parseInline?.querySelector(".parse-qty")?.textContent).toBe("× 500");
    // stop_loss_price is rendered as a parse-extra
    expect(parseInline?.textContent).toContain("stop $25.80");
  });

  it("renders local stages", () => {
    const { container } = render(
      <CardExpanded task={task} pushEvents={[]} autoTrade={true} onCollapse={vi.fn()} />
    );
    expect(container.querySelector(".stages")).toBeInTheDocument();
    expect(screen.getByText("原始消息")).toBeInTheDocument();
    expect(screen.getByText("解析指令")).toBeInTheDocument();
    expect(screen.getByText("提交订单")).toBeInTheDocument();
  });

  it("renders push block when push events exist", () => {
    const { container } = render(
      <CardExpanded task={task} pushEvents={pushEvents} autoTrade={true} onCollapse={vi.fn()} />
    );
    expect(container.querySelector(".push-block")).toBeInTheDocument();
    expect(screen.getByText("订单推送")).toBeInTheDocument();
  });

  it("push chain shows push events in compact mode by default", () => {
    const { container } = render(
      <CardExpanded task={task} pushEvents={pushEvents} autoTrade={true} onCollapse={vi.fn()} />
    );
    // compact mode shows push-chain
    expect(container.querySelector(".push-chain")).toBeInTheDocument();
    // detail list should not be visible by default
    expect(container.querySelector(".push-detail-list")).not.toBeInTheDocument();
  });

  it("toggle push-block shows detail list", () => {
    const { container } = render(
      <CardExpanded task={task} pushEvents={pushEvents} autoTrade={true} onCollapse={vi.fn()} />
    );
    const toggleBtn = screen.getByText("展开 ▾");
    fireEvent.click(toggleBtn);
    expect(container.querySelector(".push-detail-list")).toBeInTheDocument();
    expect(container.querySelector(".push-chain")).not.toBeInTheDocument();
    // Button text changes to 收起
    expect(screen.getByText("收起 ▴")).toBeInTheDocument();
  });

  it("calls onCollapse when collapse button clicked", () => {
    const onCollapse = vi.fn();
    render(<CardExpanded task={task} pushEvents={[]} autoTrade={true} onCollapse={onCollapse} />);
    fireEvent.click(screen.getByLabelText("收起"));
    expect(onCollapse).toHaveBeenCalledOnce();
  });

  it("renders order_id in submit stage and shows the synthetic '已提交' push node", () => {
    render(<CardExpanded task={task} pushEvents={[]} autoTrade={true} onCollapse={vi.fn()} />);
    // Default view is collapsed (PushChain); order_id renders only in OrderSubmit
    // there — the synthetic '已提交' node intentionally omits the id when collapsed
    // and only surfaces it in the expanded PushDetail view.
    expect(screen.getByText("729308570398740480")).toBeInTheDocument();
    expect(screen.getByText("已提交")).toBeInTheDocument();
  });

  it("shows skip reason in parse stage for SKIPPED tasks", () => {
    const skippedTask: TaskSummary = {
      ...task,
      status: "SKIPPED",
      reject_reason: "skip: duplicated message",
    };
    render(<CardExpanded task={skippedTask} pushEvents={[]} autoTrade={true} onCollapse={vi.fn()} />);
    expect(screen.getByText("skip: duplicated message")).toBeInTheDocument();
  });

  it("shows ConfirmActions when autoTrade off and instruction ready", () => {
    const readyTask: TaskSummary = {
      ...task,
      status: "INSTRUCTION_READY",
      order_id: null,
      reject_reason: "awaiting manual confirmation",
    };
    const { container } = render(
      <CardExpanded task={readyTask} pushEvents={[]} autoTrade={false} onCollapse={vi.fn()} />
    );
    expect(container.querySelector(".confirm-actions.expanded")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "确认下单" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "取消" })).toBeInTheDocument();
  });

  it("hides ConfirmActions when autoTrade is on", () => {
    const readyTask: TaskSummary = {
      ...task,
      status: "INSTRUCTION_READY",
      order_id: null,
    };
    const { container } = render(
      <CardExpanded task={readyTask} pushEvents={[]} autoTrade={true} onCollapse={vi.fn()} />
    );
    expect(container.querySelector(".confirm-actions")).not.toBeInTheDocument();
  });
});
