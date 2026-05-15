import { create } from "zustand";
import type { Execution } from "../api/domain-types";

/** Broker-side fills for the active account, today's session only.
 *
 * Source of truth for Day P/L on the position cards. Distinct from the
 * trades store (DB-backed, used for 做T pair binding) because it includes
 * manual fills placed via the LongBridge app / web that never enter our
 * own trader pipeline. Wiped + repopulated on account switch.
 */
interface ExecutionsState {
  /** All of today's fills, flat. Filtered by symbol or ticker by the
   *  consumer (PositionCard / OptionCard) on read. */
  executions: Execution[];
  setExecutions(list: Execution[]): void;
  /** Upsert one fill by ``order_id``. Used by the WS ``execution.update``
   *  push handler to update Day P/L without re-fetching the whole list.
   *  Partial fills land here as cumulative qty/price updates — the SDK's
   *  PushOrderChanged event carries the running totals on the order. */
  upsertExecution(exec: Execution): void;
  reset(): void;
}

export const useExecutionsStore = create<ExecutionsState>((set) => ({
  executions: [],
  setExecutions: (list) => set({ executions: list }),
  upsertExecution: (exec) =>
    set((state) => {
      const idx = state.executions.findIndex((e) => e.order_id === exec.order_id);
      if (idx < 0) return { executions: [...state.executions, exec] };
      const next = state.executions.slice();
      next[idx] = exec;
      return { executions: next };
    }),
  reset: () => set({ executions: [] }),
}));
