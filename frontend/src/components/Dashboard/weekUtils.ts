export function weekKeyOf(ts: string): string {
  const d = new Date(ts);
  const sunday = new Date(d);
  sunday.setHours(0, 0, 0, 0);
  sunday.setDate(d.getDate() - d.getDay());
  const yyyy = sunday.getFullYear();
  const mm = String(sunday.getMonth() + 1).padStart(2, "0");
  const dd = String(sunday.getDate()).padStart(2, "0");
  return `${yyyy}-${mm}-${dd}`;
}

export interface WeekRange {
  startLabel: string;
  endLabel: string;
}

export function formatWeekRange(weekKey: string): WeekRange {
  const [y, m, d] = weekKey.split("-").map(Number);
  const start = new Date(y, m - 1, d);
  const end = new Date(y, m - 1, d + 6);
  const fmt = (date: Date) =>
    `${String(date.getMonth() + 1).padStart(2, "0")}/${String(
      date.getDate(),
    ).padStart(2, "0")}`;
  return { startLabel: fmt(start), endLabel: fmt(end) };
}

import type { TaskSummary } from "../../api/domain-types";

export interface WeekInfo {
  key: string;
  startLabel: string;
  endLabel: string;
}

export interface ComputedWeeks {
  groups: Map<string, TaskSummary[]>;
  weeks: WeekInfo[];
}

function taskTime(t: TaskSummary): string {
  return t.message?.posted_at ?? t.created_at;
}

export function computeWeeks(tasks: TaskSummary[]): ComputedWeeks {
  const sorted = [...tasks].sort((a, b) => taskTime(b).localeCompare(taskTime(a)));
  const groups = new Map<string, TaskSummary[]>();
  for (const t of sorted) {
    const key = weekKeyOf(taskTime(t));
    let bucket = groups.get(key);
    if (!bucket) {
      bucket = [];
      groups.set(key, bucket);
    }
    bucket.push(t);
  }
  const weeks: WeekInfo[] = Array.from(groups.keys()).map((key) => ({
    key,
    ...formatWeekRange(key),
  }));
  return { groups, weeks };
}
