import { describe, expect, it, beforeEach, vi } from "vitest";
import { useChatStore } from "./chatStore";
import * as chatApi from "../api/chat";

function resetStore() {
  useChatStore.setState({ caches: {}, counts: {} });
}

describe("chatStore", () => {
  beforeEach(() => {
    resetStore();
    vi.restoreAllMocks();
  });

  it("fetchDay populates caches[pid|day]", async () => {
    vi.spyOn(chatApi, "listChatMessagesForDay").mockResolvedValue({
      messages: [
        { id: "m1", page_id: "p1", author: "alice", content: "hi",
          posted_at: "2026-05-23T01:00:00Z", quoted: null, image_url: null },
      ] as any,
      authors: [{ name: "alice", count: 1 }],
      day: { start: "2026-05-22T16:00:00Z", end: "2026-05-23T16:00:00Z" },
    });

    await useChatStore.getState().fetchDay("p1", "2026-05-23", []);
    const cache = useChatStore.getState().caches["p1|2026-05-23"];
    expect(cache).toBeDefined();
    expect(cache.messages).toHaveLength(1);
    expect(cache.authors[0].name).toBe("alice");
  });

  it("fetchCounts populates counts[pid|month] and excludes zero days", async () => {
    vi.spyOn(chatApi, "listChatMessageCounts").mockResolvedValue({
      month: "2026-05",
      counts: { "2026-05-22": 14, "2026-05-23": 3 },
    });

    await useChatStore.getState().fetchCounts("p1", "2026-05");
    const c = useChatStore.getState().counts["p1|2026-05"];
    expect(c.counts["2026-05-22"]).toBe(14);
    expect(c.counts["2026-05-21"]).toBeUndefined();
  });

  it("applyStoredMessage appends + dedupes within a cached day", () => {
    useChatStore.setState({
      caches: {
        "p1|2026-05-23": {
          messages: [
            { id: "m1", page_id: "p1", author: "a", content: "x",
              posted_at: "2026-05-23T01:00:00Z", quoted: null, image_url: null } as any,
          ],
          authors: [],
          day: { start: "2026-05-22T16:00:00Z", end: "2026-05-23T16:00:00Z" },
          fetchedAt: 0,
        },
      },
      counts: {},
    });

    const newMsg = {
      id: "m2", page_id: "p1", author: "a", content: "y",
      posted_at: "2026-05-23T02:00:00Z", quoted: null, image_url: null,
    } as any;
    useChatStore.getState().applyStoredMessage("p1", "2026-05-23", newMsg);
    useChatStore.getState().applyStoredMessage("p1", "2026-05-23", newMsg);  // dedupe

    expect(useChatStore.getState().caches["p1|2026-05-23"].messages.map(m => m.id))
      .toEqual(["m1", "m2"]);
  });

  it("applyStoredMessage drops update for uncached day", () => {
    const newMsg = {
      id: "m1", page_id: "p1", author: "a", content: "x",
      posted_at: "2026-05-23T01:00:00Z", quoted: null, image_url: null,
    } as any;
    useChatStore.getState().applyStoredMessage("p1", "2026-05-23", newMsg);
    expect(useChatStore.getState().caches["p1|2026-05-23"]).toBeUndefined();
  });

  it("fetchDay dedupes in-flight requests for the same (pid, day)", async () => {
    const spy = vi.spyOn(chatApi, "listChatMessagesForDay").mockImplementation(
      () => new Promise((resolve) => setTimeout(() => resolve({
        messages: [], authors: [],
        day: { start: "", end: "" },
      }), 10)),
    );

    const fetchDay = useChatStore.getState().fetchDay;
    await Promise.all([
      fetchDay("p1", "2026-05-23", []),
      fetchDay("p1", "2026-05-23", []),
    ]);
    expect(spy).toHaveBeenCalledTimes(1);
  });

  it("fetchCounts dedupes in-flight requests for the same (pid, month)", async () => {
    const spy = vi.spyOn(chatApi, "listChatMessageCounts").mockImplementation(
      () => new Promise((resolve) => setTimeout(() => resolve({
        month: "2026-05",
        counts: {},
      }), 10)),
    );

    const fetchCounts = useChatStore.getState().fetchCounts;
    await Promise.all([
      fetchCounts("p1", "2026-05"),
      fetchCounts("p1", "2026-05"),
    ]);
    expect(spy).toHaveBeenCalledTimes(1);
  });
});
