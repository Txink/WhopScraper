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
  it("renders running page", () => {
    render(<PageInfoBar page={stockPage} />);
    expect(screen.getByText("正股")).toBeInTheDocument();
    expect(screen.getByText("Hello")).toBeInTheDocument();
    expect(screen.getByText("运行中")).toBeInTheDocument();
    expect(screen.getByText(/已发消息\s*42/)).toBeInTheDocument();
  });

  it("renders orphan view", () => {
    render(<PageInfoBar page={null} orphanCount={5} />);
    expect(screen.getByText("已停用")).toBeInTheDocument();
    expect(screen.getByText(/5 条历史/)).toBeInTheDocument();
  });
});
