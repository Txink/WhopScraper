import { create } from "zustand";

/** Persisted UI flag: when true, the positions panel hides quantity,
 *  P/L and total-value figures so the screen is screenshot-safe in
 *  public settings. Scope is dashboard-wide (not per-account or per-
 *  page) and the value survives reloads via localStorage. */
const STORAGE_KEY = "positions-privacy-mode";

function loadInitial(): boolean {
  try {
    return localStorage.getItem(STORAGE_KEY) === "1";
  } catch {
    return false;
  }
}

function persist(v: boolean): void {
  try {
    localStorage.setItem(STORAGE_KEY, v ? "1" : "0");
  } catch {
    /* localStorage disabled — fall back to in-memory only */
  }
}

interface PrivacyModeStore {
  enabled: boolean;
  toggle: () => void;
  setEnabled: (v: boolean) => void;
}

export const usePrivacyModeStore = create<PrivacyModeStore>((set, get) => ({
  enabled: loadInitial(),
  toggle: () => {
    const next = !get().enabled;
    persist(next);
    set({ enabled: next });
  },
  setEnabled: (v) => {
    persist(v);
    set({ enabled: v });
  },
}));
