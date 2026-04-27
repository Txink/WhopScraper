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
