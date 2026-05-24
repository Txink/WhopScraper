import { useEffect } from "react";
import { useNoticesStore, type NoticeAnchor } from "../../stores/notices";
import "./NoticeStack.css";

interface Props {
  /** Which anchor's notices to render. Page-anchored stack lives in
   *  App.tsx and pins to viewport top-right; detail-anchored stack
   *  lives in DetailPane and pins to the pane's center. */
  anchor: NoticeAnchor;
}

/** Renders a stack of in-flight notices for one anchor. Notices
 *  auto-dismiss via per-item ttlMs; clicking the × dismisses early. */
export function NoticeStack({ anchor }: Props) {
  const items = useNoticesStore((s) => s.items.filter((n) => n.anchor === anchor));
  const dismiss = useNoticesStore((s) => s.dismiss);

  // Schedule auto-dismiss for each in-flight item. The effect's array
  // dependency on items ensures fresh timers track new arrivals.
  useEffect(() => {
    if (items.length === 0) return;
    const timers = items.map((n) => {
      const remaining = Math.max(0, n.ttlMs - (Date.now() - n.bornAt));
      return window.setTimeout(() => dismiss(n.id), remaining);
    });
    return () => timers.forEach((t) => window.clearTimeout(t));
  }, [items, dismiss]);

  if (items.length === 0) return null;
  return (
    <div className={`notice-stack notice-stack-${anchor}`}>
      {items.map((n) => (
        <div key={n.id} className={`notice notice-${n.kind}`} role="status">
          <span className="notice-icon" aria-hidden>
            {n.kind === "success" && "✓"}
            {n.kind === "error" && "!"}
            {n.kind === "warning" && "!"}
            {n.kind === "info" && "i"}
          </span>
          <span className="notice-message">{n.message}</span>
          <button
            type="button"
            className="notice-close"
            aria-label="关闭"
            onClick={() => dismiss(n.id)}
          >×</button>
        </div>
      ))}
    </div>
  );
}
