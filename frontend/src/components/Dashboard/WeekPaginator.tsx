import { useEffect, useRef, useState } from "react";
import type { WeekInfo } from "./weekUtils";

export interface WeekPaginatorProps {
  weeks: WeekInfo[];
  currentWeekKey: string;
  onSelect: (key: string) => void;
}

export function WeekPaginator({ weeks, currentWeekKey, onSelect }: WeekPaginatorProps) {
  const [expanded, setExpanded] = useState(false);
  const stripRef = useRef<HTMLDivElement | null>(null);

  const current = weeks.find((w) => w.key === currentWeekKey);
  const currentIndex = weeks.findIndex((w) => w.key === currentWeekKey);
  const canExpand = weeks.length > 1;
  const scrollMode: "start" | "center" | "end" =
    currentIndex <= 0
      ? "start"
      : currentIndex >= weeks.length - 1
        ? "end"
        : "center";

  useEffect(() => {
    if (!expanded) return;
    function onDocMouseDown(e: MouseEvent) {
      if (stripRef.current && !stripRef.current.contains(e.target as Node)) {
        setExpanded(false);
      }
    }
    document.addEventListener("mousedown", onDocMouseDown);
    return () => document.removeEventListener("mousedown", onDocMouseDown);
  }, [expanded]);

  useEffect(() => {
    if (!expanded) return;
    const el = stripRef.current;
    if (!el) return;
    const chip = el.children[currentIndex] as HTMLElement | undefined;
    if (!chip) return;
    if (scrollMode === "start") {
      el.scrollLeft = 0;
    } else if (scrollMode === "end") {
      el.scrollLeft = el.scrollWidth - el.clientWidth;
    } else {
      el.scrollLeft = chip.offsetLeft - (el.clientWidth - chip.clientWidth) / 2;
    }
  }, [expanded, currentIndex, scrollMode]);

  if (!current) return null;

  if (!expanded) {
    return (
      <button
        type="button"
        className="week-paginator-chip current collapsed"
        onClick={() => canExpand && setExpanded(true)}
        disabled={!canExpand}
      >
        {current.startLabel} ~ {current.endLabel}
        {canExpand && <span className="week-paginator-caret">▸</span>}
      </button>
    );
  }

  return (
    <div
      className="week-paginator-strip"
      role="listbox"
      ref={stripRef}
      data-scroll-mode={scrollMode}
    >
      {weeks.map((w) => {
        const isCurrent = w.key === currentWeekKey;
        return (
          <button
            type="button"
            key={w.key}
            role="option"
            aria-selected={isCurrent}
            className={`week-paginator-chip${isCurrent ? " current" : ""}`}
            onClick={() => {
              onSelect(w.key);
              setExpanded(false);
            }}
          >
            {w.startLabel} ~ {w.endLabel}
            {isCurrent && <span className="week-paginator-caret">▾</span>}
          </button>
        );
      })}
    </div>
  );
}
