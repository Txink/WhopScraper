import { create } from "zustand";
import type { TaskSummary, PushEvent, InstructionLabel } from "../api/domain-types";
import type { WsEvent } from "../api/ws";

// Mirrors backend app.domain.status.TERMINAL — once a task lands in any of
// these the store must NOT accept a regression to a non-terminal status from
// a stale WS payload. Without this guard, a race-y push handler that
// publishes its in-memory PENDING task AFTER another handler published the
// authoritative REJECTED can flip the displayed status back to "等待成交".
const TERMINAL_STATUSES: ReadonlySet<string> = new Set([
  "PARSE_ERROR",
  "SUBMIT_FAILED",
  "FILLED",
  "CANCELLED",
  "REJECTED",
  "SKIPPED",
]);

interface TaskState {
  tasks: TaskSummary[];
  pushEventsByTask: Record<string, PushEvent[]>;
  labelsByTask: Record<string, InstructionLabel>;
  upsertTask(task: TaskSummary): void;
  appendPushEvent(taskId: string, event: PushEvent): void;
  setInitialTasks(tasks: TaskSummary[]): void;
  applyWsEvent(evt: WsEvent): void;
  removeTasksByUrl(url: string | null): void;
  setLabel(taskId: string, label: InstructionLabel | null): void;
}

export const useTasksStore = create<TaskState>((set, get) => ({
  tasks: [],
  pushEventsByTask: {},
  labelsByTask: {},

  setInitialTasks(tasks) {
    const labelsByTask: Record<string, InstructionLabel> = {};
    for (const t of tasks) {
      if (t.label != null) labelsByTask[t.id] = t.label;
    }
    set({ tasks, labelsByTask });
  },

  upsertTask(task) {
    set((state) => {
      const existing = state.tasks.find((t) => t.id === task.id);
      // Terminal-status protection: if the store already has a terminal
      // status for this task, do NOT let a stale incoming non-terminal
      // payload regress it. We DO let the incoming task overwrite other
      // mutable fields (reject_reason, push_events count via the merge
      // below) by carrying the existing terminal status forward instead.
      let incoming: TaskSummary = task;
      if (
        existing
        && TERMINAL_STATUSES.has(existing.status)
        && !TERMINAL_STATUSES.has(task.status)
      ) {
        incoming = {
          ...task,
          status: existing.status,
          reject_reason: task.reject_reason ?? existing.reject_reason,
        };
      }
      const filtered = state.tasks.filter((t) => t.id !== task.id);
      // Insert by created_at desc
      const newList = [...filtered, incoming].sort(
        (a, b) => b.created_at.localeCompare(a.created_at),
      );
      const labelsByTask = task.label != null
        ? { ...state.labelsByTask, [task.id]: task.label }
        : state.labelsByTask;
      return { tasks: newList, labelsByTask };
    });
  },

  setLabel(taskId, label) {
    set((state) => {
      const next = { ...state.labelsByTask };
      if (label == null) delete next[taskId];
      else next[taskId] = label;
      return { labelsByTask: next };
    });
  },

  appendPushEvent(taskId, event) {
    set((state) => {
      const prior = state.pushEventsByTask[taskId] ?? [];
      // Dedupe by event.id
      if (prior.some((p) => p.id === event.id)) return state;
      return {
        pushEventsByTask: {
          ...state.pushEventsByTask,
          [taskId]: [...prior, event],
        },
      };
    });
  },

  applyWsEvent(evt) {
    const payload = evt.payload as { task?: TaskSummary; push_event?: PushEvent };
    if (payload.task) {
      get().upsertTask(payload.task);
    }
    if (payload.push_event && payload.task) {
      get().appendPushEvent(payload.task.id, payload.push_event);
    }
  },

  removeTasksByUrl(url) {
    set((state) => {
      const removedIds = new Set(
        state.tasks
          .filter((t) => (t.message?.url ?? null) === url)
          .map((t) => t.id),
      );
      if (removedIds.size === 0) return state;
      const remainingPush: Record<string, PushEvent[]> = {};
      for (const [taskId, events] of Object.entries(state.pushEventsByTask)) {
        if (!removedIds.has(taskId)) remainingPush[taskId] = events;
      }
      const remainingLabels: Record<string, InstructionLabel> = {};
      for (const [taskId, label] of Object.entries(state.labelsByTask)) {
        if (!removedIds.has(taskId)) remainingLabels[taskId] = label;
      }
      return {
        tasks: state.tasks.filter((t) => !removedIds.has(t.id)),
        pushEventsByTask: remainingPush,
        labelsByTask: remainingLabels,
      };
    });
  },
}));

/**
 * Filter tasks by url (membership in pageUrls). null = orphan filter:
 *   includes tasks with url=null OR url not in pageUrls.
 */
export function selectTasksByUrl(
  tasks: TaskSummary[],
  url: string | null,
  pageUrls: Set<string>,
): TaskSummary[] {
  if (url === null) {
    return tasks.filter(t => t.message?.url == null || !pageUrls.has(t.message.url));
  }
  return tasks.filter(t => t.message?.url === url);
}
