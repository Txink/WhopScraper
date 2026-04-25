import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { usePageTabsStore } from "../../stores/pageTabs";
import * as httpModule from "../../api/http";
import { PageActionBar } from "./PageActionBar";

const stockPage = {
  id: "a", url: "u", source: "stock" as const, name: "S", added_at: "2026-04-25T00:00:00Z",
  settings: { dedupe_processed_messages: true, price_deviation_tolerance: 1, block_non_today_messages: false, tickers: {} },
  running: true, started_at: null, last_poll_at: null, messages_published: 0, last_error: null,
};

describe("<PageActionBar>", () => {
  beforeEach(() => { usePageTabsStore.getState().reset(); });

  it("disables power/settings when orphan", () => {
    render(<PageActionBar page={null} mode="orphan" onOpenSettings={vi.fn()} />);
    expect(screen.getByLabelText("开机")).toBeDisabled();
    expect(screen.getByLabelText("设置")).toBeDisabled();
  });

  it("does not crash when mode=page but page is null", () => {
    render(<PageActionBar page={null} mode="page" onOpenSettings={vi.fn()} />);
    expect(screen.getByLabelText("开机")).toBeDisabled();
    expect(screen.getByLabelText("设置")).toBeDisabled();
  });

  it("clicks start when page is off", async () => {
    const stockPageOff = { ...stockPage, running: false, last_error: null };
    const startSpy = vi.spyOn(httpModule.api, "startWhopPage").mockResolvedValue(stockPageOff);
    render(<PageActionBar page={stockPageOff} mode="page" onOpenSettings={vi.fn()} />);
    fireEvent.click(screen.getByLabelText("开机"));
    await waitFor(() => expect(startSpy).toHaveBeenCalledWith("a"));
  });

  it("clicks stop when page is on", async () => {
    const stockPageOn = { ...stockPage, running: true, last_error: null };
    const stopSpy = vi.spyOn(httpModule.api, "stopWhopPage").mockResolvedValue(stockPageOn);
    render(<PageActionBar page={stockPageOn} mode="page" onOpenSettings={vi.fn()} />);
    fireEvent.click(screen.getByLabelText("关机"));
    await waitFor(() => expect(stopSpy).toHaveBeenCalledWith("a"));
  });

  it("error state shows red icon with last_error tooltip", () => {
    const errPage = { ...stockPage, running: false, last_error: "navigate failed" };
    render(<PageActionBar page={errPage} mode="page" onOpenSettings={vi.fn()} />);
    const btn = screen.getByLabelText("错误，点击重试");
    expect(btn).toHaveAttribute("title", "错误：navigate failed");
  });

  it("expand mode button cycles smart → all-open → all-closed → smart", () => {
    render(<PageActionBar page={stockPage} mode="page" onOpenSettings={vi.fn()} />);
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
    const { container } = render(<PageActionBar page={stockPage} mode="page" onOpenSettings={vi.fn()} />);
    // Initial state: smart, no engaged class
    expect(container.querySelector(".action-btn.engaged")).not.toBeInTheDocument();
    // Cycle once → all-open → engaged
    fireEvent.click(screen.getByText(/智能展开/));
    expect(container.querySelector(".action-btn.engaged")).toBeInTheDocument();
  });
});
