import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { PageInfoBar } from "./PageInfoBar";

const stockPage = {
  id: "a", url: "https://w/a/", source: "stock" as const, name: "Hello",
  added_at: "2026-04-25T00:00:00Z",
  settings: { dedupe_processed_messages: true, price_deviation_tolerance: 1, block_historical_messages: false, launch_headless: false, tickers: {} },
  running: true, started_at: null, last_poll_at: null, messages_published: 42, last_error: null,
};

describe("<PageInfoBar>", () => {
  it("renders page with url link and basic info", () => {
    render(<PageInfoBar page={stockPage} />);
    expect(screen.getByText("正股")).toBeInTheDocument();
    expect(screen.getByText("Hello")).toBeInTheDocument();
    // Status moved to the power button — should be absent here.
    expect(screen.queryByText(/运行中/)).toBeNull();
    const urlLink = screen.getByRole("link");
    expect(urlLink).toHaveAttribute("href", stockPage.url);
    expect(urlLink).toHaveAttribute("target", "_blank");
    expect(screen.getByText(/已发消息\s*42/)).toBeInTheDocument();
  });

  it("renders nothing when page is null", () => {
    const { container } = render(<PageInfoBar page={null} />);
    expect(container.firstChild).toBeNull();
  });
});

describe("<PageInfoBar> new-messages indicator", () => {
  it("renders 已发消息 count by default", () => {
    render(<PageInfoBar page={stockPage} />);
    expect(screen.getByText(/已发消息\s*42/)).toBeInTheDocument();
    expect(screen.queryByText(/新消息 \+/)).toBeNull();
  });

  it("replaces 已发消息 with 新消息 +K when newMessageCount > 0", () => {
    render(
      <PageInfoBar
        page={stockPage}
        newMessageCount={3}
        onJumpToCurrent={vi.fn()}
      />,
    );
    const btn = screen.getByRole("button", { name: /新消息 \+3/ });
    expect(btn).toBeInTheDocument();
    expect(btn).toHaveClass("page-info-new-msg");
    expect(screen.queryByText(/已发消息/)).toBeNull();
  });

  it("calls onJumpToCurrent when the indicator is clicked", () => {
    const onJump = vi.fn();
    render(
      <PageInfoBar
        page={stockPage}
        newMessageCount={5}
        onJumpToCurrent={onJump}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /新消息 \+5/ }));
    expect(onJump).toHaveBeenCalledTimes(1);
  });

  it("falls back to 已发消息 when newMessageCount is 0", () => {
    render(
      <PageInfoBar
        page={stockPage}
        newMessageCount={0}
        onJumpToCurrent={vi.fn()}
      />,
    );
    expect(screen.getByText(/已发消息\s*42/)).toBeInTheDocument();
    expect(screen.queryByText(/新消息 \+/)).toBeNull();
  });
});
