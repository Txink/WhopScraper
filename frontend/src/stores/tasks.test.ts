import { describe, expect, it, beforeEach } from "vitest";
import { useTasksStore, selectTasksByUrl } from "./tasks";
import type { TaskSummary } from "../api/domain-types";

describe("tasks store", () => {
  beforeEach(() => {
    useTasksStore.setState({ tasks: [], pushEventsByTask: {} });
  });

  it("upsertTask inserts new", () => {
    const task = _mkTask("t1", "2026-04-25T10:00:00Z");
    useTasksStore.getState().upsertTask(task);
    expect(useTasksStore.getState().tasks).toHaveLength(1);
  });

  it("upsertTask replaces existing by id", () => {
    const a = _mkTask("t1", "2026-04-25T10:00:00Z", "PARSING");
    const b = _mkTask("t1", "2026-04-25T10:00:01Z", "FILLED");
    useTasksStore.getState().upsertTask(a);
    useTasksStore.getState().upsertTask(b);
    expect(useTasksStore.getState().tasks).toHaveLength(1);
    expect(useTasksStore.getState().tasks[0].status).toBe("FILLED");
  });

  it("upsertTask keeps newest first", () => {
    useTasksStore.getState().upsertTask(_mkTask("t1", "2026-04-25T10:00:00Z"));
    useTasksStore.getState().upsertTask(_mkTask("t2", "2026-04-25T11:00:00Z"));
    useTasksStore.getState().upsertTask(_mkTask("t3", "2026-04-25T09:00:00Z"));
    const ids = useTasksStore.getState().tasks.map((t) => t.id);
    expect(ids).toEqual(["t2", "t1", "t3"]);
  });

  it("appendPushEvent creates map entry", () => {
    const evt = _mkPush("e1", "t1");
    useTasksStore.getState().appendPushEvent("t1", evt);
    expect(useTasksStore.getState().pushEventsByTask["t1"]).toHaveLength(1);
  });

  it("appendPushEvent dedupes by id", () => {
    const evt = _mkPush("e1", "t1");
    useTasksStore.getState().appendPushEvent("t1", evt);
    useTasksStore.getState().appendPushEvent("t1", evt);
    expect(useTasksStore.getState().pushEventsByTask["t1"]).toHaveLength(1);
  });

  it("applyWsEvent routes task + push_event", () => {
    useTasksStore.getState().applyWsEvent({
      event_id: 1,
      type: "task.push_event",
      payload: {
        task: _mkTask("t1", "2026-04-25T10:00:00Z"),
        push_event: _mkPush("e1", "t1"),
      },
    });
    expect(useTasksStore.getState().tasks).toHaveLength(1);
    expect(useTasksStore.getState().pushEventsByTask["t1"]).toHaveLength(1);
  });
});

// Minimal test fixtures — shape matches domain-types
function _mkTask(id: string, created_at: string, status = "PARSING") {
  return {
    id, type: "stock", status, order_id: null,
    stage_timings: {}, created_at, updated_at: created_at,
    reject_reason: null,
    message: {
      id, content: "test", raw_content: "test",
      author: null, source: "stock",
      posted_at: created_at, received_at: created_at,
      quoted_message_id: null,
    },
    instruction: null,
  };
}

function _mkPush(id: string, task_id: string) {
  return {
    id, task_id, order_id: "order-1", state: "NEW",
    received_at: "2026-04-25T10:00:00Z",
    delta_qty: null, delta_price: null,
    cumulative_qty: null, cumulative_avg_price: null,
    note: null,
  };
}

const makeTask = (id: string, url: string | null): TaskSummary => ({
  id, type: "stock", status: "RECEIVED", order_id: null, stage_timings: {},
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

describe("selectTasksByUrl", () => {
  const tasks: TaskSummary[] = [
    makeTask("a", "u1"),
    makeTask("b", "u2"),
    makeTask("c", null),
    makeTask("d", "u3-removed"),
  ];
  const pageUrls = new Set(["u1", "u2"]);

  it("filters by exact url", () => {
    expect(selectTasksByUrl(tasks, "u1", pageUrls).map(t => t.id)).toEqual(["a"]);
  });

  it("orphan returns null-url and unknown-url tasks", () => {
    expect(selectTasksByUrl(tasks, null, pageUrls).map(t => t.id)).toEqual(["c", "d"]);
  });

  it("returns empty for unknown url", () => {
    expect(selectTasksByUrl(tasks, "nope", pageUrls)).toEqual([]);
  });
});
