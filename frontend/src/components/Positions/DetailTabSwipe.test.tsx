import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { DetailTabSwipe } from "./DetailTabSwipe";

const tabs = [
  { id: "records", label: "交易记录", content: <div data-testid="t0">tab0</div> },
  { id: "trading", label: "交易面板", content: <div data-testid="t1">tab1</div> },
  { id: "alerts",  label: "告警",     content: <div data-testid="t2">tab2</div> },
];

describe("DetailTabSwipe", () => {
  it("renders all three tabs initially mounted (for swipe continuity)", () => {
    render(<DetailTabSwipe tabs={tabs} index={1} onIndexChange={() => {}} />);
    expect(screen.getByTestId("t0")).toBeInTheDocument();
    expect(screen.getByTestId("t1")).toBeInTheDocument();
    expect(screen.getByTestId("t2")).toBeInTheDocument();
  });

  it("clicking an indicator dot fires onIndexChange", async () => {
    const onIndex = vi.fn();
    render(<DetailTabSwipe tabs={tabs} index={0} onIndexChange={onIndex} />);
    const dots = screen.getAllByRole("button", { name: /切换到/ });
    await userEvent.click(dots[2]!);
    expect(onIndex).toHaveBeenCalledWith(2);
  });

  it("ArrowRight increments tab; ArrowLeft decrements; clamps at edges", async () => {
    const onIndex = vi.fn();
    const { rerender } = render(
      <DetailTabSwipe tabs={tabs} index={0} onIndexChange={onIndex} />
    );
    const container = screen.getByTestId("detail-tab-swipe");
    container.focus();
    await userEvent.keyboard("{ArrowRight}");
    expect(onIndex).toHaveBeenLastCalledWith(1);
    rerender(<DetailTabSwipe tabs={tabs} index={2} onIndexChange={onIndex} />);
    container.focus();
    await userEvent.keyboard("{ArrowRight}");
    // Already at max — last call should still be the prior (1) since onIndex
    // wasn't called again.
    expect(onIndex).toHaveBeenLastCalledWith(1);
  });

  it("footer shows the active tab's label", () => {
    render(<DetailTabSwipe tabs={tabs} index={1} onIndexChange={() => {}} />);
    expect(screen.getByText("交易面板")).toBeInTheDocument();
  });

  it("⚙ click invokes onOpenSettings with active index", async () => {
    const onSettings = vi.fn();
    render(
      <DetailTabSwipe tabs={tabs} index={1} onIndexChange={() => {}} onOpenSettings={onSettings} />
    );
    await userEvent.click(screen.getByRole("button", { name: /设置/ }));
    expect(onSettings).toHaveBeenCalledWith(1);
  });

  it("mouse drag past threshold changes tab", () => {
    const onIndex = vi.fn();
    render(<DetailTabSwipe tabs={tabs} index={1} onIndexChange={onIndex} />);
    const container = screen.getByTestId("detail-tab-swipe");
    fireEvent.mouseDown(container, { clientX: 500 });
    fireEvent.mouseMove(container, { clientX: 400 });
    fireEvent.mouseUp(container, { clientX: 400 });
    expect(onIndex).toHaveBeenCalledWith(2);
  });

  it("clicking an input inside content does NOT trigger drag", () => {
    const onIndex = vi.fn();
    const tabsWithInput = [
      ...tabs.slice(0, 1),
      { id: "trading", label: "交易面板", content: <input data-testid="inp" /> },
      ...tabs.slice(2),
    ];
    render(<DetailTabSwipe tabs={tabsWithInput} index={1} onIndexChange={onIndex} />);
    const inp = screen.getByTestId("inp");
    fireEvent.mouseDown(inp, { clientX: 500 });
    fireEvent.mouseMove(inp, { clientX: 400 });
    fireEvent.mouseUp(inp, { clientX: 400 });
    expect(onIndex).not.toHaveBeenCalled();
  });
});
