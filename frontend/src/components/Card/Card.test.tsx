import { describe, expect, it } from "vitest";
import { render, fireEvent } from "@testing-library/react";
import { Card } from "./Card";
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

const filledTask: TaskSummary = {
  id: "task-001",
  type: "stock",
  status: "FILLED",
  order_id: "123456789",
  stage_timings: { parse: 18, submit: 412 },
  created_at: "2026-04-25T10:42:15.100Z",
  updated_at: "2026-04-25T10:42:17.300Z",
  reject_reason: null,
  message: baseMessage,
  instruction: baseInstruction,
};

describe("Card", () => {
  it("defaultExpanded=false renders compact mode", () => {
    const { container } = render(
      <Card task={filledTask} pushEvents={[]} defaultExpanded={false} autoTrade={true} />
    );
    expect(container.querySelector(".card.compact")).toBeInTheDocument();
    expect(container.querySelector(".card.expanded")).not.toBeInTheDocument();
  });

  it("defaultExpanded=true renders expanded mode", () => {
    const { container } = render(
      <Card task={filledTask} pushEvents={[]} defaultExpanded={true} autoTrade={true} />
    );
    expect(container.querySelector(".card.expanded")).toBeInTheDocument();
    expect(container.querySelector(".card.compact")).not.toBeInTheDocument();
  });

  it("clicking compact card expands it", () => {
    const { container } = render(
      <Card task={filledTask} pushEvents={[]} defaultExpanded={false} autoTrade={true} />
    );
    const compactCard = container.querySelector(".card.compact")!;
    fireEvent.click(compactCard);
    expect(container.querySelector(".card.expanded")).toBeInTheDocument();
    expect(container.querySelector(".card.compact")).not.toBeInTheDocument();
  });

  it("clicking the header in expanded mode collapses it", () => {
    // The dedicated collapse button was removed; the entire .card-header
    // is now the collapse hit-target (role=button, aria-label="收起").
    const { container } = render(
      <Card task={filledTask} pushEvents={[]} defaultExpanded={true} autoTrade={true} />
    );
    const header = container.querySelector(".card.expanded .card-header")!;
    fireEvent.click(header);
    expect(container.querySelector(".card.compact")).toBeInTheDocument();
    expect(container.querySelector(".card.expanded")).not.toBeInTheDocument();
  });
});
