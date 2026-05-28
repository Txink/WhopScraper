import { useEffect } from "react";
import { api } from "../api/http";
import { useTasksStore } from "../stores/tasks";

// Statuses past the "order submitted" point — PENDING/PARTIAL/FILLED and the
// terminal failure states all plausibly carry push events. Used to decide
// whether to lazy-fetch full task detail. TaskSummary feeds (the list
// endpoint) omit push_events for performance; live WS pushes live in the
// store, but after a page reload they're gone — the fetch fills the gap.
const STATUSES_WITH_PUSHES: ReadonlySet<string> = new Set([
  "PENDING", "PARTIAL", "FILLED", "CANCELLED", "REJECTED", "SUBMIT_FAILED",
]);

/**
 * Rehydrate a task's push events from the persisted backend detail when the
 * store has none (e.g. after a page reload) but the task's status implies it
 * should. Shared by the expanded card and the chat signal bubble so both
 * render the full push chain instead of just the synthetic "已提交" node.
 */
export function useLazyPushEvents(
  taskId: string,
  status: string,
  currentCount: number,
  enabled = true,
): void {
  useEffect(() => {
    if (!enabled) return;
    if (currentCount > 0) return;
    if (!STATUSES_WITH_PUSHES.has(status)) return;
    let cancelled = false;
    api.getTask(taskId)
      .then((full) => {
        if (cancelled) return;
        const append = useTasksStore.getState().appendPushEvent;
        for (const evt of full.push_events) {
          append(taskId, evt);
        }
      })
      .catch((e) => {
        console.warn("useLazyPushEvents: failed to lazy-load push events:", e);
      });
    return () => { cancelled = true; };
  }, [taskId, status, currentCount, enabled]);
}
