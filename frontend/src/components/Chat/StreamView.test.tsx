import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { StreamView } from "./StreamView";
import type { StreamGroup } from "./chatTimeline";
import type { TaskSummary } from "../../api/domain-types";

function makeStreamGroups(): StreamGroup[] {
  return [
    {
      kind: "msgs",
      sender: "alpha",
      entries: [
        { id: "m1", page_id: "p", author: "alpha", content: "hi", posted_at: "2026-05-20T01:00:00Z" },
        { id: "m2", page_id: "p", author: "alpha", content: "again", posted_at: "2026-05-20T01:01:00Z" },
      ],
    },
    {
      kind: "signal",
      sender: "TSLL 监听",
      task: {
        id: "t1", type: "stock", status: "FILLED",
        message: {
          id: "t1", source: "whop", author: "TSLL 监听",
          content: "buy", posted_at: "2026-05-20T01:02:00Z",
          received_at: "2026-05-20T01:02:00Z", url: "https://x",
        },
        instruction: { instruction_type: "BUY", ticker: "TSLL", symbol: "TSLL.US", price: 200, quantity: 100 },
        last_cum_qty: 100, last_cum_avg_price: 199.87,
        created_at: "x", updated_at: "x",
      } as unknown as TaskSummary,
    },
  ];
}

describe("StreamView", () => {
  it("renders consecutive msg group as multiple bubbles + signal group as SignalCard", () => {
    render(<StreamView
      groups={makeStreamGroups()}
      watched={new Set(["alpha"])}
      pushEventsByTask={{}}
      expandedTaskId={null}
      onToggleTask={() => {}}
      autoTrade={true}
    />);
    expect(screen.getByText("hi")).toBeInTheDocument();
    expect(screen.getByText("again")).toBeInTheDocument();
    expect(screen.getByText(/TSLL\.US/)).toBeInTheDocument();
  });

  it("watched sender's group gets the watched class", () => {
    const { container } = render(<StreamView
      groups={makeStreamGroups()}
      watched={new Set(["alpha"])}
      pushEventsByTask={{}}
      expandedTaskId={null}
      onToggleTask={() => {}}
      autoTrade={true}
    />);
    const alphaGroup = container.querySelector('[data-sender="alpha"]');
    expect(alphaGroup?.classList.contains("watched")).toBe(true);
    const monitorGroup = container.querySelector('[data-sender="TSLL 监听"]');
    expect(monitorGroup?.classList.contains("watched")).toBe(false);
  });

  it("renders nothing visible when groups is empty", () => {
    const { container } = render(<StreamView
      groups={[]} watched={new Set()} pushEventsByTask={{}}
      expandedTaskId={null} onToggleTask={() => {}} autoTrade={true}
    />);
    // No stream-group items
    expect(container.querySelectorAll(".stream-group")).toHaveLength(0);
  });
});
