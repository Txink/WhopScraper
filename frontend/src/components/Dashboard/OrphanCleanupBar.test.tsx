import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import * as httpModule from "../../api/http";
import { useTasksStore } from "../../stores/tasks";
import { OrphanCleanupBar } from "./OrphanCleanupBar";
import type { TaskSummary } from "../../api/domain-types";

const makeTask = (id: string, url: string | null): TaskSummary => ({
  id, type: "stock", status: "FILLED", order_id: null, stage_timings: {},
  created_at: "2026-04-25T00:00:00Z", updated_at: "2026-04-25T00:00:00Z",
  reject_reason: null,
  message: {
    id, content: "x", raw_content: "x", author: null,
    source: "stock", posted_at: "2026-04-25T00:00:00Z",
    received_at: "2026-04-25T00:00:00Z",
    url, quoted_message_id: null,
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

  it("shows summary and global cleanup button", () => {
    const orphanTasks = [
      makeTask("a1", "u1"), makeTask("a2", "u1"),
      makeTask("b1", "u2"),
    ];
    render(<OrphanCleanupBar orphanTasks={orphanTasks} />);
    expect(screen.getByText(/共 3 条/)).toBeInTheDocument();
    expect(screen.getByText(/2 个 url/)).toBeInTheDocument();
    expect(screen.getByText(/清理全部/)).toBeInTheDocument();
  });

  it("clicking cleanup iterates all distinct urls and updates store", async () => {
    const spy = vi.spyOn(httpModule.api, "cleanupOrphanByUrl")
      .mockResolvedValue({ deleted_count: 1 });
    vi.spyOn(window, "confirm").mockReturnValue(true);

    const orphanTasks = [
      makeTask("a1", "u1"), makeTask("a2", "u1"),
      makeTask("b1", "u2"),
    ];
    useTasksStore.setState({ tasks: orphanTasks, pushEventsByTask: {} });
    render(<OrphanCleanupBar orphanTasks={orphanTasks} />);

    fireEvent.click(screen.getByText(/清理全部/));

    await waitFor(() => expect(spy).toHaveBeenCalledTimes(2));
    expect(spy).toHaveBeenCalledWith("u1");
    expect(spy).toHaveBeenCalledWith("u2");
    await waitFor(() => {
      expect(useTasksStore.getState().tasks).toEqual([]);
    });
  });

  it("disables button when only url-null tasks exist", () => {
    const orphanTasks = [makeTask("legacy1", null), makeTask("legacy2", null)];
    render(<OrphanCleanupBar orphanTasks={orphanTasks} />);
    expect(screen.getByText(/清理全部/)).toBeDisabled();
    expect(screen.getByText(/2 条 url 缺失/)).toBeInTheDocument();
  });

  it("partial failure shows error with failed urls", async () => {
    let callCount = 0;
    vi.spyOn(httpModule.api, "cleanupOrphanByUrl").mockImplementation(async () => {
      callCount++;
      if (callCount === 2) throw new Error("boom");
      return { deleted_count: 1 };
    });
    vi.spyOn(window, "confirm").mockReturnValue(true);
    const orphanTasks = [makeTask("a", "u1"), makeTask("b", "u2")];
    useTasksStore.setState({ tasks: orphanTasks, pushEventsByTask: {} });
    render(<OrphanCleanupBar orphanTasks={orphanTasks} />);
    fireEvent.click(screen.getByText(/清理全部/));
    await waitFor(() => expect(screen.getByText(/失败/)).toBeInTheDocument());
  });
});
