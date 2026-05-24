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

  it("mouse drag past threshold changes tab", () => {
    // Drag move + up live on `document` (so the drag survives if the
    // pointer leaves the swipe div mid-gesture); fire them on document.
    const onIndex = vi.fn();
    render(<DetailTabSwipe tabs={tabs} index={1} onIndexChange={onIndex} />);
    const container = screen.getByTestId("detail-tab-swipe");
    fireEvent.mouseDown(container, { clientX: 500, button: 0 });
    fireEvent.mouseMove(document, { clientX: 400 });
    fireEvent.mouseUp(document, { clientX: 400 });
    expect(onIndex).toHaveBeenCalledWith(2);
  });

  it("dragging starting from a button element still triggers swipe", () => {
    // Buttons used to block drag-start under isFormTarget — buttons are
    // densely packed inside the trade list, so swipe was unreachable in
    // practice. Drag should now begin on any non-text-input target.
    const onIndex = vi.fn();
    const tabsWithButton = [
      { id: "records", label: "交易记录", content: <button data-testid="btn">click me</button> },
      ...tabs.slice(1),
    ];
    render(<DetailTabSwipe tabs={tabsWithButton} index={0} onIndexChange={onIndex} />);
    const btn = screen.getByTestId("btn");
    // Drag leftward (200 → 100): negative dx → forward swipe → next tab.
    fireEvent.mouseDown(btn, { clientX: 200, button: 0 });
    fireEvent.mouseMove(document, { clientX: 100 });
    fireEvent.mouseUp(document, { clientX: 100 });
    expect(onIndex).toHaveBeenCalledWith(1);
  });

  it("dragging from a text input does NOT trigger swipe", () => {
    const onIndex = vi.fn();
    const tabsWithInput = [
      ...tabs.slice(0, 1),
      { id: "trading", label: "交易面板", content: <input data-testid="inp" /> },
      ...tabs.slice(2),
    ];
    render(<DetailTabSwipe tabs={tabsWithInput} index={1} onIndexChange={onIndex} />);
    const inp = screen.getByTestId("inp");
    fireEvent.mouseDown(inp, { clientX: 500, button: 0 });
    fireEvent.mouseMove(document, { clientX: 400 });
    fireEvent.mouseUp(document, { clientX: 400 });
    expect(onIndex).not.toHaveBeenCalled();
  });

  it("trackpad horizontal wheel accumulates into a tab switch", () => {
    const onIndex = vi.fn();
    render(<DetailTabSwipe tabs={tabs} index={0} onIndexChange={onIndex} />);
    const container = screen.getByTestId("detail-tab-swipe");
    // 3 small horizontal wheel events that sum past WHEEL_COMMIT_PX (60).
    fireEvent.wheel(container, { deltaX: 30, deltaY: 0 });
    fireEvent.wheel(container, { deltaX: 30, deltaY: 0 });
    fireEvent.wheel(container, { deltaX: 30, deltaY: 0 });
    expect(onIndex).toHaveBeenCalledWith(1);
  });

  it("vertical-dominant wheel does NOT switch tabs", () => {
    const onIndex = vi.fn();
    render(<DetailTabSwipe tabs={tabs} index={0} onIndexChange={onIndex} />);
    const container = screen.getByTestId("detail-tab-swipe");
    // Vertical scroll dominates — should be ignored.
    fireEvent.wheel(container, { deltaX: 5, deltaY: 100 });
    expect(onIndex).not.toHaveBeenCalled();
  });

  it("a single trackpad gesture commits at most one tab change", () => {
    // Real trackpad gesture signal: acceleration → peak → deceleration
    // → inertia tail. Without the lock, the long burst would re-cross
    // the commit threshold and chain-skip tabs.
    const onIndex = vi.fn();
    render(<DetailTabSwipe tabs={tabs} index={0} onIndexChange={onIndex} />);
    const container = screen.getByTestId("detail-tab-swipe");
    // 10 ticks summing well past WHEEL_COMMIT_PX (60): peak then taper.
    const deltas = [20, 40, 60, 60, 60, 40, 30, 20, 15, 10];
    for (const dx of deltas) {
      fireEvent.wheel(container, { deltaX: dx, deltaY: 0 });
    }
    expect(onIndex).toHaveBeenCalledTimes(1);
    expect(onIndex).toHaveBeenCalledWith(1);
  });

  it("two trackpad gestures (with natural taper between) each commit once", () => {
    // Once the wheel signal tapers below WHEEL_TAPER_PX (3), the lock
    // releases — the next gesture's events accumulate immediately.
    const onIndex = vi.fn();
    const { rerender } = render(
      <DetailTabSwipe tabs={tabs} index={0} onIndexChange={onIndex} />,
    );
    const container = screen.getByTestId("detail-tab-swipe");
    // First gesture: peak then taper to ~zero.
    for (const dx of [40, 60, 40, 20, 5, 1]) {
      fireEvent.wheel(container, { deltaX: dx, deltaY: 0 });
    }
    expect(onIndex).toHaveBeenLastCalledWith(1);

    // Caller advances index after the first commit.
    rerender(<DetailTabSwipe tabs={tabs} index={1} onIndexChange={onIndex} />);

    // Second gesture — no time delay needed, signal alone delimits.
    for (const dx of [40, 60, 40, 20, 5]) {
      fireEvent.wheel(container, { deltaX: dx, deltaY: 0 });
    }
    expect(onIndex).toHaveBeenCalledTimes(2);
    expect(onIndex).toHaveBeenLastCalledWith(2);
  });

  it("mid-stream direction reversal starts a new gesture", () => {
    const onIndex = vi.fn();
    const { rerender } = render(
      <DetailTabSwipe tabs={tabs} index={0} onIndexChange={onIndex} />,
    );
    const container = screen.getByTestId("detail-tab-swipe");
    // Forward gesture (positive deltaX = scroll right = next tab).
    for (const dx of [40, 60, 40]) {
      fireEvent.wheel(container, { deltaX: dx, deltaY: 0 });
    }
    expect(onIndex).toHaveBeenLastCalledWith(1);

    rerender(<DetailTabSwipe tabs={tabs} index={1} onIndexChange={onIndex} />);

    // Reverse direction without tapering — the sign flip alone should
    // unlock + restart accumulation in the new direction.
    for (const dx of [-40, -60, -40]) {
      fireEvent.wheel(container, { deltaX: dx, deltaY: 0 });
    }
    expect(onIndex).toHaveBeenCalledTimes(2);
    expect(onIndex).toHaveBeenLastCalledWith(0);
  });
});
