import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { usePageTabsStore } from "../../stores/pageTabs";
import { PageActionBar } from "./PageActionBar";

const stockPage = {
  id: "a", url: "u", source: "stock" as const, name: "S", added_at: "2026-04-25T00:00:00Z",
  settings: { dedupe_processed_messages: true, price_deviation_tolerance: 1, tickers: {} },
  running: true, started_at: null, last_poll_at: null, messages_published: 0, last_error: null,
};

describe("<PageActionBar>", () => {
  beforeEach(() => { usePageTabsStore.getState().reset(); });

  it("disables restart/settings when orphan", () => {
    render(<PageActionBar page={null} onOpenSettings={vi.fn()} />);
    expect(screen.getByText(/重启/)).toBeDisabled();
    expect(screen.getByText(/设置/)).toBeDisabled();
  });

  it("expand mode button cycles smart → all-open → all-closed → smart", () => {
    render(<PageActionBar page={stockPage} onOpenSettings={vi.fn()} />);
    // Initial: smart
    const initialBtn = screen.getByText(/智能展开/);
    expect(initialBtn).toBeInTheDocument();

    // Click 1: smart → all-open
    fireEvent.click(initialBtn);
    expect(usePageTabsStore.getState().expandModeByTab["a"]).toBe("all-open");
    expect(screen.getByText(/全部展开/)).toBeInTheDocument();

    // Click 2: all-open → all-closed
    fireEvent.click(screen.getByText(/全部展开/));
    expect(usePageTabsStore.getState().expandModeByTab["a"]).toBe("all-closed");
    expect(screen.getByText(/全部收起/)).toBeInTheDocument();

    // Click 3: all-closed → smart
    fireEvent.click(screen.getByText(/全部收起/));
    expect(usePageTabsStore.getState().expandModeByTab["a"]).toBe("smart");
    expect(screen.getByText(/智能展开/)).toBeInTheDocument();
  });

  it("expand button gets engaged class when not in smart mode", () => {
    const { container } = render(<PageActionBar page={stockPage} onOpenSettings={vi.fn()} />);
    // Initial state: smart, no engaged class
    expect(container.querySelector(".action-btn.engaged")).not.toBeInTheDocument();
    // Cycle once → all-open → engaged
    fireEvent.click(screen.getByText(/智能展开/));
    expect(container.querySelector(".action-btn.engaged")).toBeInTheDocument();
  });
});
