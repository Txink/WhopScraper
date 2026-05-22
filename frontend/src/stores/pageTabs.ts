import { create } from "zustand";
import type { WhopPage } from "../api/domain-types";
import type { WsEvent } from "../api/ws";

interface PageTabsState {
  pages: WhopPage[];
  /** Single-accordion expand state keyed by page id. At most one card is
   *  expanded per page; ``null`` (or absent key) = nothing expanded. */
  expandedTaskIdByTab: Record<string, string | null>;
  pagesLoaded: boolean;

  setPages(pages: WhopPage[]): void;
  toggleExpandedTask(tabId: string, taskId: string): void;
  markPagesLoaded(): void;
  applyPageChanged(evt: WsEvent): void;
  removePageIfPresent(pageId: string): void;
  reset(): void;
}

export const usePageTabsStore = create<PageTabsState>((set) => ({
  pages: [],
  expandedTaskIdByTab: {},
  pagesLoaded: false,

  setPages(pages) {
    set({ pages, pagesLoaded: true });
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
      return { pages };
    });
  },

  removePageIfPresent(pageId) {
    set(state => {
      if (!state.pages.some(p => p.id === pageId)) return state;
      return { pages: state.pages.filter(p => p.id !== pageId) };
    });
  },

  reset() {
    set({ pages: [], expandedTaskIdByTab: {}, pagesLoaded: false });
  },
}));
