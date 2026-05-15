import { Card } from "../Card/Card";
import { fmtBeijingDate } from "../Card/cardHelpers";
import type { TaskSummary, PushEvent } from "../../api/domain-types";
import { usePageTabsStore } from "../../stores/pageTabs";

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
  autoTrade: boolean;
  groups: Map<string, TaskSummary[]>;
  currentWeekKey: string | null;
  /** Identifies the tab we're rendering for — drives the single-accordion
   *  expand state lookup. Page tabs use the page id; the orphan view uses
   *  ``"orphan"``. */
  tabKey: string;
}

/** Stream of task cards for one week + day grouping. All cards render
 *  collapsed by default; clicking a card expands it and collapses any
 *  previously-expanded card on the same tab. */
export function TaskStream({
  pushEventsByTask,
  autoTrade,
  groups,
  currentWeekKey,
  tabKey,
}: Props) {
  const expandedTaskId = usePageTabsStore(
    (s) => s.expandedTaskIdByTab[tabKey] ?? null,
  );
  const toggleExpandedTask = usePageTabsStore((s) => s.toggleExpandedTask);

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
            {dayTasks.map((t) => (
              <Card
                key={t.id}
                task={t}
                pushEvents={pushEventsByTask[t.id] ?? []}
                expanded={expandedTaskId === t.id}
                onToggle={() => toggleExpandedTask(tabKey, t.id)}
                autoTrade={autoTrade}
              />
            ))}
          </div>
        );
      })}
    </>
  );
}
