import { useState } from "react";
import type { WeekInfo } from "./weekUtils";

export interface WeekPaginatorProps {
  weeks: WeekInfo[];
  currentWeekKey: string;
  onSelect: (key: string) => void;
}

export function WeekPaginator({ weeks, currentWeekKey, onSelect }: WeekPaginatorProps) {
  const [expanded, setExpanded] = useState(false);
  const current = weeks.find((w) => w.key === currentWeekKey);
  if (!current) return null;
  const canExpand = weeks.length > 1;

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
    <div className="week-paginator-strip" role="listbox">
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
