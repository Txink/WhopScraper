import { Card } from "../Card/Card";
import { fmtBeijingDate } from "../Card/cardHelpers";
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
  const nowIso = new Date().toISOString();
  const today = fmtBeijingDate(nowIso);
  const yesterday = fmtBeijingDate(new Date(Date.now() - 86400000).toISOString());
  if (dateKey === today) return `今天 ${dateKey}`;
  if (dateKey === yesterday) return `昨天 ${dateKey}`;
  return dateKey;
}

interface Props {
  pushEventsByTask: Record<string, PushEvent[]>;
  expandMode: ExpandMode;
  autoTrade: boolean;
  groups: Map<string, TaskSummary[]>;
  currentWeekKey: string | null;
}

export function TaskStream({
  pushEventsByTask,
  expandMode,
  autoTrade,
  groups,
  currentWeekKey,
}: Props) {
  if (currentWeekKey == null) return null;

  const weekTasks = groups.get(currentWeekKey) ?? [];

  const dayGroups = new Map<string, TaskSummary[]>();
  for (const t of weekTasks) {
    const ts = t.message?.posted_at ?? t.created_at;
    const dateKey = fmtBeijingDate(ts);
    if (!dayGroups.has(dateKey)) dayGroups.set(dateKey, []);
    dayGroups.get(dateKey)!.push(t);
  }
  const dateKeys = Array.from(dayGroups.keys());

  return (
    <>
      {dateKeys.map((dateKey) => {
        const dayTasks = dayGroups.get(dateKey)!;
        return (
          <div key={dateKey}>
            <div className="stream-divider">{formatDateLabel(dateKey)} · {dayTasks.length}</div>
            {dayTasks.map((t) => {
              const defaultExpanded =
                expandMode === "all-open" ? true :
                expandMode === "all-closed" ? false :
                isActiveExpanded(t);
              return (
                <Card
                  key={`${t.id}-${expandMode}`}
                  task={t}
                  pushEvents={pushEventsByTask[t.id] ?? []}
                  defaultExpanded={defaultExpanded}
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
