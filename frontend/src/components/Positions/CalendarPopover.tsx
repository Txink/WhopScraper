import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";

interface Props {
  open: boolean;
  /** Trigger element the popover positions against. */
  anchorRef: React.RefObject<HTMLElement>;
  /** Card container the popover stays inside. Must be position:
   *  relative/absolute in CSS. */
  containerRef: React.RefObject<HTMLElement>;
  /** Currently-selected ET dates (YYYY-MM-DD). Order = series index. */
  selectedDates: string[];
  /** Max simultaneous selections; clicks past this cap are ignored
   *  unless the click is on an already-selected date (which deselects). */
  max: number;
  /** Color per selection slot, in the same order as selectedDates would
   *  use; index `i` is the color for the i-th distinct date the user
   *  picks. Passed in so the chart and the calendar agree on the
   *  date↔color mapping without duplicating the palette. */
  slotColors: string[];
  onToggle(date: string): void;
  onClose(): void;
}

/** YYYY-MM-DD for a Date in the calendar's local computation tz. We
 *  intentionally use UTC component reads against UTC-midnight dates so
 *  the grid math is timezone-agnostic. Selected dates are also stored
 *  as plain YYYY-MM-DD strings (ET trading-day naming). */
function fmtYmd(y: number, m: number, d: number): string {
  return `${y}-${String(m + 1).padStart(2, "0")}-${String(d).padStart(2, "0")}`;
}

function todayYmd(): string {
  // Today in ET — the same "trading day" convention used elsewhere in
  // the detail view. Using Intl avoids DST surprises around the dateline.
  const fmt = new Intl.DateTimeFormat("en-CA", {
    timeZone: "America/New_York",
    year: "numeric", month: "2-digit", day: "2-digit",
  });
  return fmt.format(new Date());
}

/**
 * Anchored calendar dropdown for the 多日重叠 tab.
 *
 * Layout follows TabPopover's anchoring logic (absolute inside
 * `containerRef`, shifts left if it'd overflow). Each cell shows the day
 * number; selected cells render with their assigned slot color so the
 * user can read the legend straight off the calendar. Click toggles;
 * Escape / click-outside / weekend (locked) all close on their normal
 * paths. Selected dates beyond `max` are ignored at the dispatch site —
 * we still render them as clickable so the user can deselect.
 *
 * Today's cell carries a subtle outline; future days are dimmed and
 * non-interactive (no historical data exists yet).
 */
