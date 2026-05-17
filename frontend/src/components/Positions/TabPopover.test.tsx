import { describe, it, expect, vi } from "vitest";
import { render, fireEvent, act } from "@testing-library/react";
import { useRef } from "react";
import { TabPopover } from "./TabPopover";

function Host({ open, onClose }: { open: boolean; onClose: () => void }) {
  const anchorRef = useRef<HTMLButtonElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  return (
    <div ref={containerRef} style={{ position: "relative", width: 600, height: 300 }}>
      <button ref={anchorRef}>anchor</button>
      <TabPopover
        open={open}
        anchorRef={anchorRef}
        containerRef={containerRef}
        onClose={onClose}
      >
        <span data-testid="content">popover content</span>
      </TabPopover>
    </div>
  );
}

describe("TabPopover", () => {
  it("renders nothing when open=false", () => {
    const { queryByTestId } = render(<Host open={false} onClose={() => {}} />);
    expect(queryByTestId("content")).toBeNull();
  });

  it("renders children when open=true", () => {
    const { getByTestId } = render(<Host open={true} onClose={() => {}} />);
    expect(getByTestId("content")).toBeInTheDocument();
  });

  it("calls onClose when Escape is pressed", () => {
    const onClose = vi.fn();
    render(<Host open={true} onClose={onClose} />);
    act(() => {
      fireEvent.keyDown(document, { key: "Escape" });
    });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("calls onClose when clicking outside the popover", () => {
    const onClose = vi.fn();
    const { container } = render(<Host open={true} onClose={onClose} />);
    // Click on a node that is neither the popover nor the anchor.
    const outside = container.firstChild as HTMLElement; // the container div itself
    act(() => {
      fireEvent.mouseDown(outside);
    });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("does NOT call onClose when clicking inside the popover", () => {
    const onClose = vi.fn();
    const { getByTestId } = render(<Host open={true} onClose={onClose} />);
    act(() => {
      fireEvent.mouseDown(getByTestId("content"));
    });
    expect(onClose).not.toHaveBeenCalled();
  });
});
