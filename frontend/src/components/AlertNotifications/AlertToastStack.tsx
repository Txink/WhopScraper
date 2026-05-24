import { useEffect } from "react";
import { useAlertNotificationsStore } from "../../stores/alertNotifications";
import "./AlertNotifications.css";

const TOAST_TTL_MS = 5000;

export function AlertToastStack() {
  const toasts = useAlertNotificationsStore((s) => s.activeToasts);
  const dismiss = useAlertNotificationsStore((s) => s.dismissToast);

  useEffect(() => {
    const timers = toasts.map((t) =>
      setTimeout(
        () => dismiss(t.event.id),
        Math.max(0, TOAST_TTL_MS - (Date.now() - t.bornAt)),
      ),
    );
    return () => timers.forEach((id) => clearTimeout(id));
  }, [toasts, dismiss]);

  if (toasts.length === 0) return null;

  return (
    <div className="toast-stack">
      {toasts.map((t) => (
        <div
          key={t.event.id}
          className={`toast ${t.alert.repeat_mode === "recurring" ? "recurring" : ""}`}
        >
          <div className="toast-head">
            <span>
              <span className="toast-ticker">{t.event.ticker}</span>
            </span>
            <button
              className="toast-close"
              aria-label="关闭"
              onClick={() => dismiss(t.event.id)}
            >
              ×
            </button>
          </div>
          <div className="toast-snap">
            <span>{t.event.message}</span>
          </div>
        </div>
      ))}
    </div>
  );
}