export function CalendarPopover({
  open, anchorRef, containerRef,
  selectedDates, max, slotColors,
  onToggle, onClose,
}: Props) {
  const popRef = useRef<HTMLDivElement | null>(null);
  const [pos, setPos] = useState<{ left: number; top: number; caretLeft: number } | null>(null);

  // Month being shown in the grid. Defaults to the month containing the
  // most-recent selection (if any) or today.
  const initialMonthDate = useMemo(() => {
    const seed = selectedDates[selectedDates.length - 1] ?? todayYmd();
    const [y, m] = seed.split("-").map(Number);
    return new Date(Date.UTC(y, m - 1, 1));
  }, [open]); // re-seed only on open so navigating doesn't snap back
  const [viewMonth, setViewMonth] = useState<Date>(initialMonthDate);
  useEffect(() => { if (open) setViewMonth(initialMonthDate); }, [open, initialMonthDate]);

  const today = useMemo(() => todayYmd(), []);

  // Build the 6×7 grid for the visible month — leading cells from the
  // previous month, trailing cells from the next, so each row is a
  // complete week starting Monday (ISO convention).
  const grid = useMemo(() => {
    const y = viewMonth.getUTCFullYear();
    const m = viewMonth.getUTCMonth();
    const firstOfMonth = new Date(Date.UTC(y, m, 1));
    // Mon = 0, …, Sun = 6.
    const leadingBlanks = (firstOfMonth.getUTCDay() + 6) % 7;
    const daysInMonth = new Date(Date.UTC(y, m + 1, 0)).getUTCDate();
    const cells: Array<{ ymd: string; day: number; inMonth: boolean }> = [];
    // Previous-month fillers.
    if (leadingBlanks > 0) {
      const prevLast = new Date(Date.UTC(y, m, 0)).getUTCDate();
      for (let i = leadingBlanks - 1; i >= 0; i--) {
        const d = prevLast - i;
        cells.push({ ymd: fmtYmd(y, m - 1, d), day: d, inMonth: false });
      }
    }
    for (let d = 1; d <= daysInMonth; d++) {
      cells.push({ ymd: fmtYmd(y, m, d), day: d, inMonth: true });
    }
    // Pad to a full 6-row grid (42 cells) so the popover height
    // doesn't jitter when the month start / length changes.
    let tail = 1;
    while (cells.length < 42) {
      cells.push({ ymd: fmtYmd(y, m + 1, tail), day: tail, inMonth: false });
      tail++;
    }
    return cells;
  }, [viewMonth]);

  // Position before paint — same idea as TabPopover so users never see
  // a (0,0) frame.
  useLayoutEffect(() => {
    if (!open) { setPos(null); return; }
    const anchor = anchorRef.current;
    const container = containerRef.current;
    const pop = popRef.current;
    if (!anchor || !container || !pop) return;
    const a = anchor.getBoundingClientRect();
    const c = container.getBoundingClientRect();
    const popW = pop.offsetWidth || 280;
    const idealLeft = a.left - c.left;
    const maxLeft = c.width - popW - 4;
    const left = Math.min(Math.max(0, idealLeft), Math.max(0, maxLeft));
    const top = a.bottom - c.top + 6;
    const caretLeft = a.left - c.left - left + a.width / 2 - 6;
    setPos({ left, top, caretLeft });
  }, [open, anchorRef, containerRef]);

  // Escape + click-outside dismissal.
  useEffect(() => {
    if (!open) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    function onDown(e: MouseEvent) {
      const pop = popRef.current;
      const anchor = anchorRef.current;
      const target = e.target as Node | null;
      if (!target) return;
      if (pop?.contains(target)) return;
      if (anchor?.contains(target)) return;
      onClose();
    }
    document.addEventListener("keydown", onKey);
    document.addEventListener("mousedown", onDown);
    return () => {
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("mousedown", onDown);
    };
  }, [open, anchorRef, onClose]);

  if (!open) return null;

  // Color lookup — map each currently-selected date to its slot color.
  const colorByDate = new Map<string, string>();
  selectedDates.forEach((d, i) => {
    colorByDate.set(d, slotColors[i] ?? slotColors[slotColors.length - 1]!);
  });

  const monthLabel = (() => {
    const fmt = new Intl.DateTimeFormat("zh-CN", {
      year: "numeric", month: "long", timeZone: "UTC",
    });
    return fmt.format(viewMonth);
  })();

  const stepMonth = (delta: number) => {
    setViewMonth((d) => {
      const y = d.getUTCFullYear();
      const m = d.getUTCMonth();
      return new Date(Date.UTC(y, m + delta, 1));
    });
  };

  return (
    <div
      ref={popRef}
      role="dialog"
      className="tab-popover calendar-popover"
      style={pos ? { left: pos.left, top: pos.top } : { visibility: "hidden" }}
      // Stop arrow keys etc. from bubbling into chart canvas listeners.
      onClick={(e) => e.stopPropagation()}
    >
      {pos && (
        <span className="tab-popover-caret" style={{ left: pos.caretLeft }} aria-hidden />
      )}
      <div className="calendar-head">
        <button className="calendar-nav" onClick={() => stepMonth(-1)} aria-label="上个月">‹</button>
        <span className="calendar-title">{monthLabel}</span>
        <button className="calendar-nav" onClick={() => stepMonth(1)} aria-label="下个月">›</button>
      </div>
      <div className="calendar-weekdays">
        {["一", "二", "三", "四", "五", "六", "日"].map((w) => (
          <span key={w}>{w}</span>
        ))}
      </div>
      <div className="calendar-grid">
        {grid.map((cell) => {
          const isSelected = colorByDate.has(cell.ymd);
          const isFuture = cell.ymd > today;
          const isToday = cell.ymd === today;
          // Cap-locked: at max, only deselect clicks pass; new selects
          // are visually muted via the disabled class.
          const lockedByCap = !isSelected && selectedDates.length >= max;
          const color = colorByDate.get(cell.ymd);
          // Inline style for selected cells so each date picks up its
          // assigned slot color from the palette; non-selected cells use
          // the static CSS rules.
          const style: React.CSSProperties = isSelected && color
            ? { background: color, borderColor: color, color: "#0b0f14" }
            : {};
          const cls = [
            "calendar-cell",
            cell.inMonth ? "" : "out-of-month",
            isFuture ? "future" : "",
            isToday ? "today" : "",
            isSelected ? "selected" : "",
            lockedByCap ? "disabled" : "",
          ].filter(Boolean).join(" ");
          return (
            <button
              key={cell.ymd}
              className={cls}
              style={style}
              disabled={isFuture || lockedByCap}
              onClick={() => onToggle(cell.ymd)}
              title={cell.ymd}
            >
              {cell.day}
            </button>
          );
        })}
      </div>
      <div className="calendar-foot">
        {selectedDates.length === 0
          ? <span className="hint">选择日期以叠加（最多 {max} 个）</span>
          : <span className="hint">已选 {selectedDates.length} / {max}</span>}
      </div>
    </div>
  );
}
