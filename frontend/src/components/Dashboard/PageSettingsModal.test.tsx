import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import * as httpModule from "../../api/http";
import { PageSettingsModal } from "./PageSettingsModal";
import type { WhopPage } from "../../api/domain-types";

const stockPage: WhopPage = {
  id: "a", url: "u", source: "stock", name: "S", added_at: "2026-04-25T00:00:00Z",
  settings: {
    dedupe_processed_messages: true,
    price_deviation_tolerance: 1.0,
    block_non_today_messages: false,
    launch_headless: false,
    tickers: { TSLL: { trade_quantity: 2000 } },
    option_buy_quantity_enabled: false,
    option_buy_quantity: null,
    option_total_price_limit_enabled: false,
    option_total_price_limit: null,
  },
  running: true, started_at: null, last_poll_at: null, messages_published: 0, last_error: null,
};

const optionPage: WhopPage = {
  ...stockPage, id: "b", source: "option",
  settings: {
    dedupe_processed_messages: true,
    price_deviation_tolerance: 5.0,
    block_non_today_messages: false,
    launch_headless: false,
    tickers: null,
    option_buy_quantity_enabled: false,
    option_buy_quantity: null,
    option_total_price_limit_enabled: false,
    option_total_price_limit: null,
  },
};

describe("<PageSettingsModal>", () => {
  beforeEach(() => { vi.restoreAllMocks(); });

  it("stock modal shows ticker editor; option modal hides it", () => {
    const { unmount } = render(<PageSettingsModal page={stockPage} onClose={vi.fn()} />);
    expect(screen.getByText(/股票配置/)).toBeInTheDocument();
    unmount();
    render(<PageSettingsModal page={optionPage} onClose={vi.fn()} />);
    expect(screen.queryByText(/股票配置/)).not.toBeInTheDocument();
  });

  it("editing ticker uppercases the key on save", async () => {
    const spy = vi.spyOn(httpModule.api, "updateWhopPageSettings").mockResolvedValue(stockPage);
    render(<PageSettingsModal page={stockPage} onClose={vi.fn()} />);
    fireEvent.click(screen.getByText(/添加 ticker/));
    const tickerInputs = screen.getAllByPlaceholderText(/输入 ticker/);
    fireEvent.change(tickerInputs[tickerInputs.length - 1], { target: { value: "nvda" } });
    const qtyInputs = screen.getAllByPlaceholderText(/数量/);
    fireEvent.change(qtyInputs[qtyInputs.length - 1], { target: { value: "500" } });
    fireEvent.click(screen.getByText(/^保存/));
    await waitFor(() => expect(spy).toHaveBeenCalled());
    const arg = spy.mock.calls[0][1];
    expect(arg.tickers).toMatchObject({ NVDA: { trade_quantity: 500 } });
  });

  it("toggling dedupe shows hint about restart", () => {
    render(<PageSettingsModal page={stockPage} onClose={vi.fn()} />);
    const checkbox = screen.getByLabelText(/避免重复解析/);
    fireEvent.click(checkbox);
    expect(screen.getByText(/下次重启监听才生效/)).toBeInTheDocument();
  });

  it("invalid tolerance (negative) blocks save", async () => {
    const spy = vi.spyOn(httpModule.api, "updateWhopPageSettings").mockResolvedValue(stockPage);
    render(<PageSettingsModal page={stockPage} onClose={vi.fn()} />);
    const input = screen.getByLabelText(/价格偏差容忍/);
    fireEvent.change(input, { target: { value: "-1" } });
    fireEvent.click(screen.getByText(/^保存/));
    await waitFor(() => expect(screen.getByText(/必须 ≥ 0/)).toBeInTheDocument());
    expect(spy).not.toHaveBeenCalled();
  });

  it("toggling block_non_today_messages saves it", async () => {
    const spy = vi.spyOn(httpModule.api, "updateWhopPageSettings").mockResolvedValue(stockPage);
    render(<PageSettingsModal page={stockPage} onClose={vi.fn()} />);
    const checkbox = screen.getByLabelText(/禁止下单非当天/);
    fireEvent.click(checkbox);
    fireEvent.click(screen.getByText(/^保存/));
    await waitFor(() => expect(spy).toHaveBeenCalled());
    const arg = spy.mock.calls[0][1];
    expect(arg.block_non_today_messages).toBe(true);
  });

  it("toggling launch_headless saves it", async () => {
    const spy = vi.spyOn(httpModule.api, "updateWhopPageSettings").mockResolvedValue(stockPage);
    render(<PageSettingsModal page={stockPage} onClose={vi.fn()} />);
    const checkbox = screen.getByLabelText(/无头模式启动网页/);
    fireEvent.click(checkbox);
    fireEvent.click(screen.getByText(/^保存/));
    await waitFor(() => expect(spy).toHaveBeenCalled());
    const arg = spy.mock.calls[0][1];
    expect(arg.launch_headless).toBe(true);
  });

  it("option modal shows local option controls", () => {
    render(<PageSettingsModal page={optionPage} onClose={vi.fn()} />);
    expect(screen.getByText(/期权购买数量配置/)).toBeInTheDocument();
    expect(screen.getByLabelText(/启用期权购买张数/)).toBeInTheDocument();
    expect(screen.getByLabelText(/启用期权总价上限/)).toBeInTheDocument();
  });

  it("option modal saves selected option rules", async () => {
    const spy = vi.spyOn(httpModule.api, "updateWhopPageSettings").mockResolvedValue(optionPage);
    render(<PageSettingsModal page={optionPage} onClose={vi.fn()} />);

    fireEvent.click(screen.getByLabelText(/启用期权购买张数/));
    fireEvent.change(screen.getByPlaceholderText(/期权购买张数/), { target: { value: "3" } });
    fireEvent.click(screen.getByLabelText(/启用期权总价上限/));
    fireEvent.change(screen.getByPlaceholderText(/期权总价上限/), { target: { value: "1200" } });

    fireEvent.click(screen.getByText(/^保存/));
    await waitFor(() => expect(spy).toHaveBeenCalled());
    const arg = spy.mock.calls[0][1];
    expect(arg.option_buy_quantity_enabled).toBe(true);
    expect(arg.option_buy_quantity).toBe(3);
    expect(arg.option_total_price_limit_enabled).toBe(true);
    expect(arg.option_total_price_limit).toBe(1200);
  });

  it("shows listener diagnostics block", () => {
    const pageWithRuntime: WhopPage = {
      ...stockPage,
      running: true,
      started_at: "2026-04-25T10:00:00Z",
      last_poll_at: "2026-04-25T10:01:00Z",
      messages_published: 12,
      last_error: null,
    };
    render(<PageSettingsModal page={pageWithRuntime} onClose={vi.fn()} />);
    expect(screen.getByText(/监听诊断/)).toBeInTheDocument();
    expect(screen.getByText("运行中")).toBeInTheDocument();
    expect(screen.getByText("12")).toBeInTheDocument();
    expect(screen.getByText("无")).toBeInTheDocument();
  });
});
