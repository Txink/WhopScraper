import { create } from "zustand";
import { listChatMessages, type ChatMessagesResponse } from "../api/chat";
import type { ChatMessageOut } from "../components/Chat/chatCards";

/** Cached slice for a single ``(page_id, week)`` pair. ``fetchedAt`` is a
 *  ms-epoch wall-clock — used by UI to render "last refreshed" badges
 *  and to decide whether to refetch on tab focus. */
interface ChatCache {
  messages: ChatMessageOut[];
  authors: { name: string; count: number }[];
  week: { start: string; end: string };
  fetchedAt: number;
}

interface ChatStore {
  /** Indexed by ``${pageId}|${week}`` — see {@link cacheKey}. */
  caches: Record<string, ChatCache>;
  /** Fetch the slice for ``(pageId, week)`` filtered by ``senders`` and
   *  store it under the matching cache key. The ``senders`` arg goes
   *  straight through to the server; if empty, the server returns all. */
  fetch: (pageId: string, week: string, senders: string[]) => Promise<void>;
  /** WS-triggered insert. Drops the update if no cache entry exists
   *  (we'd be staging a fragment for a slice the user never opened) or
   *  if the message id is already present (dedupe re-deliveries).
   *  Otherwise the message is appended and the slice is re-sorted by
   *  ``posted_at`` ascending — the canonical render order. */
  applyStoredMessage: (
    pageId: string,
    week: string,
    message: ChatMessageOut,
  ) => void;
}

const cacheKey = (pageId: string, week: string): string => `${pageId}|${week}`;

export const useChatStore = create<ChatStore>((set, get) => ({
  caches: {},

  fetch: async (pageId, week, senders) => {
    const r: ChatMessagesResponse = await listChatMessages(
      pageId,
      week,
      senders,
    );
    set((state) => ({
      caches: {
        ...state.caches,
        [cacheKey(pageId, week)]: {
          messages: r.messages,
          authors: r.authors,
          week: r.week,
          fetchedAt: Date.now(),
        },
      },
    }));
  },

  applyStoredMessage: (pageId, week, message) => {
    const key = cacheKey(pageId, week);
    const existing = get().caches[key];
    if (!existing) return;
    if (existing.messages.some((m) => m.id === message.id)) return;
    const next = [...existing.messages, message].sort((a, b) =>
      a.posted_at.localeCompare(b.posted_at),
    );
    set((state) => ({
      caches: { ...state.caches, [key]: { ...existing, messages: next } },
    }));
  },
}));
