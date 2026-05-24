import { create } from "zustand";

export type NoticeKind = "success" | "error" | "warning" | "info";

/** Where the notice should appear:
 *  - "page": top-right of the viewport (global app-level toasts).
 *  - "detail": centered over the .detail-pane (scoped to the stock
 *    detail working area; used for trading/alert action feedback).
 */
export type NoticeAnchor = "page" | "detail";

export interface Notice {
  id: number;
  kind: NoticeKind;
  message: string;
  anchor: NoticeAnchor;
  bornAt: number;
  /** Auto-dismiss timeout in ms. Default depends on kind. */
  ttlMs: number;
}

interface NoticesState {
  items: Notice[];
  /** Push a notice. Returns the id so callers can dismiss programmatically. */
  push(notice: Omit<Notice, "id" | "bornAt" | "ttlMs"> & { ttlMs?: number }): number;
  dismiss(id: number): void;
  clear(): void;
}

let _nextId = 1;
const TTL_DEFAULT: Record<NoticeKind, number> = {
  success: 3000,
  info: 3500,
  warning: 5000,
  error: 6500,
};

export const useNoticesStore = create<NoticesState>((set) => ({
  items: [],
  push: (n) => {
    const id = _nextId++;
    set((s) => ({
      items: [...s.items, {
        id,
        kind: n.kind,
        message: n.message,
        anchor: n.anchor,
        bornAt: Date.now(),
        ttlMs: n.ttlMs ?? TTL_DEFAULT[n.kind],
      }],
    }));
    return id;
  },
  dismiss: (id) => set((s) => ({ items: s.items.filter((n) => n.id !== id) })),
  clear: () => set({ items: [] }),
}));

/** Shortcut helpers — keep call sites terse. */
export const notice = {
  success(message: string, anchor: NoticeAnchor = "page"): number {
    return useNoticesStore.getState().push({ kind: "success", message, anchor });
  },
  error(message: string, anchor: NoticeAnchor = "page"): number {
    return useNoticesStore.getState().push({ kind: "error", message, anchor });
  },
  warning(message: string, anchor: NoticeAnchor = "page"): number {
    return useNoticesStore.getState().push({ kind: "warning", message, anchor });
  },
  info(message: string, anchor: NoticeAnchor = "page"): number {
    return useNoticesStore.getState().push({ kind: "info", message, anchor });
  },
};
