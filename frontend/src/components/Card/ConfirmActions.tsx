import { useState } from "react";
import type { SyntheticEvent } from "react";
import { api, HttpError } from "../../api/http";
import { useTasksStore } from "../../stores/tasks";

export interface ConfirmActionsProps {
  taskId: string;
  variant: "compact" | "expanded";
}

export function ConfirmActions({ taskId, variant }: ConfirmActionsProps) {
  const [busy, setBusy] = useState<"confirm" | "skip" | null>(null);
  const [error, setError] = useState<string | null>(null);

  const run = async (kind: "confirm" | "skip") => {
    setBusy(kind);
    setError(null);
    try {
      const updated = kind === "confirm"
        ? await api.confirmTask(taskId)
        : await api.skipTask(taskId);
      useTasksStore.getState().upsertTask(updated);
    } catch (e) {
      const msg = e instanceof HttpError
        ? (typeof e.body === "object" && e.body && "detail" in e.body
            ? String((e.body as { detail: unknown }).detail)
            : e.message)
        : (e instanceof Error ? e.message : String(e));
      setError(msg);
    } finally {
      setBusy(null);
    }
  };

  const stop = (e: SyntheticEvent) => e.stopPropagation();

  return (
    <span
      className={`confirm-actions ${variant}`}
      onClick={stop}
      onKeyDown={stop}
    >
      <button
        type="button"
        className="ca-btn ca-confirm"
        title="确认下单"
        aria-label="确认下单"
        disabled={busy !== null}
        onClick={() => run("confirm")}
      >
        {busy === "confirm" ? <span className="ca-spinner" /> : (
          <svg viewBox="0 0 16 16" fill="none" stroke="currentColor"
               strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round">
            <polyline points="3 8 7 12 13 4" />
          </svg>
        )}
      </button>
      <button
        type="button"
        className="ca-btn ca-cancel"
        title="取消"
        aria-label="取消"
        disabled={busy !== null}
        onClick={() => run("skip")}
      >
        {busy === "skip" ? <span className="ca-spinner" /> : (
          <svg viewBox="0 0 16 16" fill="none" stroke="currentColor"
               strokeWidth="2.4" strokeLinecap="round">
            <line x1="4" y1="4" x2="12" y2="12" />
            <line x1="12" y1="4" x2="4" y2="12" />
          </svg>
        )}
      </button>
      {error && <span className="ca-err" title={error}>!</span>}
    </span>
  );
}
