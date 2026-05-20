import { create } from "zustand";
import type { WhopPage } from "../api/domain-types";
import type { WsEvent } from "../api/ws";

export type ActiveTabId = string | "orphan" | null;

const LS_KEY = "DASHBOARD_LAST_TAB";

interface PageTabsState {
  pages: WhopPage[];
  activeTabId: ActiveTabId;
  /** Single-accordion expand state per tab. At most one card is expanded
   *  per tab; ``null`` (or absent key) = nothing expanded. Click an
   *  unexpanded card → it becomes expanded and the prior one collapses;
   *  click the expanded card → it collapses (key set to null). */
  expandedTaskIdByTab: Record<string, string | null>;
  orphanCount: number;
  pagesLoaded: boolean;

  setPages(pages: WhopPage[]): void;
  setActiveTab(id: ActiveTabId): void;
  /** Toggle the card's expanded state. Pass the same id twice to collapse;
   *  pass a different id to switch the accordion's open slot. */
  toggleExpandedTask(tabId: string, taskId: string): void;
  setOrphanCount(n: number): void;
  markPagesLoaded(): void;
  applyPageChanged(evt: WsEvent): void;
  removePageIfPresent(pageId: string): void;
  reset(): void;
}

export const usePageTabsStore = create<PageTabsState>((set, get) => ({
  pages: [],
  activeTabId: null,
  expandedTaskIdByTab: {},
  orphanCount: 0,
  pagesLoaded: false,

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
    set({ pages, activeTabId: next, pagesLoaded: true });
  },

  setActiveTab(id) {
    if (id !== null && id !== "orphan") localStorage.setItem(LS_KEY, id);
    set({ activeTabId: id });
  },

  toggleExpandedTask(tabId, taskId) {
    set(state => {
      const current = state.expandedTaskIdByTab[tabId] ?? null;
      const next = current === taskId ? null : taskId;
      return {
        expandedTaskIdByTab: { ...state.expandedTaskIdByTab, [tabId]: next },
      };
    });
  },

  setOrphanCount(n) {
    set({ orphanCount: n });
  },

  markPagesLoaded() {
    set({ pagesLoaded: true });
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

  removePageIfPresent(pageId) {
    set(state => {
      if (!state.pages.some(p => p.id === pageId)) return state;
      return { pages: state.pages.filter(p => p.id !== pageId) };
    });
  },

  reset() {
    set({ pages: [], activeTabId: null, expandedTaskIdByTab: {}, orphanCount: 0, pagesLoaded: false });
  },
}));
