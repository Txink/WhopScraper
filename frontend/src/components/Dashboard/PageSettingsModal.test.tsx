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
    tickers: { TSLL: { trade_quantity: 2000 } },
  },
  running: true, started_at: null, last_poll_at: null, messages_published: 0, last_error: null,
};

const optionPage: WhopPage = {
  ...stockPage, id: "b", source: "option",
  settings: {
    dedupe_processed_messages: true,
    price_deviation_tolerance: 5.0,
    block_non_today_messages: false,
    tickers: null,
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
});
