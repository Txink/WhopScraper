import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import * as httpModule from "../../api/http";
import { PageSettingsModal } from "./PageSettingsModal";
import type { WhopPage } from "../../api/domain-types";
import { useChildPagesStore } from "../../stores/childPages";

const chatPage: WhopPage = {
  id: "c", url: "u", source: "chat", name: "Chat", added_at: "2026-04-25T00:00:00Z",
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
  running: true, started_at: null, last_poll_at: null, messages_published: 0, last_error: null,
};

describe("<PageSettingsModal>", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    useChildPagesStore.getState().setByParent("c", []);
  });

  it("renders 3-tab nav (消息监听 / 正股监听 / 期权监听)", () => {
    vi.spyOn(httpModule.api, "listWhopPages").mockResolvedValue({ pages: [] });
    render(<PageSettingsModal page={chatPage} onClose={vi.fn()} />);
    expect(screen.getByRole("tab", { name: /消息监听/ })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /正股监听/ })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /期权监听/ })).toBeInTheDocument();
  });

  it("default tab is 消息监听 — shows dedupe + headless + 清空消息", () => {
    vi.spyOn(httpModule.api, "listWhopPages").mockResolvedValue({ pages: [] });
    render(<PageSettingsModal page={chatPage} onClose={vi.fn()} />);
    expect(screen.getByLabelText(/避免重复解析/)).toBeInTheDocument();
    expect(screen.getByLabelText(/无头模式启动网页/)).toBeInTheDocument();
    expect(screen.getByText(/清空消息/)).toBeInTheDocument();
    // Stock/option-only fields no longer surface in the chat settings modal
    // — they've been migrated into the 正股/期权 tabs' MonRow expanded body.
    expect(screen.queryByLabelText(/价格偏差容忍/)).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/禁止下单历史消息/)).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/parser v2/i)).not.toBeInTheDocument();
  });

  it("clicking 正股监听 tab renders the stock sub-monitor add form", () => {
    vi.spyOn(httpModule.api, "listWhopPages").mockResolvedValue({ pages: [] });
    render(<PageSettingsModal page={chatPage} onClose={vi.fn()} />);
    fireEvent.click(screen.getByRole("tab", { name: /正股监听/ }));
    expect(screen.getByRole("button", { name: /\+ 添加正股监听/ })).toBeInTheDocument();
  });

  it("clicking 期权监听 tab renders the option sub-monitor add form", () => {
    vi.spyOn(httpModule.api, "listWhopPages").mockResolvedValue({ pages: [] });
    render(<PageSettingsModal page={chatPage} onClose={vi.fn()} />);
    fireEvent.click(screen.getByRole("tab", { name: /期权监听/ }));
    expect(screen.getByRole("button", { name: /\+ 添加期权监听/ })).toBeInTheDocument();
  });

  it("fetches child pages on mount", async () => {
    const listSpy = vi.spyOn(httpModule.api, "listWhopPages").mockResolvedValue({ pages: [] });
    render(<PageSettingsModal page={chatPage} onClose={vi.fn()} />);
    await waitFor(() => expect(listSpy).toHaveBeenCalledWith({ parentChatId: "c" }));
  });

  it("save patches only dedupe + launch_headless", async () => {
    vi.spyOn(httpModule.api, "listWhopPages").mockResolvedValue({ pages: [] });
    const spy = vi.spyOn(httpModule.api, "updateWhopPageSettings").mockResolvedValue(chatPage);
    render(<PageSettingsModal page={chatPage} onClose={vi.fn()} />);
    fireEvent.click(screen.getByLabelText(/无头模式启动网页/));
    fireEvent.click(screen.getByText(/^保存/));
    await waitFor(() => expect(spy).toHaveBeenCalled());
    const arg = spy.mock.calls[0][1];
    expect(arg.launch_headless).toBe(true);
    expect(arg.dedupe_processed_messages).toBe(false);
    // Fields not exposed to the chat-source modal must NOT be patched —
    // backend's per-field merge then preserves their existing values.
    expect("price_deviation_tolerance" in arg).toBe(false);
    expect("block_historical_messages" in arg).toBe(false);
    expect("parser_version" in arg).toBe(false);
  });

  it("toggling dedupe shows hint about restart", () => {
    vi.spyOn(httpModule.api, "listWhopPages").mockResolvedValue({ pages: [] });
    render(<PageSettingsModal page={chatPage} onClose={vi.fn()} />);
    const checkbox = screen.getByLabelText(/避免重复解析/);
    fireEvent.click(checkbox);
    expect(screen.getByText(/下次重启监听才生效/)).toBeInTheDocument();
  });

  it("renders Whop Cookie status card in 消息监听 tab", async () => {
    vi.spyOn(httpModule.api, "listWhopPages").mockResolvedValue({ pages: [] });
    vi.spyOn(httpModule.api, "whopCookieStatus").mockResolvedValue({
      exists: true,
      path: "/path/to/cookie.json",
      last_modified: "2026-05-22T10:00:00Z",
      age_seconds: 3600,
    });
    render(<PageSettingsModal page={chatPage} onClose={vi.fn()} />);
    await waitFor(() => expect(screen.getByText(/Whop Cookie 状态/)).toBeInTheDocument());
    expect(screen.getByText("有效")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /复制登录命令/ })).toBeInTheDocument();
  });
});
