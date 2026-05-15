import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { usePageTabsStore } from "../../stores/pageTabs";
import * as httpModule from "../../api/http";
import { PageActionBar } from "./PageActionBar";

const stockPage = {
  id: "a", url: "u", source: "stock" as const, name: "S", added_at: "2026-04-25T00:00:00Z",
  settings: { dedupe_processed_messages: true, price_deviation_tolerance: 1, block_historical_messages: false, tickers: {} },
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

  it("running listener with last_error shows red (last_error wins over running)", () => {
    const errPage = { ...stockPage, running: true, last_error: "scrape timeout" };
    render(<PageActionBar page={errPage} mode="page" onOpenSettings={vi.fn()} />);
    const btn = screen.getByLabelText("错误，点击关机");
    expect(btn).toHaveAttribute("title", "错误：scrape timeout");
    expect(btn.className).toContain("err");
    expect(btn.className).not.toMatch(/\bon\b/);
  });

  it("clicks stop when red button is clicked while running with error", async () => {
    const errPage = { ...stockPage, running: true, last_error: "scrape timeout" };
    const stopSpy = vi.spyOn(httpModule.api, "stopWhopPage").mockResolvedValue(errPage);
    render(<PageActionBar page={errPage} mode="page" onOpenSettings={vi.fn()} />);
    fireEvent.click(screen.getByLabelText("错误，点击关机"));
    await waitFor(() => expect(stopSpy).toHaveBeenCalledWith("a"));
  });

  it("does not render the expand-mode toggle button (single-accordion is fixed)", () => {
    // Regression: the tri-state expand toggle was removed in favor of a
    // single-accordion behavior driven by TaskStream + pageTabsStore.
    // Action bar should only show 2 buttons now (power + settings).
    const { container } = render(
      <PageActionBar page={stockPage} mode="page" onOpenSettings={vi.fn()} />,
    );
    expect(container.querySelectorAll(".page-action-bar button")).toHaveLength(2);
    expect(screen.queryByLabelText("智能展开")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("全部展开")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("全部收起")).not.toBeInTheDocument();
  });
});
