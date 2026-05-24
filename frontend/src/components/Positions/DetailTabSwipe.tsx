import {
  useCallback, useEffect, useRef, useState, type ReactNode,
} from "react";
import "./DetailTabSwipe.css";

export interface TabDef {
  id: string;
  label: string;
  content: ReactNode;
}

interface Props {
  tabs: TabDef[];
  index: number;
  onIndexChange: (i: number) => void;
}

const DRAG_THRESHOLD_PX = 8;
const SWIPE_DISTANCE_PX = 50;
const SWIPE_VELOCITY = 0.4;  // px/ms
/** Cumulative horizontal trackpad wheel delta required to commit a tab
 *  switch. Tuned so a deliberate two-finger swipe lands the next tab
 *  while inertia from vertical scrolling on a busy page doesn't drift it. */
const WHEEL_COMMIT_PX = 60;
/** Once a swipe has committed, the lock releases as soon as the wheel
 *  signal drops below this many pixels — i.e. the gesture has tapered
 *  toward zero (the natural end of any trackpad swipe / inertia tail). */
const WHEEL_TAPER_PX = 3;

/** Block drag-start only on text-entry elements where horizontal mouse
 *  movement should belong to caret/selection. Buttons and other
 *  click-only controls are fine — the 8px drag threshold keeps pure
 *  clicks from being mistaken for drags. */
function isTextInput(el: EventTarget | null): boolean {
  if (!(el instanceof HTMLElement)) return false;
  const tag = el.tagName;
  if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return true;
  return el.isContentEditable;
}

