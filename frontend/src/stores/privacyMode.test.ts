import { describe, it, expect, beforeEach } from "vitest";
import { usePrivacyModeStore } from "./privacyMode";

const KEY = "positions-privacy-mode";

describe("privacyMode store", () => {
  beforeEach(() => {
    localStorage.clear();
    // Reset store to the freshly-cleared localStorage state.
    usePrivacyModeStore.setState({ enabled: false });
  });

  it("defaults to disabled when localStorage is empty", () => {
    expect(usePrivacyModeStore.getState().enabled).toBe(false);
  });

  it("toggle() flips the flag AND persists to localStorage", () => {
    usePrivacyModeStore.getState().toggle();
    expect(usePrivacyModeStore.getState().enabled).toBe(true);
    expect(localStorage.getItem(KEY)).toBe("1");

    usePrivacyModeStore.getState().toggle();
    expect(usePrivacyModeStore.getState().enabled).toBe(false);
    expect(localStorage.getItem(KEY)).toBe("0");
  });

  it("setEnabled() sets the flag directly and persists", () => {
    usePrivacyModeStore.getState().setEnabled(true);
    expect(usePrivacyModeStore.getState().enabled).toBe(true);
    expect(localStorage.getItem(KEY)).toBe("1");
  });
});
