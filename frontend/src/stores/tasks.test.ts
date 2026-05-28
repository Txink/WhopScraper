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

  it("upsertTask preserves terminal status against stale non-terminal payload", () => {
    // Regression: two backend push handlers race; one publishes
    // task.status=REJECTED, the other (with a stale in-memory snapshot)
    // publishes task.status=PENDING. WS broadcasts both. Whichever arrives
    // last must NOT regress the displayed status from REJECTED to PENDING —
    // otherwise the user sees "等待成交" on a task that LongPort already
    // rejected.
    const rejected = _mkTask("t1", "2026-04-25T10:00:01Z", "REJECTED");
    rejected.reject_reason = "订单金额超出最大购买力";
    const stalePending = _mkTask("t1", "2026-04-25T10:00:01Z", "PENDING");

    useTasksStore.getState().upsertTask(rejected);
    useTasksStore.getState().upsertTask(stalePending);

    const stored = useTasksStore.getState().tasks[0];
    expect(stored.status).toBe("REJECTED");
    expect(stored.reject_reason).toBe("订单金额超出最大购买力");
  });

  it("upsertTask allows non-terminal → terminal as a legitimate progression", () => {
    const pending = _mkTask("t1", "2026-04-25T10:00:01Z", "PENDING");
    const filled = _mkTask("t1", "2026-04-25T10:00:02Z", "FILLED");
    useTasksStore.getState().upsertTask(pending);
    useTasksStore.getState().upsertTask(filled);
    expect(useTasksStore.getState().tasks[0].status).toBe("FILLED");
  });

  it("upsertTask allows non-terminal → non-terminal transitions", () => {
    const parsing = _mkTask("t1", "2026-04-25T10:00:01Z", "PARSING");
    const ready = _mkTask("t1", "2026-04-25T10:00:02Z", "INSTRUCTION_READY");
    useTasksStore.getState().upsertTask(parsing);
    useTasksStore.getState().upsertTask(ready);
    expect(useTasksStore.getState().tasks[0].status).toBe("INSTRUCTION_READY");
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

describe("labelsByTask", () => {
  beforeEach(() => {
    useTasksStore.setState({ tasks: [], pushEventsByTask: {}, labelsByTask: {} });
  });

  function _mkLabeled(id: string, verdict: "correct" | "corrected") {
    return { ..._mkTask(id, "2026-04-25T10:00:00Z"), label: { verdict, corrected_payload: null } };
  }

  it("setInitialTasks seeds labelsByTask from task.label", () => {
    useTasksStore.getState().setInitialTasks([_mkLabeled("t1", "correct")]);
    expect(useTasksStore.getState().labelsByTask["t1"].verdict).toBe("correct");
  });

  it("setInitialTasks rebuilds (drops stale labels)", () => {
    useTasksStore.setState({ labelsByTask: { told: { verdict: "correct", corrected_payload: null } } });
    useTasksStore.getState().setInitialTasks([_mkTask("t1", "2026-04-25T10:00:00Z")]);
    expect(useTasksStore.getState().labelsByTask).toEqual({});
  });

  it("upsertTask with null label does NOT clobber existing label", () => {
    useTasksStore.getState().setLabel("t1", { verdict: "correct", corrected_payload: null });
    useTasksStore.getState().upsertTask(_mkTask("t1", "2026-04-25T10:00:00Z"));
    expect(useTasksStore.getState().labelsByTask["t1"].verdict).toBe("correct");
  });

  it("setLabel(null) clears", () => {
    useTasksStore.getState().setLabel("t1", { verdict: "correct", corrected_payload: null });
    useTasksStore.getState().setLabel("t1", null);
    expect(useTasksStore.getState().labelsByTask["t1"]).toBeUndefined();
  });
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

  it("regression: child-monitor urls in urlSet are excluded from orphan results", () => {
    // Simulate the fix: allMonitoredUrls includes child page url "u3-child".
    // A task with that url must NOT appear in the orphan list.
    const tasksWithChild: TaskSummary[] = [
      makeTask("a", "u1"),          // top-level page
      makeTask("b", "u3-child"),    // sub-monitor page (child)
      makeTask("c", null),          // truly orphan (no url)
      makeTask("d", "u4-unknown"),  // truly orphan (url not in any monitor)
    ];
    const allMonitoredUrls = new Set(["u1", "u3-child"]); // merged top-level + child
    expect(selectTasksByUrl(tasksWithChild, null, allMonitoredUrls).map(t => t.id))
      .toEqual(["c", "d"]);
  });
});
