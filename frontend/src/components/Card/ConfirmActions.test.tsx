import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { ConfirmActions } from "./ConfirmActions";
import * as httpModule from "../../api/http";
import { useTasksStore } from "../../stores/tasks";

const fakeTaskOut = {
  id: "task-1",
  type: "stock" as const,
  status: "SKIPPED",
  order_id: null,
  stage_timings: {},
  created_at: "2026-04-26T10:00:00Z",
  updated_at: "2026-04-26T10:00:01Z",
  reject_reason: "用户手动取消",
  message: {} as never,
  instruction: null,
  push_events: [],
};

describe("ConfirmActions", () => {
  beforeEach(() => {
    useTasksStore.setState({ tasks: [], pushEventsByTask: {} });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders two icon buttons (confirm + cancel)", () => {
    render(<ConfirmActions taskId="task-1" variant="compact" />);
    expect(screen.getByRole("button", { name: "确认下单" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "取消" })).toBeInTheDocument();
  });

  it("clicking confirm calls api.confirmTask with taskId", async () => {
    const spy = vi.spyOn(httpModule.api, "confirmTask").mockResolvedValue(fakeTaskOut as never);
    render(<ConfirmActions taskId="task-1" variant="compact" />);
    fireEvent.click(screen.getByRole("button", { name: "确认下单" }));
    await waitFor(() => expect(spy).toHaveBeenCalledWith("task-1"));
  });

  it("clicking cancel calls api.skipTask with taskId", async () => {
    const spy = vi.spyOn(httpModule.api, "skipTask").mockResolvedValue(fakeTaskOut as never);
    render(<ConfirmActions taskId="task-1" variant="compact" />);
    fireEvent.click(screen.getByRole("button", { name: "取消" }));
    await waitFor(() => expect(spy).toHaveBeenCalledWith("task-1"));
  });

  it("disables both buttons while a request is in-flight", async () => {
    let resolve!: (v: typeof fakeTaskOut) => void;
    vi.spyOn(httpModule.api, "confirmTask").mockImplementation(
      () => new Promise((r) => { resolve = r as never; }),
    );
    render(<ConfirmActions taskId="task-1" variant="compact" />);
    const confirmBtn = screen.getByRole("button", { name: "确认下单" });
    const cancelBtn = screen.getByRole("button", { name: "取消" });
    fireEvent.click(confirmBtn);
    await waitFor(() => {
      expect(confirmBtn).toBeDisabled();
      expect(cancelBtn).toBeDisabled();
    });
    resolve(fakeTaskOut);
    await waitFor(() => expect(confirmBtn).not.toBeDisabled());
  });

  it("shows error indicator when api call fails", async () => {
    vi.spyOn(httpModule.api, "skipTask").mockRejectedValue(
      new httpModule.HttpError(400, { detail: "wrong status" }, "HTTP 400"),
    );
    const { container } = render(<ConfirmActions taskId="task-1" variant="compact" />);
    fireEvent.click(screen.getByRole("button", { name: "取消" }));
    await waitFor(() => {
      const err = container.querySelector(".ca-err");
      expect(err).toBeInTheDocument();
      expect(err?.getAttribute("title")).toContain("wrong status");
    });
  });

  it("stops click propagation so wrapper handlers do not fire", () => {
    const wrapperClick = vi.fn();
    vi.spyOn(httpModule.api, "skipTask").mockResolvedValue(fakeTaskOut as never);
    render(
      <div onClick={wrapperClick}>
        <ConfirmActions taskId="task-1" variant="compact" />
      </div>,
    );
    fireEvent.click(screen.getByRole("button", { name: "取消" }));
    expect(wrapperClick).not.toHaveBeenCalled();
  });

  it("upserts the returned task into the store on success", async () => {
    vi.spyOn(httpModule.api, "skipTask").mockResolvedValue(fakeTaskOut as never);
    render(<ConfirmActions taskId="task-1" variant="compact" />);
    fireEvent.click(screen.getByRole("button", { name: "取消" }));
    await waitFor(() => {
      const stored = useTasksStore.getState().tasks.find((t) => t.id === "task-1");
      expect(stored).toBeDefined();
      expect(stored?.status).toBe("SKIPPED");
    });
  });
});
