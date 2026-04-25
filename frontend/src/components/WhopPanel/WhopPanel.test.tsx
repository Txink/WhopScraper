import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { WhopPanel } from "./WhopPanel";
import * as httpMod from "../../api/http";

vi.mock("../../api/http", () => ({
  api: {
    listWhopPages: vi.fn(),
    addWhopPage: vi.fn(),
    removeWhopPage: vi.fn(),
    restartWhopPage: vi.fn(),
    whopCookieStatus: vi.fn(),
  },
  HttpError: class HttpError extends Error {
    status: number;
    body: unknown;
    constructor(status: number, body: unknown, msg: string) {
      super(msg);
      this.status = status;
      this.body = body;
    }
  },
}));

const api = httpMod.api as ReturnType<typeof vi.fn> & typeof httpMod.api;

beforeEach(() => {
  vi.clearAllMocks();
  (api.listWhopPages as ReturnType<typeof vi.fn>).mockResolvedValue({ pages: [] });
  (api.whopCookieStatus as ReturnType<typeof vi.fn>).mockResolvedValue({
    exists: true,
    path: "/path/to/cookie.json",
    last_modified: "2026-04-25T10:00:00Z",
    age_seconds: 3600,
  });
});

describe("WhopPanel", () => {
  it("renders cookie status as ok when fresh", async () => {
    render(<WhopPanel />);
    await waitFor(() => expect(screen.getByText("有效")).toBeInTheDocument());
  });

  it("renders empty hint when no pages", async () => {
    render(<WhopPanel />);
    await waitFor(() =>
      expect(screen.getByText(/暂无监听/)).toBeInTheDocument()
    );
  });

  it("calls addWhopPage on form submit", async () => {
    (api.addWhopPage as ReturnType<typeof vi.fn>).mockResolvedValue({
      id: "abc", url: "https://whop.com/joined/abc/app/", source: "stock", name: "test",
      added_at: "2026-04-25T00:00:00Z", running: true, started_at: null,
      last_poll_at: null, messages_published: 0, last_error: null,
    });
    render(<WhopPanel />);
    await waitFor(() => screen.getByRole("button", { name: /^添加监听$/ }));

    const urlInput = screen.getByPlaceholderText(/https:\/\/whop\.com/);
    fireEvent.change(urlInput, { target: { value: "https://whop.com/joined/abc/app/" } });
    fireEvent.click(screen.getByRole("button", { name: /^添加监听$/ }));

    await waitFor(() => {
      expect(api.addWhopPage).toHaveBeenCalledWith({
        url: "https://whop.com/joined/abc/app/",
        source: "stock",
        name: null,
      });
    });
  });

  it("shows add error message when addWhopPage rejects", async () => {
    const { HttpError } = httpMod;
    (api.addWhopPage as ReturnType<typeof vi.fn>).mockRejectedValue(
      new HttpError(422, { detail: "URL already exists" }, "HTTP 422")
    );
    render(<WhopPanel />);
    await waitFor(() => screen.getByRole("button", { name: /^添加监听$/ }));

    const urlInput = screen.getByPlaceholderText(/https:\/\/whop\.com/);
    fireEvent.change(urlInput, { target: { value: "https://whop.com/joined/dup/app/" } });
    fireEvent.click(screen.getByRole("button", { name: /^添加监听$/ }));

    await waitFor(() =>
      expect(screen.getByText("URL already exists")).toBeInTheDocument()
    );
  });

  it("renders pages table with rows", async () => {
    (api.listWhopPages as ReturnType<typeof vi.fn>).mockResolvedValue({
      pages: [{
        id: "p1", url: "https://whop.com/joined/abc/app/",
        source: "stock", name: "Test Stock",
        added_at: "2026-04-25T10:00:00Z",
        running: true, started_at: null, last_poll_at: null,
        messages_published: 5, last_error: null,
      }],
    });
    render(<WhopPanel />);
    await waitFor(() => screen.getByText("Test Stock"));
    expect(screen.getByText("运行中")).toBeInTheDocument();
    expect(screen.getByText("5")).toBeInTheDocument();
  });

  it("shows missing cookie state", async () => {
    (api.whopCookieStatus as ReturnType<typeof vi.fn>).mockResolvedValue({
      exists: false, path: "/x", last_modified: null, age_seconds: null,
    });
    render(<WhopPanel />);
    await waitFor(() => expect(screen.getByText("缺失")).toBeInTheDocument());
  });

  it("restart button calls api.restartWhopPage", async () => {
    (api.listWhopPages as ReturnType<typeof vi.fn>).mockResolvedValue({
      pages: [{
        id: "p1", url: "https://whop.com/joined/abc/app/",
        source: "stock", name: "Test Stock",
        added_at: "2026-04-25T10:00:00Z",
        running: false, started_at: null, last_poll_at: null,
        messages_published: 0, last_error: null,
      }],
    });
    (api.restartWhopPage as ReturnType<typeof vi.fn>).mockResolvedValue({
      id: "p1", url: "https://whop.com/joined/abc/app/",
      source: "stock", name: "Test Stock",
      added_at: "2026-04-25T10:00:00Z",
      running: true, started_at: null, last_poll_at: null,
      messages_published: 0, last_error: null,
    });
    render(<WhopPanel />);
    await waitFor(() => screen.getByText("Test Stock"));

    fireEvent.click(screen.getByRole("button", { name: "重启" }));

    await waitFor(() =>
      expect(api.restartWhopPage).toHaveBeenCalledWith("p1")
    );
  });

  it("remove with confirm calls api.removeWhopPage", async () => {
    (api.listWhopPages as ReturnType<typeof vi.fn>).mockResolvedValue({
      pages: [{
        id: "p1", url: "https://whop.com/joined/abc/app/",
        source: "stock", name: "Test Stock",
        added_at: "2026-04-25T10:00:00Z",
        running: false, started_at: null, last_poll_at: null,
        messages_published: 0, last_error: null,
      }],
    });
    (api.removeWhopPage as ReturnType<typeof vi.fn>).mockResolvedValue(undefined);
    // Stub confirm to return true
    vi.stubGlobal("confirm", () => true);

    render(<WhopPanel />);
    await waitFor(() => screen.getByText("Test Stock"));

    fireEvent.click(screen.getByRole("button", { name: "移除" }));

    await waitFor(() =>
      expect(api.removeWhopPage).toHaveBeenCalledWith("p1")
    );

    vi.unstubAllGlobals();
  });
});
