import { create } from "zustand";
import type { WhopPage } from "../api/domain-types";

interface ChildPagesState {
  /** parent chat id → list of its sub-monitor pages. Pages without a parent
   *  (top-level) never appear here — they live in usePageTabsStore. */
  byParent: Record<string, WhopPage[]>;

  /** Bulk-replace the list for ``parentId``. Used by ChatBoardPanel after
   *  a fresh GET /api/whop/pages?parent_chat_id=<id> fetch. */
  setByParent(parentId: string, pages: WhopPage[]): void;

  /** Insert-or-update a single page. Handles four cases:
   *  - new page with parent → append to its parent's list
   *  - existing page, same parent → replace in place
   *  - existing page, different parent → drop from old parent + append to new
   *  - existing page, parent now null → drop from store entirely (caller is
   *    responsible for inserting it into pageTabsStore separately).
   *  Called by the WS whop.page_changed handler. */
  upsert(page: WhopPage): void;

  /** Drop a page by id, regardless of which parent it's under. */
  remove(pageId: string): void;
}

export const useChildPagesStore = create<ChildPagesState>((set) => ({
  byParent: {},

  setByParent(parentId, pages) {
    set((s) => ({ byParent: { ...s.byParent, [parentId]: pages } }));
  },

  upsert(page) {
    set((s) => {
      // Drop the page from EVERY parent bucket first — covers both the
      // "moved to a different parent" and "promoted to top-level" cases
      // with a single pass.
      const cleaned: Record<string, WhopPage[]> = {};
      for (const [pid, list] of Object.entries(s.byParent)) {
        const filtered = list.filter((p) => p.id !== page.id);
        if (filtered.length > 0) cleaned[pid] = filtered;
      }
      if (page.parent_chat_id == null) return { byParent: cleaned };
      const existing = cleaned[page.parent_chat_id] ?? [];
      return {
        byParent: { ...cleaned, [page.parent_chat_id]: [...existing, page] },
      };
    });
  },

  remove(pageId) {
    set((s) => {
      const next: Record<string, WhopPage[]> = {};
      for (const [pid, list] of Object.entries(s.byParent)) {
        const filtered = list.filter((p) => p.id !== pageId);
        if (filtered.length > 0) next[pid] = filtered;
      }
      return { byParent: next };
    });
  },
}));
