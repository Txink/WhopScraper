import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api, configureHttp, HttpError, __resetForTests } from "./http";

describe("http", () => {
  beforeEach(() => {
    global.fetch = vi.fn();
    configureHttp({ baseUrl: "http://localhost:8000", token: "test-token" });
  });

  afterEach(() => {
    vi.restoreAllMocks();
    __resetForTests();
  });

  it("throws if configureHttp not called", async () => {
    __resetForTests();
    await expect(api.health()).rejects.toThrow("http not configured");
  });

  it("adds token as query param", async () => {
    (global.fetch as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: true,
      json: async () => ({ whop: "up", longport: "up", mode: "paper", dry_run: true }),
    });
    await api.health();
    const call = (global.fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(call[0]).toContain("token=test-token");
  });

  it("throws HttpError with correct status on non-2xx", async () => {
    (global.fetch as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: false,
      status: 403,
      statusText: "Forbidden",
      json: async () => ({ detail: "forbidden" }),
      text: async () => "",
    });
    await expect(api.health()).rejects.toMatchObject({
      name: "HttpError",
      status: 403,
    });
    await expect(api.health()).rejects.toBeInstanceOf(HttpError);
  });

  it("appends query params for listTasks", async () => {
    (global.fetch as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: true,
      json: async () => ({ tasks: [], next_cursor: null }),
    });
    await api.listTasks({ status: "FILLED", limit: 10 });
    const call = (global.fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    const url: string = call[0];
    expect(url).toContain("status=FILLED");
    expect(url).toContain("limit=10");
  });

  it("uses POST method for cancelTask", async () => {
    (global.fetch as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: true,
      json: async () => ({ ok: true }),
    });
    await api.cancelTask("msg-1");
    const call = (global.fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    const [url, init] = call;
    expect(url).toContain("/api/tasks/msg-1/cancel");
    expect(init.method).toBe("POST");
  });
});
