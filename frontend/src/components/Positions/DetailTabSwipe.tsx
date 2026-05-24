import {
  useCallback, useEffect, useRef, useState, type ReactNode,
} from "react";
import { DetailTabFooter } from "./DetailTabFooter";
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
  onOpenSettings?: (i: number) => void;
}

const DRAG_THRESHOLD_PX = 8;
const SWIPE_DISTANCE_PX = 50;
const SWIPE_VELOCITY = 0.4;  // px/ms

function isFormTarget(el: EventTarget | null): boolean {
  if (!(el instanceof HTMLElement)) return false;
  const tag = el.tagName;
  return (
    tag === "INPUT" || tag === "SELECT" || tag === "TEXTAREA" || tag === "BUTTON" ||
    el.isContentEditable
  );
}

export function DetailTabSwipe({ tabs, index, onIndexChange, onOpenSettings }: Props) {
  const max = tabs.length - 1;
  const [dragDx, setDragDx] = useState(0);
  const startRef = useRef<{ x: number; t: number; pointerId: number | null } | null>(null);

  const onKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLDivElement>) => {
      if (e.key === "ArrowRight" && index < max) {
        onIndexChange(index + 1);
      } else if (e.key === "ArrowLeft" && index > 0) {
        onIndexChange(index - 1);
      }
    },
    [index, max, onIndexChange],
  );

  const startDrag = (clientX: number, target: EventTarget | null) => {
    if (isFormTarget(target)) return;
    startRef.current = { x: clientX, t: Date.now(), pointerId: null };
    setDragDx(0);
  };
  const moveDrag = (clientX: number) => {
    const s = startRef.current;
    if (!s) return;
    setDragDx(clientX - s.x);
  };
  const endDrag = (clientX: number) => {
    const s = startRef.current;
    startRef.current = null;
    if (!s) return;
    const dx = clientX - s.x;
    const dt = Math.max(1, Date.now() - s.t);
    const velocity = Math.abs(dx) / dt;
    setDragDx(0);
    if (Math.abs(dx) < DRAG_THRESHOLD_PX) return;
    const shouldSwipe = Math.abs(dx) > SWIPE_DISTANCE_PX || velocity > SWIPE_VELOCITY;
    if (!shouldSwipe) return;
    if (dx < 0 && index < max) onIndexChange(index + 1);
    else if (dx > 0 && index > 0) onIndexChange(index - 1);
  };

  // Mouse
  const onMouseDown = (e: React.MouseEvent<HTMLDivElement>) => startDrag(e.clientX, e.target);
  const onMouseMove = (e: React.MouseEvent<HTMLDivElement>) => moveDrag(e.clientX);
  const onMouseUp = (e: React.MouseEvent<HTMLDivElement>) => endDrag(e.clientX);

  // Touch
  const onTouchStart = (e: React.TouchEvent<HTMLDivElement>) => {
    const t = e.touches[0];
    if (!t) return;
    startDrag(t.clientX, e.target);
  };
  const onTouchMove = (e: React.TouchEvent<HTMLDivElement>) => {
    const t = e.touches[0];
    if (!t) return;
    moveDrag(t.clientX);
  };
  const onTouchEnd = (e: React.TouchEvent<HTMLDivElement>) => {
    const t = e.changedTouches[0];
    if (!t) return;
    endDrag(t.clientX);
  };

  // Cancel drag if pointer leaves window mid-drag
  useEffect(() => {
    const cancel = () => {
      startRef.current = null;
      setDragDx(0);
    };
    window.addEventListener("mouseleave", cancel);
    window.addEventListener("blur", cancel);
    return () => {
      window.removeEventListener("mouseleave", cancel);
      window.removeEventListener("blur", cancel);
    };
  }, []);

  const translatePct = -index * 100;
  const transform = `translateX(calc(${translatePct}% + ${dragDx}px))`;

  return (
    <div
      className="detail-tab-swipe"
      data-testid="detail-tab-swipe"
      tabIndex={0}
      onKeyDown={onKeyDown}
      onMouseDown={onMouseDown}
      onMouseMove={onMouseMove}
      onMouseUp={onMouseUp}
      onTouchStart={onTouchStart}
      onTouchMove={onTouchMove}
      onTouchEnd={onTouchEnd}
    >
      <div className="detail-tab-track" style={{ transform }}>
        {tabs.map((t) => (
          <div className="detail-tab-pane" key={t.id}>
            {t.content}
          </div>
        ))}
      </div>
      <DetailTabFooter
        tabs={tabs}
        index={index}
        onIndexChange={onIndexChange}
        onOpenSettings={onOpenSettings}
      />
    </div>
  );
}
