import { useEffect, useRef, useState } from "react";
import type { UIEvent } from "react";
import type { WeekInfo } from "./weekUtils";

export interface WeekPaginatorProps {
  weeks: WeekInfo[];
  currentWeekKey: string;
  onSelect: (key: string) => void;
}

// Row height — kept in sync with .week-paginator-row CSS. The wheel viewport
// is 3 × ITEM_H tall and pads ITEM_H above/below the inner list so first and
// last items can scroll into the center slot. The chip sits in front of the
// middle slot and acts as the "selection frame" of the wheel.
const ITEM_H = 26;

function CalendarIcon() {
  return (
    <svg
      className="week-paginator-cal"
      viewBox="0 0 16 16"
      width="12"
      height="12"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.4"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <rect x="2.25" y="3.25" width="11.5" height="10" rx="1.5" />
      <path d="M2.5 6.5h11" />
      <path d="M5.5 2v2.5M10.5 2v2.5" />
    </svg>
  );
}

function ChevronIcon({ open }: { open: boolean }) {
  return (
    <svg
      className="week-paginator-caret"
      data-open={open ? "true" : "false"}
      viewBox="0 0 12 12"
      width="10"
      height="10"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <polyline points="3 4.5 6 7.5 9 4.5" />
    </svg>
  );
}

export function WeekPaginator({ weeks, currentWeekKey, onSelect }: WeekPaginatorProps) {
  const [expanded, setExpanded] = useState(false);
  const [centeredKey, setCenteredKey] = useState(currentWeekKey);
  const containerRef = useRef<HTMLDivElement | null>(null);
  const wheelRef = useRef<HTMLDivElement | null>(null);
  const chipRef = useRef<HTMLButtonElement | null>(null);

  const current = weeks.find((w) => w.key === currentWeekKey);
  const currentIndex = weeks.findIndex((w) => w.key === currentWeekKey);
  const centered = weeks.find((w) => w.key === centeredKey) ?? current;
  const canExpand = weeks.length > 1;

  // External selection changes reset the centered candidate.
  useEffect(() => {
    setCenteredKey(currentWeekKey);
  }, [currentWeekKey]);

  // On expand: reset centered to current and align the wheel so the current
  // week sits in the middle slot (right behind the chip's selection frame).
  useEffect(() => {
    if (!expanded) return;
    setCenteredKey(currentWeekKey);
    const wheel = wheelRef.current;
    if (!wheel) return;
    wheel.scrollTop = currentIndex * ITEM_H;
  }, [expanded, currentIndex, currentWeekKey]);

  // Outside click collapses (no commit).
  useEffect(() => {
    if (!expanded) return;
    function onDocMouseDown(e: MouseEvent) {
      const node = containerRef.current;
      if (node && !node.contains(e.target as Node)) {
        setExpanded(false);
      }
    }
    document.addEventListener("mousedown", onDocMouseDown);
    return () => document.removeEventListener("mousedown", onDocMouseDown);
  }, [expanded]);

  // Step-based wheel handler attached to the whole paginator container so
  // events from the chip (which overlays the wheel's middle slot) and from
  // the visible wheel rows above/below the chip are handled consistently.
  // We intentionally bypass the browser's native scroll because:
  //   1. CSS scroll-snap fights `scrollTop += deltaY` set programmatically,
  //      so the chip-forwarded scroll felt stuck.
  //   2. Continuous (non-integer) scrollTop briefly puts two rows at the
  //      chip's edges, leaking partial text in/out.
  // The accumulator cleanly maps any wheel input to integer ITEM_H steps —
  // scrollTop is always a snapped position, so the chip frame perfectly
  // overlays exactly one row at any time.
  useEffect(() => {
    if (!expanded) return;
    const container = containerRef.current;
    if (!container) return;
    let acc = 0;
    function onWheel(e: WheelEvent) {
      e.preventDefault();
      const wheel = wheelRef.current;
      if (!wheel) return;
      // Reset accumulator on direction change so back-and-forth feels snappy.
      if (acc !== 0 && Math.sign(e.deltaY) !== Math.sign(acc)) acc = 0;
      acc += e.deltaY;
      const stepDir = acc >= ITEM_H ? 1 : acc <= -ITEM_H ? -1 : 0;
      if (stepDir === 0) return;
      const currentIdx = Math.round(wheel.scrollTop / ITEM_H);
      const targetIdx = Math.max(
        0,
        Math.min(weeks.length - 1, currentIdx + stepDir),
      );
      if (targetIdx !== currentIdx) {
        wheel.scrollTop = targetIdx * ITEM_H;
      }
      acc -= stepDir * ITEM_H;
    }
    container.addEventListener("wheel", onWheel, { passive: false });
    return () => container.removeEventListener("wheel", onWheel);
  }, [expanded, weeks.length]);

  function onWheelScroll(e: UIEvent<HTMLDivElement>) {
    const idx = Math.max(
      0,
      Math.min(weeks.length - 1, Math.round(e.currentTarget.scrollTop / ITEM_H)),
    );
    const k = weeks[idx]?.key;
    if (k && k !== centeredKey) setCenteredKey(k);
  }

  function onChipClick() {
    if (!canExpand) return;
    if (!expanded) {
      setExpanded(true);
      return;
    }
    // Expanded → second click commits whatever the chip is currently
    // framing (the centered row of the wheel) and collapses.
    if (centeredKey !== currentWeekKey) onSelect(centeredKey);
    setExpanded(false);
  }

  function onRowClick(key: string) {
    if (key !== currentWeekKey) onSelect(key);
    setExpanded(false);
  }

  if (!current || !centered) return null;

  // While expanded, the chip mirrors the row currently aligned with it —
  // that is the candidate that a chip-click would commit.
  const chipDisplay = expanded ? centered : current;

  return (
    <div className="week-paginator" ref={containerRef}>
      {expanded && (
        <div className="week-paginator-frame">
          <div
            className="week-paginator-wheel"
            ref={wheelRef}
            onScroll={onWheelScroll}
            role="listbox"
            data-centered-key={centeredKey}
          >
            {weeks.map((w) => {
              const isCentered = w.key === centeredKey;
              return (
                <button
                  key={w.key}
                  type="button"
                  role="option"
                  aria-selected={isCentered}
                  className={`week-paginator-row${isCentered ? " centered" : ""}`}
                  onClick={() => onRowClick(w.key)}
                >
                  {w.startLabel} ~ {w.endLabel}
                </button>
              );
            })}
          </div>
        </div>
      )}
      <button
        ref={chipRef}
        type="button"
        className={`week-paginator-chip current${expanded ? " open" : ""}`}
        onClick={onChipClick}
        disabled={!canExpand}
      >
        <CalendarIcon />
        <span className="week-paginator-range">
          {chipDisplay.startLabel} ~ {chipDisplay.endLabel}
        </span>
        {canExpand && <ChevronIcon open={expanded} />}
      </button>
    </div>
  );
}
