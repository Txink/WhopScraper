import { useEffect, useMemo, useRef } from "react";
import {
  addDays,
  chatTodayInShanghai,
  daysInMonth,
  monthOf,
} from "../Dashboard/weekUtils";
import "./DayPicker.css";

interface Props {
  /** "YYYY-MM" — controls which month grid is shown. */
  visibleMonth: string;
  /** "YYYY-MM-DD" — currently selected day (may be outside visibleMonth). */
  selectedDate: string;
  /** Latest selectable date; days after this are disabled. */
  maxDate: string;
  /** Whether to show a dot under a given day (caller's data source). */
  hasMessagesOnDay: (dayKey: string) => boolean;
  /** Optional "loading" indicator at the bottom while prefetch is in flight. */
  loading?: boolean;
  onMonthChange: (nextMonthKey: string) => void;
  onPickDay: (dayKey: string) => void;
  onClose: () => void;
}

/** 6-row × 7-col fixed grid starting on Monday. Cells before the 1st and
 *  after the last belong to neighboring months (rendered dim, still
 *  clickable so the user can jump into them). */
function buildGrid(monthKey: string): { dayKey: string; inMonth: boolean }[] {
  const days = daysInMonth(monthKey);
  const first = days[0];
  const last = days[days.length - 1];
  const m = first.match(/^(\d{4})-(\d{2})-(\d{2})$/)!;
  const firstAnchor = new Date(
    Date.UTC(Number(m[1]), Number(m[2]) - 1, Number(m[3])),
  );
  const firstWdSun0 = firstAnchor.getUTCDay(); // Sun=0..Sat=6
  // Convert to Monday-first index (Mon=0..Sun=6).
  const firstWdMon0 = (firstWdSun0 + 6) % 7;

  const cells: { dayKey: string; inMonth: boolean }[] = [];
  for (let i = firstWdMon0; i > 0; i--) {
    cells.push({ dayKey: addDays(first, -i), inMonth: false });
  }
  for (const d of days) {
    cells.push({ dayKey: d, inMonth: true });
  }
  while (cells.length < 42) {
    cells.push({
      dayKey: addDays(last, cells.length - (firstWdMon0 + days.length) + 1),
      inMonth: false,
    });
  }
  return cells;
}

export function ChatCalendarPopover({
  visibleMonth,
  selectedDate,
  maxDate,
  hasMessagesOnDay,
  loading,
  onMonthChange,
  onPickDay,
  onClose,
}: Props) {
  const rootRef = useRef<HTMLDivElement | null>(null);

  // Click-outside-to-close.
  useEffect(() => {
    function onDocMouseDown(e: MouseEvent) {
      if (!rootRef.current) return;
      if (!rootRef.current.contains(e.target as Node)) onClose();
    }
    document.addEventListener("mousedown", onDocMouseDown);
    return () => document.removeEventListener("mousedown", onDocMouseDown);
  }, [onClose]);

  const cells = useMemo(() => buildGrid(visibleMonth), [visibleMonth]);
  const today = chatTodayInShanghai();

  const [year, monthNum] = visibleMonth.split("-").map(Number);
  const titleZh = `${year} 年 ${monthNum} 月`;

  const prevMonthKey = (mk: string): string => {
    const [y, m] = mk.split("-").map(Number);
    const ny = m === 1 ? y - 1 : y;
    const nm = m === 1 ? 12 : m - 1;
    return `${ny}-${String(nm).padStart(2, "0")}`;
  };
  const nextMonthKey = (mk: string): string => {
    const [y, m] = mk.split("-").map(Number);
    const ny = m === 12 ? y + 1 : y;
    const nm = m === 12 ? 1 : m + 1;
    return `${ny}-${String(nm).padStart(2, "0")}`;
  };

  return (
    <div className="calendar-popover" ref={rootRef} role="dialog" aria-label="选择日期">
      <div className="calendar-head">
        <button
          type="button"
          aria-label="上个月"
          onClick={() => onMonthChange(prevMonthKey(visibleMonth))}
        >
          ‹
        </button>
        <div className="calendar-title">{titleZh}</div>
        <button
          type="button"
          aria-label="下个月"
          onClick={() => onMonthChange(nextMonthKey(visibleMonth))}
        >
          ›
        </button>
      </div>
      <div className="calendar-week-names">
        <span>一</span><span>二</span><span>三</span><span>四</span>
        <span>五</span><span>六</span><span>日</span>
      </div>
      <div className="calendar-grid">
        {cells.map(({ dayKey, inMonth }) => {
          const disabled = dayKey > maxDate;
          const isToday = dayKey === today;
          const isSelected = dayKey === selectedDate;
          const showDot = hasMessagesOnDay(dayKey);
          const classes = [
            "calendar-cell",
            !inMonth && "is-other-month",
            isToday && "is-today",
            isSelected && "is-selected",
          ]
            .filter(Boolean)
            .join(" ");
          const dayNum = Number(dayKey.slice(-2));
          return (
            <button
              key={dayKey}
              type="button"
              className={classes}
              disabled={disabled}
              onClick={() => {
                if (!inMonth) onMonthChange(monthOf(dayKey));
                onPickDay(dayKey);
              }}
            >
              {dayNum}
              {showDot && <span className="calendar-dot" />}
            </button>
          );
        })}
      </div>
      {loading && <div className="calendar-loading">加载中…</div>}
    </div>
  );
}
