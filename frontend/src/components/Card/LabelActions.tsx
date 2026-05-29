import { useState } from "react";
import type { SyntheticEvent } from "react";
import type { Instruction, CorrectedInstruction } from "../../api/domain-types";
import { api, HttpError } from "../../api/http";
import { useTasksStore } from "../../stores/tasks";
import { LabelCorrectionDialog } from "./LabelCorrectionDialog";
import "./LabelActions.css";

interface Props {
  taskId: string;
  instruction: Instruction | null;
  variant: "stock" | "option";
}

export function LabelActions({ taskId, instruction, variant }: Props) {
  const label = useTasksStore((s) => s.labelsByTask[taskId]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [dialogOpen, setDialogOpen] = useState(false);

  const verdict = label?.verdict;

  const errMsg = (e: unknown) =>
    e instanceof HttpError
      ? (typeof e.body === "object" && e.body && "detail" in e.body
          ? String((e.body as { detail: unknown }).detail)
          : e.message)
      : (e instanceof Error ? e.message : String(e));

  const toggleCorrect = async () => {
    setBusy(true);
    setError(null);
    try {
      if (verdict === "correct") {
        const updated = await api.clearTaskLabel(taskId);
        useTasksStore.getState().setLabel(taskId, updated.label ?? null);
      } else {
        const updated = await api.setTaskLabel(taskId, { verdict: "correct" });
        useTasksStore.getState().setLabel(taskId, updated.label ?? null);
      }
    } catch (e) {
      setError(errMsg(e));
    } finally {
      setBusy(false);
    }
  };

  const saveCorrection = async (payload: CorrectedInstruction) => {
    setBusy(true);
    setError(null);
    try {
      const updated = await api.setTaskLabel(taskId, {
        verdict: "corrected",
        corrected_payload: payload,
      });
      useTasksStore.getState().setLabel(taskId, updated.label ?? null);
      setDialogOpen(false);
    } catch (e) {
      setError(errMsg(e));
    } finally {
      setBusy(false);
    }
  };

  const stop = (e: SyntheticEvent) => e.stopPropagation();

  return (
    <div className="label-actions" onClick={stop} onKeyDown={stop}>
      {error && <span className="label-err" title={error}>!</span>}
      <button
        type="button"
        className={`label-action-btn${verdict === "correct" ? " active-correct" : ""}`}
        disabled={busy}
        onClick={toggleCorrect}
      >
        正确
      </button>
      <button
        type="button"
        className={`label-action-btn${verdict === "corrected" ? " active-corrected" : ""}`}
        disabled={busy}
        onClick={() => setDialogOpen(true)}
      >
        校正
      </button>
      {dialogOpen && (
        <LabelCorrectionDialog
          variant={variant}
          instruction={instruction}
          existing={label?.corrected_payload ?? null}
          onSubmit={saveCorrection}
          onClose={() => setDialogOpen(false)}
        />
      )}
    </div>
  );
}
