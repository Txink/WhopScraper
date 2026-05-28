import { render, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { LabelActions } from "./LabelActions";
import { useTasksStore } from "../../stores/tasks";
import { api } from "../../api/http";

beforeEach(() => {
  useTasksStore.setState({ tasks: [], pushEventsByTask: {}, labelsByTask: {} });
});
afterEach(() => vi.restoreAllMocks());

describe("LabelActions", () => {
  it("clicking 解析正确 calls setTaskLabel(correct) and updates store", async () => {
    vi.spyOn(api, "setTaskLabel").mockResolvedValue({
      id: "t1", label: { verdict: "correct", corrected_payload: null },
    } as never);
    render(<LabelActions taskId="t1" instruction={null} variant="stock" />);
    fireEvent.click(screen.getByText("解析正确"));
    await waitFor(() => {
      expect(api.setTaskLabel).toHaveBeenCalledWith("t1", { verdict: "correct" });
      expect(useTasksStore.getState().labelsByTask["t1"].verdict).toBe("correct");
    });
  });

  it("clicking 解析正确 while already correct clears it", async () => {
    useTasksStore.getState().setLabel("t1", { verdict: "correct", corrected_payload: null, updated_at: "" });
    vi.spyOn(api, "clearTaskLabel").mockResolvedValue({ id: "t1", label: null } as never);
    render(<LabelActions taskId="t1" instruction={null} variant="stock" />);
    fireEvent.click(screen.getByText("已确认正确"));
    await waitFor(() => {
      expect(api.clearTaskLabel).toHaveBeenCalledWith("t1");
      expect(useTasksStore.getState().labelsByTask["t1"]).toBeUndefined();
    });
  });

  it("校正 opens dialog; saving calls setTaskLabel(corrected)", async () => {
    vi.spyOn(api, "setTaskLabel").mockResolvedValue({
      id: "t1",
      label: { verdict: "corrected", corrected_payload: { type: "stock", action: "BUY" } },
    } as never);
    render(<LabelActions taskId="t1" instruction={null} variant="stock" />);
    fireEvent.click(screen.getByText("校正"));
    expect(screen.getByRole("dialog")).not.toBeNull();
    fireEvent.click(screen.getByText("保存"));
    await waitFor(() => {
      expect(api.setTaskLabel).toHaveBeenCalledWith(
        "t1",
        expect.objectContaining({ verdict: "corrected" }),
      );
    });
  });
});
