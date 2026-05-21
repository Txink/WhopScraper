import { useState } from "react";
import {
  addDays,
  formatDayLabel,
  monthOf,
} from "../Dashboard/weekUtils";
import { ChatCalendarPopover } from "./ChatCalendarPopover";
import "./DayPicker.css";

interface Props {
  selectedDate: string;
  maxDate: string;
  hasMessagesOnDay: (dayKey: string) => boolean;
  /** True while month-week prefetch is in flight; passed to the popover. */
  prefetching?: boolean;
  onChange: (dayKey: string) => void;
  /** Fires whenever the popover opens or closes (with the visible-month
   *  it is opening on), so the parent can drive prefetch. */
  onCalendarOpenChange: (open: boolean, visibleMonth: string) => void;
  /** Fires when the user pages the popover to a new month — parent uses
   *  this to prefetch that month. */
  onVisibleMonthChange: (monthKey: string) => void;
}

export function DayPicker({
  selectedDate,
  maxDate,
  hasMessagesOnDay,
  prefetching,
  onChange,
  onCalendarOpenChange,
  onVisibleMonthChange,
}: Props) {
  const [open, setOpen] = useState(false);
  const [visibleMonth, setVisibleMonth] = useState<string>(monthOf(selectedDate));

  const isAtMax = selectedDate >= maxDate;

  function toggleOpen(next?: boolean) {
    const willOpen = next ?? !open;
    if (willOpen) {
      // Re-anchor the calendar to the currently selected day's month each
      // time we re-open — feels more natural than keeping last-seen month.
      const month = monthOf(selectedDate);
      setVisibleMonth(month);
      onCalendarOpenChange(true, month);
    } else {
      onCalendarOpenChange(false, visibleMonth);
    }
    setOpen(willOpen);
  }

  function handleMonthChange(next: string) {
    setVisibleMonth(next);
    onVisibleMonthChange(next);
  }

  function handlePickDay(dayKey: string) {
    onChange(dayKey);
    toggleOpen(false);
  }

  return (
    <div className="day-picker">
      <button
        type="button"
        className="day-picker-arrow"
        aria-label="上一天"
        onClick={() => onChange(addDays(selectedDate, -1))}
      >
        ‹
      </button>
      <button
        type="button"
        className="day-picker-center"
        onClick={() => toggleOpen()}
      >
        {formatDayLabel(selectedDate)}
      </button>
      <button
        type="button"
        className="day-picker-arrow"
        aria-label="下一天"
        disabled={isAtMax}
        onClick={() => onChange(addDays(selectedDate, 1))}
      >
        ›
      </button>
      {open && (
        <ChatCalendarPopover
          visibleMonth={visibleMonth}
          selectedDate={selectedDate}
          maxDate={maxDate}
          hasMessagesOnDay={hasMessagesOnDay}
          loading={prefetching}
          onMonthChange={handleMonthChange}
          onPickDay={handlePickDay}
          onClose={() => toggleOpen(false)}
        />
      )}
    </div>
  );
}
