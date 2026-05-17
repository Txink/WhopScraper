import { useEffect, useLayoutEffect, useRef, useState } from "react";

interface Props {
  open: boolean;
  /** The tab button (or any anchor element) the popover positions against. */
  anchorRef: React.RefObject<HTMLElement>;
  /** The chart-card element — popover stays inside its bounds. Provides the
   *  relative-positioning context as well, so this MUST be `position: relative`
   *  (or absolute) in CSS. */
  containerRef: React.RefObject<HTMLElement>;
  onClose(): void;
  children: React.ReactNode;
}

/**
 * Anchored dropdown used by DetailPane's popup-tabs (日内 / 分钟 / 多日).
 *
 * - Absolute-positioned inside `containerRef.current`.
 * - Top edge sits 6px below the anchor; left edge aligns to the anchor's left.
 * - If `left + popoverWidth > containerWidth - 4`, the popover shifts left so
 *   its right edge sticks at `containerWidth - 4`.
 * - Closes on Escape / click outside the popover (the anchor click is the
 *   parent's responsibility — clicking it again just toggles the parent's open
 *   state).
 *
 * The popover content is the caller's responsibility (typically a row of
 * `<button class="popover-pill">`).
 */
export function TabPopover({ open, anchorRef, containerRef, onClose, children }: Props) {
  const popRef = useRef<HTMLDivElement | null>(null);
  const [pos, setPos] = useState<{ left: number; top: number; caretLeft: number } | null>(null);

  // Position before paint so users never see the popover at (0,0) for a frame.
  useLayoutEffect(() => {
    if (!open) {
      setPos(null);
      return;
    }
    const anchor = anchorRef.current;
    const container = containerRef.current;
    const pop = popRef.current;
    if (!anchor || !container || !pop) return;
    const a = anchor.getBoundingClientRect();
    const c = container.getBoundingClientRect();
    const popW = pop.offsetWidth || 160;
    const idealLeft = a.left - c.left;
    const maxLeft = c.width - popW - 4;
    const left = Math.min(Math.max(0, idealLeft), Math.max(0, maxLeft));
    const top = a.bottom - c.top + 6;
    // Caret stays anchored over the trigger even when popover shifts left.
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
      if (anchor?.contains(target)) return; // anchor toggles via its own onClick
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

  return (
    <div
      ref={popRef}
      role="dialog"
      className="tab-popover"
      style={pos ? { left: pos.left, top: pos.top } : { visibility: "hidden" }}
    >
      {pos && (
        <span className="tab-popover-caret" style={{ left: pos.caretLeft }} aria-hidden />
      )}
      {children}
    </div>
  );
}
