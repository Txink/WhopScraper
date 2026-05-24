import { useEffect, useRef, useState } from "react";
import { useAlertNotificationsStore } from "../../stores/alertNotifications";
import type { AlertEventOut } from "../../stores/alertNotifications";
import { alertsApi } from "../../api/alerts";
import "./AlertNotifications.css";

export function AlertBell() {
  const unread = useAlertNotificationsStore((s) => s.unreadCount);
  const history = useAlertNotificationsStore((s) => s.history);
  const clearUnread = useAlertNotificationsStore((s) => s.clearUnread);
  const setHistory = (events: AlertEventOut[]) =>
    useAlertNotificationsStore.setState({ history: events });
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    alertsApi.events({ limit: 50 }).then((r) => setHistory(r.events))
      .catch(() => {});
  }, [open]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [open]);

  const onOpen = () => {
    const willOpen = !open;
    setOpen(willOpen);
    if (willOpen) clearUnread();
  };

  return (
    <div ref={containerRef} style={{ position: "relative" }}>
      <button
        type="button"
        aria-label="告警"
        className={`bell ${unread > 0 ? "has-unread" : ""}`}
        onClick={onOpen}
      >
        <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9" />
          <path d="M10.3 21a1.94 1.94 0 0 0 3.4 0" />
        </svg>
        {unread > 0 && (
          <span data-testid="bell-badge" className="bell-badge">
            {unread > 99 ? "99+" : unread}
          </span>
        )}
      </button>
      {open && (
        <div className="bell-popover">
          <div className="bell-popover-head">
            <span>告警历史</span>
          </div>
          <div className="bell-popover-body">
            {history.length === 0 && (
              <div style={{ padding: 12, color: "var(--fg-3)" }}>无触发记录</div>
            )}
            {history.map((evt) => (
              <div key={evt.id} className="bell-event">
                <span className="bell-event-icon oneshot" />
                <div className="bell-event-main">
                  <span className="bell-event-cond">{evt.message}</span>
                  {evt.snapshot_price != null && (
                    <span className="bell-event-snap">
                      触发价 ${evt.snapshot_price.toFixed(2)}
                    </span>
                  )}
                </div>
                <span className="bell-event-time">
                  {new Date(evt.triggered_at).toLocaleTimeString("zh-CN", {
                    hour: "2-digit",
                    minute: "2-digit",
                    second: "2-digit",
                  })}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
