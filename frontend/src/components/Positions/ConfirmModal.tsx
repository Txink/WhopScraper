import { useEffect, useRef } from "react";

interface Props {
  title: string;
  /** Short body text shown under the title. Plain string — keep it
   *  one-or-two sentences. */
  description: string;
  /** Label on the primary confirm button. Defaults to "确认". */
  confirmLabel?: string;
  /** Render the confirm button in danger styling (red) for destructive
   *  actions. Cancel button always stays neutral. */
  danger?: boolean;
  /** Where to anchor the modal card inside the panel. ``center``
   *  (default) vertically centers; ``bottom`` pins it near the bottom
   *  edge so it appears close to the triggering control (e.g. just
   *  above a sticky form row) rather than floating in the middle. */
  placement?: "center" | "bottom";
  onConfirm(): void | Promise<void>;
  onCancel(): void;
}

/** Panel-scoped confirm dialog. Backdrop is absolutely-positioned, so
 *  the parent (``.detail-pane``) must carry ``position: relative`` for
 *  the overlay to anchor inside it rather than the viewport. Used for
 *  destructive actions on the trade list (clear做T bindings, refetch,
 *  clear executions) — see DetailPane's trade-menu wiring. */
export function ConfirmModal({
  title,
  description,
  confirmLabel = "确认",
  danger = false,
  placement = "center",
  onConfirm,
  onCancel,
}: Props) {
  const confirmRef = useRef<HTMLButtonElement | null>(null);

  // Focus the confirm button on mount so a user expecting Enter-to-
  // submit can press it without reaching for the mouse. Esc closes.
  useEffect(() => {
    confirmRef.current?.focus();
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onCancel();
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onCancel]);

  return (
    <div
      className={`confirm-modal-backdrop ${placement === "bottom" ? "placement-bottom" : ""}`}
      role="dialog"
      aria-modal="true"
      aria-labelledby="confirm-modal-title"
      onClick={(e) => {
        // Click on the backdrop (NOT on the card) dismisses, matching
        // the project's modal-backdrop convention elsewhere.
        if (e.target === e.currentTarget) onCancel();
      }}
    >
      <div className="confirm-modal-card">
        <h4 id="confirm-modal-title" className="confirm-modal-title">{title}</h4>
        <p className="confirm-modal-desc">{description}</p>
        <div className="confirm-modal-actions">
          <button type="button" className="btn ghost" onClick={onCancel}>
            取消
          </button>
          <button
            ref={confirmRef}
            type="button"
            className={`btn ${danger ? "danger" : "primary"}`}
            onClick={() => void onConfirm()}
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