export function DetailTabSwipe({ tabs, index, onIndexChange }: Props) {
  const max = tabs.length - 1;
  const [dragDx, setDragDx] = useState(0);
  /** Latest props captured into refs so document-level listeners installed
   *  on mousedown stay accurate without re-attaching every render. */
  const indexRef = useRef(index);
  const maxRef = useRef(max);
  const onIndexChangeRef = useRef(onIndexChange);
  useEffect(() => {
    indexRef.current = index;
    maxRef.current = max;
    onIndexChangeRef.current = onIndexChange;
  }, [index, max, onIndexChange]);

  /** Drag-in-progress state. Once set, document-level mousemove/mouseup
   *  drive the drag through to release — the original element can lose
   *  the pointer (e.g. user drags out of the swipe div) without
   *  stranding the state. */
  const dragRef = useRef<{ x: number; t: number } | null>(null);
  /** Wheel-accumulator state for trackpad horizontal swipes.
   *  ``locked`` flips true on commit; we unlock based on the wheel
   *  signal itself (direction reversal or magnitude tapering to zero)
   *  rather than a wall-clock idle gap, so a gesture's natural end
   *  releases the lock and the next swipe can begin immediately. */
  const wheelRef = useRef<{ accum: number; locked: boolean }>({
    accum: 0,
    locked: false,
  });
  /** Set true on a successful swipe (drag or wheel) commit and reset
   *  shortly after, so the click event that fires post-mouseup is
   *  suppressed (so swiping across a clickable row doesn't also toggle
   *  selection). */
  const swipeCommittedRef = useRef(false);

  const markCommitted = () => {
    swipeCommittedRef.current = true;
    window.setTimeout(() => {
      swipeCommittedRef.current = false;
    }, 60);
  };

  const commitSwipe = useCallback((direction: 1 | -1) => {
    const i = indexRef.current;
    const m = maxRef.current;
    if (direction > 0 && i < m) onIndexChangeRef.current(i + 1);
    else if (direction < 0 && i > 0) onIndexChangeRef.current(i - 1);
  }, []);

  const onKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLDivElement>) => {
      if (e.key === "ArrowRight") commitSwipe(1);
      else if (e.key === "ArrowLeft") commitSwipe(-1);
    },
    [commitSwipe],
  );

  const onMouseDown = (e: React.MouseEvent<HTMLDivElement>) => {
    if (isTextInput(e.target)) return;
    if (e.button !== 0) return; // left-click only
    dragRef.current = { x: e.clientX, t: Date.now() };
    setDragDx(0);
  };

  /** Document-level move / up listeners installed once. They consult
   *  dragRef and only do work when a drag is in progress, so they have
   *  near-zero cost when idle. Installing here avoids losing the
   *  mouseup event if the user drags outside the swipe container. */
  useEffect(() => {
    const onDocMove = (e: MouseEvent) => {
      const s = dragRef.current;
      if (!s) return;
      setDragDx(e.clientX - s.x);
    };
    const onDocUp = (e: MouseEvent) => {
      const s = dragRef.current;
      if (!s) return;
      dragRef.current = null;
      const dx = e.clientX - s.x;
      const dt = Math.max(1, Date.now() - s.t);
      const velocity = Math.abs(dx) / dt;
      setDragDx(0);
      if (Math.abs(dx) < DRAG_THRESHOLD_PX) return;
      const shouldSwipe =
        Math.abs(dx) > SWIPE_DISTANCE_PX || velocity > SWIPE_VELOCITY;
      if (!shouldSwipe) return;
      markCommitted();
      commitSwipe(dx < 0 ? 1 : -1);
    };
    const cancel = () => {
      dragRef.current = null;
      setDragDx(0);
    };
    document.addEventListener("mousemove", onDocMove);
    document.addEventListener("mouseup", onDocUp);
    window.addEventListener("blur", cancel);
    return () => {
      document.removeEventListener("mousemove", onDocMove);
      document.removeEventListener("mouseup", onDocUp);
      window.removeEventListener("blur", cancel);
    };
  }, [commitSwipe]);

  // Touch
  const onTouchStart = (e: React.TouchEvent<HTMLDivElement>) => {
    const t = e.touches[0];
    if (!t || isTextInput(e.target)) return;
    dragRef.current = { x: t.clientX, t: Date.now() };
    setDragDx(0);
  };
  const onTouchMove = (e: React.TouchEvent<HTMLDivElement>) => {
    const t = e.touches[0];
    const s = dragRef.current;
    if (!t || !s) return;
    setDragDx(t.clientX - s.x);
  };
  const onTouchEnd = (e: React.TouchEvent<HTMLDivElement>) => {
    const t = e.changedTouches[0];
    const s = dragRef.current;
    if (!t || !s) return;
    dragRef.current = null;
    const dx = t.clientX - s.x;
    const dt = Math.max(1, Date.now() - s.t);
    const velocity = Math.abs(dx) / dt;
    setDragDx(0);
    if (Math.abs(dx) < DRAG_THRESHOLD_PX) return;
    const shouldSwipe =
      Math.abs(dx) > SWIPE_DISTANCE_PX || velocity > SWIPE_VELOCITY;
    if (!shouldSwipe) return;
    markCommitted();
    commitSwipe(dx < 0 ? 1 : -1);
  };

  /** Trackpad two-finger horizontal swipe. Browser fires wheel events
   *  with deltaX (Mac trackpads, Windows precision touchpads). One
   *  user gesture produces a long burst of wheel events — typically
   *  acceleration → peak → deceleration → inertia tail → near zero.
   *  We commit AT MOST one tab change per gesture by reading the
   *  signal shape:
   *
   *  - Vertical-dominant wheels are ignored (text scroll).
   *  - Direction reversal mid-stream = the user reversed the swipe,
   *    so reset and start fresh (also clears any commit-lock).
   *  - Once accumulated |deltaX| crosses WHEEL_COMMIT_PX, switch tabs
   *    and LOCK. Subsequent events are still swallowed
   *    (preventDefault) but don't trigger another commit.
   *  - Lock releases when |deltaX| drops below WHEEL_TAPER_PX —
   *    every real trackpad gesture's signal tapers to zero before
   *    the next one begins, so this is gesture-end without any
   *    wall-clock timer.
   */
  const onWheel = (e: React.WheelEvent<HTMLDivElement>) => {
    if (Math.abs(e.deltaX) < Math.abs(e.deltaY)) return;
    e.preventDefault();
    const state = wheelRef.current;
    const absDx = Math.abs(e.deltaX);

    // Tapering toward zero = current gesture is ending. Release the
    // lock so the next gesture can begin immediately on its first
    // significant event.
    if (absDx < WHEEL_TAPER_PX) {
      state.locked = false;
      state.accum = 0;
      return;
    }

    // Direction reversal mid-stream — new gesture; clear accumulator
    // and lock so the reversed swipe can commit on its own threshold.
    if (state.accum !== 0 && Math.sign(e.deltaX) !== Math.sign(state.accum)) {
      state.accum = 0;
      state.locked = false;
    }

    if (state.locked) return;

    state.accum += e.deltaX;
    if (Math.abs(state.accum) >= WHEEL_COMMIT_PX) {
      const dir: 1 | -1 = state.accum > 0 ? 1 : -1;
      state.locked = true;
      // Intentionally do NOT reset accum here — keeping its sign lets
      // the direction-reversal check above fire if the user reverses
      // before the gesture has had a chance to taper to zero.
      commitSwipe(dir);
    }
  };

  // Suppress click events that follow a committed swipe — prevents
  // swiping across a clickable row from also firing its onClick.
  const onClickCapture = (e: React.MouseEvent<HTMLDivElement>) => {
    if (swipeCommittedRef.current) {
      e.preventDefault();
      e.stopPropagation();
    }
  };

  const translatePct = -index * 100;
  const transform = `translateX(calc(${translatePct}% + ${dragDx}px))`;

  return (
    <div
      className="detail-tab-swipe"
      data-testid="detail-tab-swipe"
      tabIndex={0}
      onKeyDown={onKeyDown}
      onMouseDown={onMouseDown}
      onTouchStart={onTouchStart}
      onTouchMove={onTouchMove}
      onTouchEnd={onTouchEnd}
      onWheel={onWheel}
      onClickCapture={onClickCapture}
    >
      <div className="detail-tab-track" style={{ transform }}>
        {tabs.map((t) => (
          <div className="detail-tab-pane" key={t.id}>
            {t.content}
          </div>
        ))}
      </div>
      {/* Floating indicator — sits over whichever tab's footer is showing,
       *  centered horizontally near the bottom edge. Clickable for direct
       *  tab jumps. */}
      <div className="detail-tab-indicator" aria-hidden={false}>
        {tabs.map((t, i) => (
          <button
            type="button"
            key={t.id}
            className={`detail-tab-dot ${i === index ? "active" : ""}`}
            onClick={() => onIndexChange(i)}
            aria-label={`切换到 ${t.label}`}
          />
        ))}
      </div>
    </div>
  );
}
