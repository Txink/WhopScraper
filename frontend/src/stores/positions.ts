import { create } from "zustand";
import type { Position } from "../api/domain-types";

interface PositionsState {
  stocks: Position[];
  options: Position[];
  setAll(data: { stocks: Position[]; options: Position[] }): void;
  reset(): void;
}

export const usePositionsStore = create<PositionsState>((set) => ({
  stocks: [],
  options: [],
  setAll: (data) => set({ stocks: data.stocks, options: data.options }),
  reset: () => set({ stocks: [], options: [] }),
}));
