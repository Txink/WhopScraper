import { create } from "zustand";
import type { TaskSummary, PushEvent } from "../api/domain-types";
import type { WsEvent } from "../api/ws";

interface TaskState {
  tasks: TaskSummary[];
  pushEventsByTask: Record<string, PushEvent[]>;
  upsertTask(task: TaskSummary): void;
  appendPushEvent(taskId: string, event: PushEvent): void;
  setInitialTasks(tasks: TaskSummary[]): void;
  applyWsEvent(evt: WsEvent): void;
  removeTasksByUrl(url: string | null): void;
}

export const useTasksStore = create<TaskState>((set, get) => ({
  tasks: [],
  pushEventsByTask: {},

  setInitialTasks(tasks) {
    set({ tasks });
  },

  upsertTask(task) {
    set((state) => {
      const filtered = state.tasks.filter((t) => t.id !== task.id);
      // Insert by created_at desc
      const newList = [...filtered, task].sort(
        (a, b) => b.created_at.localeCompare(a.created_at),
      );
      return { tasks: newList };
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
      return {
        tasks: state.tasks.filter((t) => !removedIds.has(t.id)),
        pushEventsByTask: remainingPush,
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
