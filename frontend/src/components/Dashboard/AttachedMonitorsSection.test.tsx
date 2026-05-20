import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { AttachedMonitorsSection } from "./AttachedMonitorsSection";
import type { WhopPage } from "../../api/domain-types";
import { api } from "../../api/http";

vi.mock("../../api/http", () => ({
  api: {
    addWhopPage: vi.fn(),
    startWhopPage: vi.fn(),
    stopWhopPage: vi.fn(),
    restartWhopPage: vi.fn(),
    removeWhopPage: vi.fn(),
    updateWhopPageSettings: vi.fn(),
  },
  HttpError: class HttpError extends Error {},
}));

const stockChild: WhopPage = {
  id: "s1", url: "https://stock", source: "stock", name: "TSLL 监听",
  added_at: "x", running: true, started_at: null, last_poll_at: null,
  messages_published: 0, last_error: null, parent_chat_id: "chat1",
  settings: { tickers: { "TSLL.US": { trade_quantity: 100 } } } as unknown as WhopPage["settings"],
};

const optionChild: WhopPage = {
  id: "o1", url: "https://opt", source: "option", name: "NVDA 期权监听",
  added_at: "x", running: false, started_at: null, last_poll_at: null,
  messages_published: 0, last_error: "playwright timeout", parent_chat_id: "chat1",
  settings: {
    option_buy_quantity_enabled: true, option_buy_quantity: 5,
    option_total_price_limit_enabled: false, option_total_price_limit: null,
  } as WhopPage["settings"],
};

describe("AttachedMonitorsSection", () => {
  beforeEach(() => vi.clearAllMocks());

  it("renders a row per child + count badge", () => {
    render(<AttachedMonitorsSection parentId="chat1" pages={[stockChild, optionChild]} onRefresh={() => {}} />);
    expect(screen.getByText("TSLL 监听")).toBeInTheDocument();
    expect(screen.getByText("NVDA 期权监听")).toBeInTheDocument();
    expect(screen.getByText(/2 个/)).toBeInTheDocument();
  });

  it("expands a stock row → renders TickerWhitelistEditor", () => {
    render(<AttachedMonitorsSection parentId="chat1" pages={[stockChild]} onRefresh={() => {}} />);
    fireEvent.click(screen.getByText("TSLL 监听"));
    expect(screen.getByText(/Ticker 白名单/i)).toBeInTheDocument();
  });

  it("expands an option row → renders OptionQuantityEditor + error banner if last_error", () => {
    render(<AttachedMonitorsSection parentId="chat1" pages={[optionChild]} onRefresh={() => {}} />);
    fireEvent.click(screen.getByText("NVDA 期权监听"));
    expect(screen.getByText(/启用期权购买张数/)).toBeInTheDocument();
    expect(screen.getByText(/playwright timeout/i)).toBeInTheDocument();
  });

  it("type select 'chat' option is disabled in add form", () => {
    render(<AttachedMonitorsSection parentId="chat1" pages={[]} onRefresh={() => {}} />);
    const chatOption = screen.getByRole("option", { name: /聊天/ }) as HTMLOptionElement;
    expect(chatOption.disabled).toBe(true);
  });

  it("submitting add form calls api.addWhopPage with parent_chat_id", async () => {
    (api.addWhopPage as unknown as ReturnType<typeof vi.fn>).mockResolvedValue({});
    const onRefresh = vi.fn();
    render(<AttachedMonitorsSection parentId="chat1" pages={[]} onRefresh={onRefresh} />);
    const urlInput = screen.getByPlaceholderText(/https/i);
    fireEvent.change(urlInput, { target: { value: "https://example.com/x" } });
    fireEvent.click(screen.getByText(/添加监听/));
    await waitFor(() => expect(api.addWhopPage).toHaveBeenCalled());
    expect(api.addWhopPage).toHaveBeenCalledWith(expect.objectContaining({
      url: "https://example.com/x",
      parent_chat_id: "chat1",
    }));
  });

  it("clicking stop/restart/remove on a row calls the right API", async () => {
    (api.stopWhopPage as unknown as ReturnType<typeof vi.fn>).mockResolvedValue({});
    (api.restartWhopPage as unknown as ReturnType<typeof vi.fn>).mockResolvedValue({});
    (api.removeWhopPage as unknown as ReturnType<typeof vi.fn>).mockResolvedValue(undefined);
    // confirm dialog auto-OK
    vi.spyOn(window, "confirm").mockReturnValue(true);

    const onRefresh = vi.fn();
    render(<AttachedMonitorsSection parentId="chat1" pages={[stockChild]} onRefresh={onRefresh} />);
    fireEvent.click(screen.getByTitle("停止"));
    await waitFor(() => expect(api.stopWhopPage).toHaveBeenCalledWith("s1"));
    fireEvent.click(screen.getByTitle("重启"));
    await waitFor(() => expect(api.restartWhopPage).toHaveBeenCalledWith("s1"));
    fireEvent.click(screen.getByTitle("移除"));
    await waitFor(() => expect(api.removeWhopPage).toHaveBeenCalledWith("s1"));
  });
});
