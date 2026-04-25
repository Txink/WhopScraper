import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import * as httpModule from "../../api/http";
import { useTasksStore } from "../../stores/tasks";
import { OrphanCleanupBar } from "./OrphanCleanupBar";
import type { TaskSummary } from "../../api/domain-types";

const makeTask = (id: string, url: string | null): TaskSummary => ({
  id,
  type: "stock",
  status: "FILLED",
  order_id: null,
  stage_timings: {},
  created_at: "2026-04-25T00:00:00Z",
  updated_at: "2026-04-25T00:00:00Z",
  reject_reason: null,
  message: {
    id,
    content: "x",
    raw_content: "x",
    author: null,
    source: "stock",
    posted_at: "2026-04-25T00:00:00Z",
    received_at: "2026-04-25T00:00:00Z",
    url,
    quoted_message_id: null,
  },
  instruction: null,
});

describe("<OrphanCleanupBar>", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    useTasksStore.setState({ tasks: [], pushEventsByTask: {} });
  });

  it("renders nothing when no orphan tasks", () => {
    const { container } = render(<OrphanCleanupBar orphanTasks={[]} />);
    expect(container.firstChild).toBeNull();
  });

  it("groups by url and shows counts", () => {
    const orphanTasks = [
      makeTask("a1", "u1"),
      makeTask("a2", "u1"),
      makeTask("b1", "u2"),
    ];
    render(<OrphanCleanupBar orphanTasks={orphanTasks} />);
    expect(screen.getByText("u1")).toBeInTheDocument();
    expect(screen.getByText("u2")).toBeInTheDocument();
    expect(screen.getByText("2 条")).toBeInTheDocument();
    expect(screen.getByText("1 条")).toBeInTheDocument();
  });

  it("clicking remove calls API and updates store on success", async () => {
    const spy = vi
      .spyOn(httpModule.api, "cleanupOrphanByUrl")
      .mockResolvedValue({ deleted_count: 2 });
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(true);

    const orphanTasks = [
      makeTask("a1", "u1"),
      makeTask("a2", "u1"),
      makeTask("b1", "u2"),
    ];
    useTasksStore.setState({ tasks: orphanTasks, pushEventsByTask: {} });
    render(<OrphanCleanupBar orphanTasks={orphanTasks} />);

    const buttons = screen.getAllByText("移除");
    fireEvent.click(buttons[0]); // u1 (2 tasks, comes first by sort)

    await waitFor(() => expect(spy).toHaveBeenCalledWith("u1"));
    await waitFor(() => {
      const remaining = useTasksStore.getState().tasks;
      expect(remaining.map((t) => t.id)).toEqual(["b1"]);
    });
    confirmSpy.mockRestore();
  });

  it("shows alert for url=null group (cannot be cleaned by url)", () => {
    const alertSpy = vi.spyOn(window, "alert").mockImplementation(() => {});
    const orphanTasks = [makeTask("legacy", null)];
    render(<OrphanCleanupBar orphanTasks={orphanTasks} />);
    fireEvent.click(screen.getByText("移除"));
    expect(alertSpy).toHaveBeenCalledWith(expect.stringContaining("无法按 url"));
    alertSpy.mockRestore();
  });
});
