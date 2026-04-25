import { create } from "zustand";

export type View = "dashboard" | "whop" | "database";

interface ViewState {
  view: View;
  setView(v: View): void;
}

export const useViewStore = create<ViewState>((set) => ({
  view: "dashboard",
  setView: (v) => set({ view: v }),
}));
