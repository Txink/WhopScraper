import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { PageInfoBar } from "./PageInfoBar";

const stockPage = {
  id: "a", url: "https://w/a/", source: "stock" as const, name: "Hello",
  added_at: "2026-04-25T00:00:00Z",
  settings: { dedupe_processed_messages: true, price_deviation_tolerance: 1, tickers: {} },
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

  it("renders orphan view", () => {
    render(<PageInfoBar page={null} orphanCount={5} />);
    expect(screen.getByText("已停用")).toBeInTheDocument();
    expect(screen.getByText(/5 条历史/)).toBeInTheDocument();
  });
});
