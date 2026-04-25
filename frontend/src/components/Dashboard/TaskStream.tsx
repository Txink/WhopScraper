import { Card } from "../Card/Card";
import type { TaskSummary, PushEvent } from "../../api/domain-types";
import type { ExpandMode } from "../../stores/pageTabs";

const ACTIVE_STATUSES = new Set([
  "RECEIVED", "PARSING", "INSTRUCTION_READY",
  "SUBMITTING", "PENDING", "PARTIAL",
]);

function isActiveExpanded(task: TaskSummary): boolean {
  if (ACTIVE_STATUSES.has(task.status)) return true;
  if (task.status === "FILLED") {
    const updatedAt = new Date(task.updated_at).getTime();
    return Date.now() - updatedAt < 30_000;
  }
  return false;
}

function formatDateLabel(dateKey: string): string {
  const today = new Date().toISOString().slice(0, 10);
  const yesterday = new Date(Date.now() - 86400000).toISOString().slice(0, 10);
  if (dateKey === today) return `今天 ${dateKey}`;
  if (dateKey === yesterday) return `昨天 ${dateKey}`;
  return dateKey;
}

interface Props {
  tasks: TaskSummary[];
  pushEventsByTask: Record<string, PushEvent[]>;
  expandMode: ExpandMode;
  autoTrade: boolean;
}

export function TaskStream({ tasks, pushEventsByTask, expandMode, autoTrade }: Props) {
  const sorted = [...tasks].sort((a, b) => {
    const aTime = a.message?.posted_at ?? a.created_at;
    const bTime = b.message?.posted_at ?? b.created_at;
    return bTime.localeCompare(aTime);
  });
  const groups = new Map<string, TaskSummary[]>();
  for (const t of sorted) {
    const ts = t.message?.posted_at ?? t.created_at;
    const dateKey = ts.slice(0, 10);
    if (!groups.has(dateKey)) groups.set(dateKey, []);
    groups.get(dateKey)!.push(t);
  }
  const dateKeys = Array.from(groups.keys());

  return (
    <>
      {dateKeys.map(dateKey => {
        const dayTasks = groups.get(dateKey)!;
        return (
          <div key={dateKey}>
            <div className="stream-divider">{formatDateLabel(dateKey)} · {dayTasks.length}</div>
            {dayTasks.map(t => {
              const expanded =
                expandMode === "all-open" ? true :
                expandMode === "all-closed" ? false :
                isActiveExpanded(t);
              // KEY trick: include expandMode in key so card re-mounts when mode flips,
              // forcing the new defaultExpanded to take effect (Card uses internal useState).
              return (
                <Card
                  key={`${t.id}-${expandMode}`}
                  task={t}
                  pushEvents={pushEventsByTask[t.id] ?? []}
                  defaultExpanded={expanded}
                  autoTrade={autoTrade}
                />
              );
            })}
          </div>
        );
      })}
    </>
  );
}
