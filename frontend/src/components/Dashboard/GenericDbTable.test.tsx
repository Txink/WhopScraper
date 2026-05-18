import { describe, it, expect, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import * as httpModule from "../../api/http";
import { GenericDbTable } from "./GenericDbTable";

describe("<GenericDbTable>", () => {
  it("renders columns and rows from API", async () => {
    vi.spyOn(httpModule.api, "listDbRows").mockResolvedValue({
      table: "messages",
      columns: ["id", "content", "posted_at"],
      rows: [
        ["m1", "AAPL buy", "2026-04-25T00:00:00Z"],
        ["m2", "TSLA sell", "2026-04-24T00:00:00Z"],
      ],
      total: 2,
    });

    render(<GenericDbTable table="messages" />);
    await waitFor(() => expect(screen.getByText("AAPL buy")).toBeInTheDocument());

    expect(screen.getByText("id")).toBeInTheDocument();
    expect(screen.getByText("posted_at")).toBeInTheDocument();
    expect(screen.getByText("m1")).toBeInTheDocument();
    expect(screen.getByText("第 1 页 / 共 1 页")).toBeInTheDocument();
  });

  it("stringifies JSON cells with title attribute for hover", async () => {
    const payload = { foo: "bar", n: 42 };
    vi.spyOn(httpModule.api, "listDbRows").mockResolvedValue({
      table: "push_events",
      columns: ["id", "payload_json"],
      rows: [["evt1", payload]],
      total: 1,
    });

    render(<GenericDbTable table="push_events" />);
    await waitFor(() => expect(screen.getByText("evt1")).toBeInTheDocument());

    const cell = screen.getByTitle(JSON.stringify(payload));
    expect(cell).toBeInTheDocument();
    expect(cell.textContent).toContain('"foo"');
  });

  it("renders null cells as em-dash", async () => {
    vi.spyOn(httpModule.api, "listDbRows").mockResolvedValue({
      table: "messages",
      columns: ["id", "author"],
      rows: [["m1", null]],
      total: 1,
    });

    render(<GenericDbTable table="messages" />);
    await waitFor(() => expect(screen.getByText("m1")).toBeInTheDocument());

    const row = screen.getByText("m1").closest("tr")!;
    const cells = row.querySelectorAll("td");
    expect(cells[1].textContent).toBe("—");
  });

  it("paginates via offset on next/prev", async () => {
    const spy = vi
      .spyOn(httpModule.api, "listDbRows")
      .mockResolvedValueOnce({
        table: "messages",
        columns: ["id"],
        rows: [["a"]],
        total: 25,
      })
      .mockResolvedValueOnce({
        table: "messages",
        columns: ["id"],
        rows: [["b"]],
        total: 25,
      });

    render(<GenericDbTable table="messages" />);
    await waitFor(() => expect(screen.getByText("a")).toBeInTheDocument());
    expect(spy).toHaveBeenNthCalledWith(1, "messages", { limit: 15, offset: 0 });

    fireEvent.click(screen.getByRole("button", { name: "下一页" }));
    await waitFor(() => expect(screen.getByText("b")).toBeInTheDocument());
    expect(spy).toHaveBeenNthCalledWith(2, "messages", { limit: 15, offset: 15 });
  });

  it("formats ISO datetime cells via fmtBeijingFull with raw timestamp in title", async () => {
    const iso = "2026-04-25T03:00:00Z";
    vi.spyOn(httpModule.api, "listDbRows").mockResolvedValue({
      table: "messages",
      columns: ["id", "posted_at"],
      rows: [["m1", iso]],
      total: 1,
    });

    render(<GenericDbTable table="messages" />);
    await waitFor(() => expect(screen.getByText("m1")).toBeInTheDocument());

    // 原始 ISO 仍在 title 里，方便复制
    expect(screen.getByTitle(iso)).toBeInTheDocument();
    // 显示文本不应是原始 ISO
    const row = screen.getByText("m1").closest("tr")!;
    const cells = row.querySelectorAll("td");
    expect(cells[1].textContent).not.toBe(iso);
    // fmtBeijingFull 应当包含年份数字（具体格式可能因实现而异，只断言不是空也不是原始 ISO）
    expect(cells[1].textContent).toMatch(/\d{4}/);
  });
});
