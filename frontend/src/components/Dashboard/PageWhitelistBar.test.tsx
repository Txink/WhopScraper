import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import * as httpModule from "../../api/http";
import { PageWhitelistBar } from "./PageWhitelistBar";
import type { WhopPage } from "../../api/domain-types";

function makePage(tickers: Record<string, { trade_quantity: number }> | null = null): WhopPage {
  return {
    id: "page-1",
    url: "https://whop.com/joined/x/y/app/",
    source: "stock",
    name: "正股发布",
    added_at: "2026-04-25T00:00:00Z",
    settings: {
      dedupe_processed_messages: true,
      price_deviation_tolerance: 1.0,
      block_non_today_messages: false,
      launch_headless: true,
      tickers,
      option_buy_quantity_enabled: false,
      option_buy_quantity: null,
      option_total_price_limit_enabled: false,
      option_total_price_limit: null,
    },
    running: true,
    started_at: null,
    last_poll_at: null,
    messages_published: 0,
    last_error: null,
  };
}

describe("<PageWhitelistBar>", () => {
  beforeEach(() => { vi.restoreAllMocks(); });

  it("renders ticker chips sorted alphabetically", () => {
    const page = makePage({
      TSLL: { trade_quantity: 2000 },
      CONL: { trade_quantity: 1000 },
      AAPL: { trade_quantity: 100 },
    });
    render(<PageWhitelistBar page={page} />);
    const chips = screen.getAllByRole("button").filter(b => b.classList.contains("ticker-chip"));
    expect(chips.map(c => c.textContent)).toEqual([
      expect.stringContaining("AAPL.US"),
      expect.stringContaining("CONL.US"),
      expect.stringContaining("TSLL.US"),
    ]);
  });

  it("clicking a chip removes that ticker via PATCH", async () => {
    const spy = vi.spyOn(httpModule.api, "updateWhopPageSettings")
      .mockResolvedValue(makePage({ TSLL: { trade_quantity: 2000 } }));
    const page = makePage({
      TSLL: { trade_quantity: 2000 },
      CONL: { trade_quantity: 1000 },
    });
    render(<PageWhitelistBar page={page} />);
    fireEvent.click(screen.getByLabelText("删除 CONL"));
    await waitFor(() => expect(spy).toHaveBeenCalled());
    const arg = spy.mock.calls[0][1];
    expect(arg.tickers).toEqual({ TSLL: { trade_quantity: 2000 } });
  });

  it("shows empty hint when no tickers configured", () => {
    render(<PageWhitelistBar page={makePage(null)} />);
    expect(screen.getByText(/未配置/)).toBeInTheDocument();
  });

  it("'+' button opens an inline form", () => {
    render(<PageWhitelistBar page={makePage()} />);
    fireEvent.click(screen.getByLabelText("添加 ticker"));
    expect(screen.getByPlaceholderText("ticker")).toBeInTheDocument();
    expect(screen.getByPlaceholderText("qty")).toBeInTheDocument();
    expect(screen.getByLabelText("确认添加")).toBeInTheDocument();
    expect(screen.getByLabelText("取消")).toBeInTheDocument();
  });

  it("submitting the inline form uppercases ticker and PATCHes new map", async () => {
    const spy = vi.spyOn(httpModule.api, "updateWhopPageSettings")
      .mockResolvedValue(makePage());
    render(<PageWhitelistBar page={makePage({ TSLL: { trade_quantity: 2000 } })} />);
    fireEvent.click(screen.getByLabelText("添加 ticker"));
    fireEvent.change(screen.getByPlaceholderText("ticker"), { target: { value: "nvda" } });
    fireEvent.change(screen.getByPlaceholderText("qty"), { target: { value: "500" } });
    fireEvent.click(screen.getByLabelText("确认添加"));
    await waitFor(() => expect(spy).toHaveBeenCalled());
    const arg = spy.mock.calls[0][1];
    expect(arg.tickers).toEqual({
      TSLL: { trade_quantity: 2000 },
      NVDA: { trade_quantity: 500 },
    });
  });

  it("rejects empty ticker", async () => {
    const spy = vi.spyOn(httpModule.api, "updateWhopPageSettings");
    render(<PageWhitelistBar page={makePage()} />);
    fireEvent.click(screen.getByLabelText("添加 ticker"));
    fireEvent.change(screen.getByPlaceholderText("qty"), { target: { value: "100" } });
    fireEvent.click(screen.getByLabelText("确认添加"));
    expect(spy).not.toHaveBeenCalled();
    expect(screen.getByRole("alert")).toHaveTextContent("ticker 不能为空");
  });

  it("rejects non-positive quantity", async () => {
    const spy = vi.spyOn(httpModule.api, "updateWhopPageSettings");
    render(<PageWhitelistBar page={makePage()} />);
    fireEvent.click(screen.getByLabelText("添加 ticker"));
    fireEvent.change(screen.getByPlaceholderText("ticker"), { target: { value: "AAPL" } });
    fireEvent.change(screen.getByPlaceholderText("qty"), { target: { value: "0" } });
    fireEvent.click(screen.getByLabelText("确认添加"));
    expect(spy).not.toHaveBeenCalled();
    expect(screen.getByRole("alert")).toHaveTextContent(/数量必须是 > 0/);
  });

  it("rejects duplicate ticker", async () => {
    const spy = vi.spyOn(httpModule.api, "updateWhopPageSettings");
    render(<PageWhitelistBar page={makePage({ TSLL: { trade_quantity: 2000 } })} />);
    fireEvent.click(screen.getByLabelText("添加 ticker"));
    fireEvent.change(screen.getByPlaceholderText("ticker"), { target: { value: "tsll" } });
    fireEvent.change(screen.getByPlaceholderText("qty"), { target: { value: "100" } });
    fireEvent.click(screen.getByLabelText("确认添加"));
    expect(spy).not.toHaveBeenCalled();
    expect(screen.getByRole("alert")).toHaveTextContent(/已存在/);
  });

  it("cancel button closes the inline form without PATCH", () => {
    const spy = vi.spyOn(httpModule.api, "updateWhopPageSettings");
    render(<PageWhitelistBar page={makePage()} />);
    fireEvent.click(screen.getByLabelText("添加 ticker"));
    fireEvent.click(screen.getByLabelText("取消"));
    expect(screen.queryByPlaceholderText("ticker")).not.toBeInTheDocument();
    expect(spy).not.toHaveBeenCalled();
  });
});
