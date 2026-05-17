import { create } from "zustand";

/**
 * Stock direction color convention:
 *   "us"  – Western / US: green = up, red = down (default)
 *   "cn"  – Chinese / Asian: red = up, green = down
 *
 * Stored in localStorage so the choice survives reloads.
 */
export type ColorMode = "us" | "cn";

const LS_KEY = "prefs.colorMode";

function loadFromStorage(): ColorMode {
  try {
    const v = localStorage.getItem(LS_KEY);
    if (v === "us" || v === "cn") return v;
  } catch {
    /* localStorage unavailable in tests / private mode */
  }
  return "us";
}

function persist(mode: ColorMode): void {
  try { localStorage.setItem(LS_KEY, mode); } catch { /* noop */ }
}

/** Apply the active color mode to the document root by setting CSS
 *  variables. Components reference these via var(--up-color) /
 *  var(--down-color) so changes are global and instant.
 *
 *  Hex values match the brand --ok / --err tokens to preserve the
 *  existing visual weight; we just swap which one means "up". */
function applyToRoot(mode: ColorMode): void {
  if (typeof document === "undefined") return;
  const root = document.documentElement;
  if (mode === "cn") {
    root.style.setProperty("--up-color", "#ef5b5b");
    root.style.setProperty("--up-soft",  "rgba(239, 91, 91, 0.14)");
    root.style.setProperty("--down-color", "#3dd68c");
    root.style.setProperty("--down-soft",  "rgba(61, 214, 140, 0.14)");
    root.style.setProperty("--candle-up-color", "#952a2a");
    root.style.setProperty("--candle-down-color", "#147a48");
  } else {
    root.style.setProperty("--up-color", "#3dd68c");
    root.style.setProperty("--up-soft",  "rgba(61, 214, 140, 0.14)");
    root.style.setProperty("--down-color", "#ef5b5b");
    root.style.setProperty("--down-soft",  "rgba(239, 91, 91, 0.14)");
    root.style.setProperty("--candle-up-color", "#147a48");
    root.style.setProperty("--candle-down-color", "#952a2a");
  }
}

interface PrefsState {
  colorMode: ColorMode;
  setColorMode(m: ColorMode): void;
  toggleColorMode(): void;
}

export const usePrefsStore = create<PrefsState>((set, get) => {
  const initial = loadFromStorage();
  applyToRoot(initial);
  return {
    colorMode: initial,
    setColorMode: (m) => {
      persist(m);
      applyToRoot(m);
      set({ colorMode: m });
    },
    toggleColorMode: () => {
      const next: ColorMode = get().colorMode === "us" ? "cn" : "us";
      persist(next);
      applyToRoot(next);
      set({ colorMode: next });
    },
  };
});
