import { create } from "zustand";
import type { Trade } from "../api/domain-types";

/** Per-ticker flat list of FILLED / PARTIAL trades.
 *
 * The detail pane paginates broker fills via "加载更多". Each page returns
 * a slice of newest-first executions; ``appendTrades`` merges by ``id``
 * (broker order_id) so prior pages stay in the store. This is what makes
 * cross-page做T binding work — a trade selected on page 1 is still
 * present when the user fetches page 2, so the bind builder's stats sum
 * the union, not just the current page.
 *
 * ``setTrades`` replaces the list (used on detail-pane mount for page 0).
 */
interface TradesState {
  byTicker: Record<string, Trade[]>;
  setTrades(ticker: string, trades: Trade[]): void;
  appendTrades(ticker: string, trades: Trade[]): void;
  reset(): void;
}

function mergeById(prev: Trade[], next: Trade[]): Trade[] {
  // Upsert by id: incoming rows overwrite same-id entries, new rows append.
  // Keeps the original ordering of ``prev`` for entries that survive and
  // appends genuinely-new rows in their incoming order. The trade list
  // re-sorts by ts before rendering so storage order doesn't matter.
  const byId = new Map(prev.map((t) => [t.id, t]));
  for (const t of next) byId.set(t.id, t);
  return [...byId.values()];
}

export const useTradesStore = create<TradesState>((set) => ({
  byTicker: {},
  setTrades: (ticker, trades) =>
    set((state) => ({ byTicker: { ...state.byTicker, [ticker]: trades } })),
  appendTrades: (ticker, trades) =>
    set((state) => ({
      byTicker: {
        ...state.byTicker,
        [ticker]: mergeById(state.byTicker[ticker] ?? [], trades),
      },
    })),
  reset: () => set({ byTicker: {} }),
}));
