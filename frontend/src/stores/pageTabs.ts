import { create } from "zustand";
import type { WhopPage } from "../api/domain-types";
import type { WsEvent } from "../api/ws";

export type ExpandMode = "smart" | "all-open" | "all-closed";
export type ActiveTabId = string | "orphan" | null;

const LS_KEY = "DASHBOARD_LAST_TAB";

interface PageTabsState {
  pages: WhopPage[];
  activeTabId: ActiveTabId;
  expandModeByTab: Record<string, ExpandMode>;
  orphanCount: number;

  setPages(pages: WhopPage[]): void;
  setActiveTab(id: ActiveTabId): void;
  setExpandMode(tabId: string, mode: ExpandMode): void;
  setOrphanCount(n: number): void;
  applyPageChanged(evt: WsEvent): void;
  reset(): void;
}

export const usePageTabsStore = create<PageTabsState>((set, get) => ({
  pages: [],
  activeTabId: null,
  expandModeByTab: {},
  orphanCount: 0,

  setPages(pages) {
    const stored = localStorage.getItem(LS_KEY);
    let next: ActiveTabId = get().activeTabId;
    // Re-pick activeTabId if it's no longer in the page list (or never set).
    if (next === null || (next !== "orphan" && !pages.some(p => p.id === next))) {
      if (stored && pages.some(p => p.id === stored)) {
        next = stored;
      } else if (pages.length > 0) {
        next = pages[0].id;
      } else {
        next = null;
      }
    }
    set({ pages, activeTabId: next });
  },

  setActiveTab(id) {
    if (id !== null && id !== "orphan") localStorage.setItem(LS_KEY, id);
    set({ activeTabId: id });
  },

  setExpandMode(tabId, mode) {
    set(state => ({
      expandModeByTab: { ...state.expandModeByTab, [tabId]: mode },
    }));
  },

  setOrphanCount(n) {
    set({ orphanCount: n });
  },

  applyPageChanged(evt) {
    const p = evt.payload as { action: string; page: WhopPage };
    const action = p.action;
    const page = p.page;
    set(state => {
      let pages = state.pages;
      if (action === "added") {
        if (!pages.some(x => x.id === page.id)) pages = [...pages, page];
      } else if (action === "removed") {
        pages = pages.filter(x => x.id !== page.id);
      } else {
        // restarted | settings_updated → replace in place
        pages = pages.map(x => x.id === page.id ? page : x);
      }
      let activeTabId = state.activeTabId;
      if (activeTabId !== "orphan" && activeTabId !== null && !pages.some(x => x.id === activeTabId)) {
        activeTabId = pages[0]?.id ?? null;
      }
      return { pages, activeTabId };
    });
  },

  reset() {
    set({ pages: [], activeTabId: null, expandModeByTab: {}, orphanCount: 0 });
  },
}));
