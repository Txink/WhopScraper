import { render, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { ChatSenderBar } from "./ChatSenderBar";

// patchWatchedSenders makes a real HTTP call — stub it out so tests are
// hermetic. The component only calls it in response to user interaction
// (click) and swallows errors, so a no-op is sufficient here.
vi.mock("../../api/chat", () => ({
  patchWatchedSenders: vi.fn().mockResolvedValue(undefined),
}));

const baseProps = {
  pageId: "p1",
  watchedSenders: [],
  onChange: () => {},
  mode: "filter" as const,
  onModeChange: () => {},
};

describe("ChatSenderBar monitor chips", () => {
  it("renders a watched monitor chip with the correct source dot prefix", () => {
    const { container } = render(
      <ChatSenderBar
        {...baseProps}
        authors={[{ name: "alpha", count: 3 }, { name: "TSLL 监听", count: 0 }]}
        watchedSenders={["TSLL 监听"]}
        monitorSources={{ "TSLL 监听": "stock" }}
      />,
    );
    const chip = container.querySelector("button.chat-watched-chip.monitor");
    expect(chip).not.toBeNull();
    expect(chip!.querySelector(".src-dot.stock")).not.toBeNull();
  });

  it("regular watched chip has no .monitor class and no src-dot", () => {
    const { container } = render(
      <ChatSenderBar
        {...baseProps}
        authors={[{ name: "alpha", count: 3 }]}
        watchedSenders={["alpha"]}
        monitorSources={{}}
      />,
    );
    const chip = container.querySelector("button.chat-watched-chip");
    expect(chip).not.toBeNull();
    expect(chip!.classList.contains("monitor")).toBe(false);
    expect(chip!.querySelector(".src-dot")).toBeNull();
  });

  it("option monitor chip gets src-dot.option class", () => {
    const { container } = render(
      <ChatSenderBar
        {...baseProps}
        authors={[{ name: "NVDA 期权", count: 2 }]}
        watchedSenders={["NVDA 期权"]}
        monitorSources={{ "NVDA 期权": "option" }}
      />,
    );
    const chip = container.querySelector("button.chat-watched-chip.monitor");
    expect(chip).not.toBeNull();
    expect(chip!.querySelector(".src-dot.option")).not.toBeNull();
    expect(chip!.querySelector(".src-dot.stock")).toBeNull();
  });

  it("works without monitorSources prop (backward-compat default)", () => {
    // No monitorSources passed at all — should render plain chip, no crash.
    const { container } = render(
      <ChatSenderBar
        {...baseProps}
        authors={[{ name: "alpha", count: 1 }]}
        watchedSenders={["alpha"]}
      />,
    );
    const chip = container.querySelector("button.chat-watched-chip");
    expect(chip).not.toBeNull();
    expect(chip!.classList.contains("monitor")).toBe(false);
  });

  it("popover item for a monitor sender gets .monitor class and src-dot", () => {
    // Open the popover by rendering with no watchedSenders (so "TSLL 监听"
    // appears in the addable list). The popover is only mounted when open,
    // so we need to trigger the button first.
    const { container } = render(
      <ChatSenderBar
        {...baseProps}
        authors={[{ name: "TSLL 监听", count: 5 }]}
        watchedSenders={[]}
        monitorSources={{ "TSLL 监听": "stock" }}
      />,
    );
    // Use fireEvent.click to dispatch a synthetic React event on the trigger.
    const trigger = container.querySelector("button.chat-sender-label");
    expect(trigger).not.toBeNull();
    fireEvent.click(trigger!);

    const popoverItem = container.querySelector(
      ".chat-sender-popover-item.monitor",
    );
    expect(popoverItem).not.toBeNull();
    expect(popoverItem!.querySelector(".src-dot.stock")).not.toBeNull();
  });
});
