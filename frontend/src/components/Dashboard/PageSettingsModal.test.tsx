import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import * as httpModule from "../../api/http";
import { PageSettingsModal } from "./PageSettingsModal";
import type { WhopPage } from "../../api/domain-types";
import { useChildPagesStore } from "../../stores/childPages";

const stockPage: WhopPage = {
  id: "a", url: "u", source: "stock", name: "S", added_at: "2026-04-25T00:00:00Z",
  settings: {
    dedupe_processed_messages: true,
    price_deviation_tolerance: 1.0,
    block_historical_messages: false,
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
    block_historical_messages: false,
    launch_headless: false,
    tickers: null,
    option_buy_quantity_enabled: false,
    option_buy_quantity: null,
    option_total_price_limit_enabled: false,
    option_total_price_limit: null,
  },
};

const chatPage: WhopPage = {
  ...stockPage, id: "c", source: "chat", name: "Chat",
  settings: {
    dedupe_processed_messages: false,
    price_deviation_tolerance: 0,
    block_historical_messages: false,
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

  it("ticker whitelist editor is no longer in the settings modal (moved to PageWhitelistBar)", () => {
    // Whitelist editing is now inline below the page header — see PageWhitelistBar.
    // The settings modal should not surface 股票配置 or any ticker editing UI.
    render(<PageSettingsModal page={stockPage} onClose={vi.fn()} />);
    expect(screen.queryByText(/股票配置/)).not.toBeInTheDocument();
    expect(screen.queryByPlaceholderText(/输入 ticker/)).not.toBeInTheDocument();
  });

  it("save patch never sends tickers — backend's per-field merge keeps existing whitelist", async () => {
    const spy = vi.spyOn(httpModule.api, "updateWhopPageSettings").mockResolvedValue(stockPage);
    render(<PageSettingsModal page={stockPage} onClose={vi.fn()} />);
    fireEvent.click(screen.getByText(/^保存/));
    await waitFor(() => expect(spy).toHaveBeenCalled());
    const arg = spy.mock.calls[0][1];
    expect(arg).not.toHaveProperty("tickers");
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

  it("toggling block_historical_messages saves it", async () => {
    const spy = vi.spyOn(httpModule.api, "updateWhopPageSettings").mockResolvedValue(stockPage);
    render(<PageSettingsModal page={stockPage} onClose={vi.fn()} />);
    const checkbox = screen.getByLabelText(/禁止下单历史消息/);
    fireEvent.click(checkbox);
    fireEvent.click(screen.getByText(/^保存/));
    await waitFor(() => expect(spy).toHaveBeenCalled());
    const arg = spy.mock.calls[0][1];
    expect(arg.block_historical_messages).toBe(true);
    expect("block_non_today_messages" in arg).toBe(false);
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

  it("toggling parser_version checkbox saves it as v2", async () => {
    const spy = vi.spyOn(httpModule.api, "updateWhopPageSettings").mockResolvedValue(stockPage);
    render(<PageSettingsModal page={stockPage} onClose={vi.fn()} />);
    const checkbox = screen.getByLabelText(/parser v2/i);
    fireEvent.click(checkbox);
    fireEvent.click(screen.getByText(/^保存/));
    await waitFor(() => expect(spy).toHaveBeenCalled());
    const arg = spy.mock.calls[0][1];
    expect(arg.parser_version).toBe("v2");
  });

  it("checkbox initial state reflects existing parser_version=v2", async () => {
    const v2Page: WhopPage = {
      ...stockPage,
      settings: { ...stockPage.settings, parser_version: "v2" },
    };
    const spy = vi.spyOn(httpModule.api, "updateWhopPageSettings").mockResolvedValue(v2Page);
    render(<PageSettingsModal page={v2Page} onClose={vi.fn()} />);
    const checkbox = screen.getByLabelText(/parser v2/i) as HTMLInputElement;
    expect(checkbox.checked).toBe(true);
    fireEvent.click(checkbox); // unchecks
    fireEvent.click(screen.getByText(/^保存/));
    await waitFor(() => expect(spy).toHaveBeenCalled());
    const arg = spy.mock.calls[0][1];
    expect(arg.parser_version).toBe("v1");
  });

  describe("chat-source page", () => {
    beforeEach(() => {
      // Reset child pages store between tests
      useChildPagesStore.getState().setByParent("c", []);
    });

    it("renders AttachedMonitorsSection for chat-source pages", async () => {
      vi.spyOn(httpModule.api, "listWhopPages").mockResolvedValue({ pages: [] });
      render(<PageSettingsModal page={chatPage} onClose={vi.fn()} />);
      // Section heading is always present, even with zero children
      await waitFor(() => expect(screen.getByText(/挂载监听/)).toBeInTheDocument());
    });

    it("fetches child pages on mount for chat-source pages", async () => {
      const listSpy = vi.spyOn(httpModule.api, "listWhopPages").mockResolvedValue({ pages: [] });
      render(<PageSettingsModal page={chatPage} onClose={vi.fn()} />);
      await waitFor(() => expect(listSpy).toHaveBeenCalledWith({ parentChatId: "c" }));
    });

    it("does NOT render AttachedMonitorsSection for stock-source pages", () => {
      render(<PageSettingsModal page={stockPage} onClose={vi.fn()} />);
      expect(screen.queryByText(/挂载监听/)).not.toBeInTheDocument();
    });

    it("does NOT render AttachedMonitorsSection for option-source pages", () => {
      render(<PageSettingsModal page={optionPage} onClose={vi.fn()} />);
      expect(screen.queryByText(/挂载监听/)).not.toBeInTheDocument();
    });

    it("does NOT call listWhopPages for stock-source pages", () => {
      const listSpy = vi.spyOn(httpModule.api, "listWhopPages").mockResolvedValue({ pages: [] });
      render(<PageSettingsModal page={stockPage} onClose={vi.fn()} />);
      expect(listSpy).not.toHaveBeenCalled();
    });
  });

});
