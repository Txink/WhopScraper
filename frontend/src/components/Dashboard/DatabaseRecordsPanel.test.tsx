import { describe, it, expect, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import * as httpModule from "../../api/http";
import { DatabaseRecordsPanel } from "./DatabaseRecordsPanel";

describe("<DatabaseRecordsPanel>", () => {
  it("loads and renders persisted task rows", async () => {
    const listSpy = vi.spyOn(httpModule.api, "listTasks").mockResolvedValue({
      tasks: [
        {
          id: "t1",
          type: "stock",
          status: "FILLED",
          order_id: null,
          stage_timings: {},
          created_at: "2026-04-25T00:00:00Z",
          updated_at: "2026-04-25T00:00:00Z",
          reject_reason: null,
          message: {
            id: "m1",
            content: "AAPL buy",
            raw_content: "AAPL buy",
            author: "alice",
            source: "whop",
            posted_at: "2026-04-25T00:00:00Z",
            received_at: "2026-04-25T00:00:00Z",
            url: "https://w/a/",
            quoted_message_id: null,
          },
          instruction: null,
        },
      ],
      next_cursor: null,
    });
    const countSpy = vi.spyOn(httpModule.api, "countTasks").mockResolvedValue({
      total_count: 10,
    });

    render(
      <DatabaseRecordsPanel
        pageNameByUrl={new Map([["https://w/a/", "Alpha 页面"]])}
      />
    );
    await waitFor(() => expect(screen.getByText("AAPL buy")).toBeInTheDocument());

    expect(screen.getByText("数据库记录")).toBeInTheDocument();
    expect(screen.getByText("Alpha 页面")).toBeInTheDocument();
    expect(screen.queryByText("类型")).toBeNull();
    expect(screen.getByText("FILLED")).toBeInTheDocument();
    expect(screen.getByText("第 1 页 / 共 1 页")).toBeInTheDocument();
    expect(listSpy).toHaveBeenCalledWith({ limit: 15 });
    expect(countSpy).toHaveBeenCalled();
  });

  it("supports cursor pagination with 15 rows per page", async () => {
    const listSpy = vi
      .spyOn(httpModule.api, "listTasks")
      .mockResolvedValueOnce({
        tasks: [
          {
            id: "t1",
            type: "stock",
            status: "FILLED",
            order_id: null,
            stage_timings: {},
            created_at: "2026-04-25T00:00:00Z",
            updated_at: "2026-04-25T00:00:00Z",
            reject_reason: null,
            message: {
              id: "m1",
              content: "first page",
              raw_content: "first page",
              author: "alice",
              source: "whop",
              posted_at: "2026-04-25T00:00:00Z",
              received_at: "2026-04-25T00:00:00Z",
              url: "https://w/a/",
              quoted_message_id: null,
            },
            instruction: null,
          },
        ],
        next_cursor: "cursor-2",
      })
      .mockResolvedValueOnce({
        tasks: [
          {
            id: "t2",
            type: "stock",
            status: "REJECTED",
            order_id: null,
            stage_timings: {},
            created_at: "2026-04-25T00:00:00Z",
            updated_at: "2026-04-25T00:00:00Z",
            reject_reason: null,
            message: {
              id: "m2",
              content: "second page",
              raw_content: "second page",
              author: "bob",
              source: "whop",
              posted_at: "2026-04-25T00:00:00Z",
              received_at: "2026-04-25T00:00:00Z",
              url: "https://w/a/",
              quoted_message_id: null,
            },
            instruction: null,
          },
        ],
        next_cursor: null,
      });
    const countSpy = vi.spyOn(httpModule.api, "countTasks");
    countSpy.mockResolvedValueOnce({ total_count: 30 }).mockResolvedValueOnce({ total_count: 30 });

    render(
      <DatabaseRecordsPanel
        pageNameByUrl={new Map([["https://w/a/", "Alpha 页面"]])}
      />,
    );

    await waitFor(() => expect(screen.getByText("first page")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "下一页" }));
    await waitFor(() => expect(screen.getByText("second page")).toBeInTheDocument());

    expect(screen.getByText("第 2 页 / 共 2 页")).toBeInTheDocument();
    expect(listSpy).toHaveBeenNthCalledWith(1, { limit: 15 });
    expect(listSpy).toHaveBeenNthCalledWith(2, { limit: 15, cursor: "cursor-2" });
    expect(countSpy).toHaveBeenCalledTimes(2);
  });

  it("switches to a non-tasks tab and calls listDbRows", async () => {
    vi.spyOn(httpModule.api, "listTasks").mockResolvedValue({
      tasks: [],
      next_cursor: null,
    });
    vi.spyOn(httpModule.api, "countTasks").mockResolvedValue({ total_count: 0 });
    const dbSpy = vi.spyOn(httpModule.api, "listDbRows").mockResolvedValue({
      table: "messages",
      columns: ["id", "content"],
      rows: [["m1", "hello"]],
      total: 1,
    });

    render(<DatabaseRecordsPanel pageNameByUrl={new Map()} />);
    await waitFor(() => expect(httpModule.api.listTasks).toHaveBeenCalled());

    fireEvent.click(screen.getByRole("tab", { name: "messages" }));
    await waitFor(() => expect(screen.getByText("hello")).toBeInTheDocument());

    expect(dbSpy).toHaveBeenCalledWith("messages", { limit: 15, offset: 0 });
  });
});
