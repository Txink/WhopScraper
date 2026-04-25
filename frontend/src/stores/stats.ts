import { create } from "zustand";
import type { StatsToday } from "../api/domain-types";

interface StatsState {
  stats: StatsToday | null;
  setStats(stats: StatsToday): void;
  reset(): void;
}

export const useStatsStore = create<StatsState>((set) => ({
  stats: null,
  setStats: (stats) => set({ stats }),
  reset: () => set({ stats: null }),
}));
