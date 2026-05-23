import { create } from "zustand";
import {
  listChatMessagesForDay,
  listChatMessageCounts,
  type ChatMessagesResponse,
  type ChatMessageCountsResponse,
} from "../api/chat";
import type { ChatMessageOut } from "../components/Chat/chatCards";

/** Cached slice for a single ``(page_id, day)`` pair (day = Beijing YYYY-MM-DD). */
interface ChatDayCache {
  messages: ChatMessageOut[];
  authors: { name: string; count: number }[];
  day: { start: string; end: string };
  fetchedAt: number;
}

/** Cached per-day message counts for one Beijing calendar month. */
interface ChatMonthCounts {
  month: string;
  counts: Record<string, number>;  // dayKey -> count, omits zero-days
  fetchedAt: number;
}

interface ChatStore {
  /** Keyed by ``${pageId}|${day}``. */
  caches: Record<string, ChatDayCache>;
  /** Keyed by ``${pageId}|${month}`` (month = YYYY-MM Beijing). */
  counts: Record<string, ChatMonthCounts>;

  /** Fetch one Beijing-day's messages and cache by ``(pageId, day)``.
   *
   *  Concurrent calls for the same ``(pageId, day)`` share a single
   *  in-flight promise — the first caller's ``senders`` filter is the
   *  one actually sent. Callers passing non-empty ``senders`` should not
   *  race against callers passing ``[]``; today's only consumer
   *  (ChatBoardPanel) always passes ``[]``. */
  fetchDay: (pageId: string, day: string, senders: string[]) => Promise<void>;
  fetchCounts: (pageId: string, month: string) => Promise<void>;

  /** WS-triggered insert. Drops the update if no cache entry exists for
   *  ``(pageId, day)`` (we'd be staging a fragment for a slice the user
   *  never opened) or if the message id is already present (dedupe). */
  applyStoredMessage: (
    pageId: string,
    day: string,
    message: ChatMessageOut,
  ) => void;
}

const dayKey = (pageId: string, day: string): string => `${pageId}|${day}`;
const monthKey = (pageId: string, month: string): string => `${pageId}|${month}`;

// In-flight request dedupe — concurrent fetchDay/fetchCounts for the same
// key share a single promise so the page-mount + selectedDate-effect race
// doesn't double-fetch today's slice.
const inflightDays = new Map<string, Promise<void>>();
const inflightCounts = new Map<string, Promise<void>>();

export const useChatStore = create<ChatStore>((set, get) => ({
  caches: {},
  counts: {},

  fetchDay: async (pageId, day, senders) => {
    const k = dayKey(pageId, day);
    const existing = inflightDays.get(k);
    if (existing) return existing;
    const p = (async () => {
      try {
        const r: ChatMessagesResponse = await listChatMessagesForDay(
          pageId, day, senders,
        );
        set((state) => ({
          caches: {
            ...state.caches,
            [k]: {
              messages: r.messages,
              authors: r.authors,
              day: r.day,
              fetchedAt: Date.now(),
            },
          },
        }));
      } finally {
        inflightDays.delete(k);
      }
    })();
    inflightDays.set(k, p);
    return p;
  },

  fetchCounts: async (pageId, month) => {
    const k = monthKey(pageId, month);
    const existing = inflightCounts.get(k);
    if (existing) return existing;
    const p = (async () => {
      try {
        const r: ChatMessageCountsResponse = await listChatMessageCounts(
          pageId, month,
        );
        set((state) => ({
          counts: {
            ...state.counts,
            [k]: { month: r.month, counts: r.counts, fetchedAt: Date.now() },
          },
        }));
      } finally {
        inflightCounts.delete(k);
      }
    })();
    inflightCounts.set(k, p);
    return p;
  },

  applyStoredMessage: (pageId, day, message) => {
    const k = dayKey(pageId, day);
    const existing = get().caches[k];
    if (!existing) return;
    if (existing.messages.some((m) => m.id === message.id)) return;
    const next = [...existing.messages, message].sort((a, b) =>
      a.posted_at.localeCompare(b.posted_at),
    );
    set((state) => ({
      caches: { ...state.caches, [k]: { ...existing, messages: next } },
    }));
  },
}));
