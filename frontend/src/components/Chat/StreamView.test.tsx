import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { StreamView } from "./StreamView";
import type { StreamGroup } from "./chatTimeline";
import {
  makeMessage,
  makeStockTask,
  makeOptionTask,
} from "../../test/fixtures";

function groups(): StreamGroup[] {
  const m1 = makeMessage({ author: "alpha", content: "hi" });
  const m2 = makeMessage({ author: "alpha", content: "again" });
  return [
    { kind: "msgs", sender: "alpha", entries: [m1, m2] },
    { kind: "signal", sender: "TSLL 监听", task: makeStockTask() },
    { kind: "signal", sender: "NVDA 期权监听", task: makeOptionTask() },
  ];
}

describe("StreamView routing", () => {
  it("msg group → ChatMessage (chat-group without monitor class)", () => {
    const { container } = render(
      <StreamView
        groups={groups()}
        watched={new Set()}
        pushEventsByTask={{}}
        expandedTaskId={null}
        onToggleTask={() => {}}
        autoTrade={true}
      />,
    );
    const msgGroup = container.querySelector('[data-sender="alpha"]');
    expect(msgGroup?.className).toBe("chat-group");
  });

  it("stock signal group → StockCard (chat-group.monitor.stock)", () => {
    const { container } = render(
      <StreamView
        groups={groups()}
        watched={new Set()}
        pushEventsByTask={{}}
        expandedTaskId={null}
        onToggleTask={() => {}}
        autoTrade={true}
      />,
    );
    const node = container.querySelector('[data-sender="TSLL 监听"]');
    expect(node?.classList.contains("monitor")).toBe(true);
    expect(node?.classList.contains("stock")).toBe(true);
  });

  it("option signal group → OptionCard (chat-group.monitor.option)", () => {
    const { container } = render(
      <StreamView
        groups={groups()}
        watched={new Set()}
        pushEventsByTask={{}}
        expandedTaskId={null}
        onToggleTask={() => {}}
        autoTrade={true}
      />,
    );
    const node = container.querySelector('[data-sender="NVDA 期权监听"]');
    expect(node?.classList.contains("monitor")).toBe(true);
    expect(node?.classList.contains("option")).toBe(true);
  });

  it("watched sender → align=right (chat-group--right)", () => {
    const { container } = render(
      <StreamView
        groups={groups()}
        watched={new Set(["alpha"])}
        pushEventsByTask={{}}
        expandedTaskId={null}
        onToggleTask={() => {}}
        autoTrade={true}
      />,
    );
    const node = container.querySelector('[data-sender="alpha"]');
    expect(node?.classList.contains("chat-group--right")).toBe(true);
  });

  it("empty groups → no children", () => {
    const { container } = render(
      <StreamView
        groups={[]}
        watched={new Set()}
        pushEventsByTask={{}}
        expandedTaskId={null}
        onToggleTask={() => {}}
        autoTrade={true}
      />,
    );
    expect(container.querySelectorAll(".chat-group")).toHaveLength(0);
  });

  it("watched set is non-empty + this sender is NOT watched → dim avatar (chat-avatar-neutral)", () => {
    const { container } = render(
      <StreamView
        groups={groups()}
        watched={new Set(["someone-else"])}
        pushEventsByTask={{}}
        expandedTaskId={null}
        onToggleTask={() => {}}
        autoTrade={true}
      />,
    );
    const avatar = container.querySelector('[data-sender="alpha"] .chat-avatar');
    expect(avatar?.classList.contains("chat-avatar-neutral")).toBe(true);
  });

  it("watched set is empty → no dim (alpha keeps palette color)", () => {
    const { container } = render(
      <StreamView
        groups={groups()}
        watched={new Set()}
        pushEventsByTask={{}}
        expandedTaskId={null}
        onToggleTask={() => {}}
        autoTrade={true}
      />,
    );
    const avatar = container.querySelector('[data-sender="alpha"] .chat-avatar');
    expect(avatar?.classList.contains("chat-avatar-neutral")).toBe(false);
  });
});
