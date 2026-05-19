import { describe, it, expect } from "vitest";
import { buildExportPayload } from "./chatExport";
import { groupIntoCards, type ChatMessageOut } from "./chatCards";

function msg(
  id: string,
  author: string,
  posted_at: string,
  opts: { quoted?: { author: string; content: string } } = {},
): ChatMessageOut {
  return {
    id,
    page_id: "p1",
    author,
    content: `body ${id}`,
    posted_at,
    quoted: opts.quoted
      ? { message_id: null, ...opts.quoted, posted_at: null }
      : undefined,
  };
}

describe("buildExportPayload", () => {
  it("emits card_index increasing from 0", () => {
    // alice batch, then a quote — but with the new model the quote
    // extends the batch into a single quote-kind chunk. Use a non-
    // watched gap of >=5 to force two distinct cards.
    const messages = [
      msg("a0", "alice", "2026-05-18T09:00:00Z"),
      ...Array.from({ length: 5 }, (_, i) =>
        msg(`c${i}`, "carol", `2026-05-18T09:${String(i + 1).padStart(2, "0")}:00Z`)),
      msg("q1", "alice", "2026-05-18T09:07:00Z", {
        quoted: { author: "bob", content: "earlier" },
      }),
    ];
    const cards = groupIntoCards(messages, new Set(["alice"]));
    const payload = buildExportPayload({
      page_id: "p1",
      page_name: "Test Page",
      week: { start: "2026-05-18", end: "2026-05-25" },
      watched_senders: ["alice"],
      messages,
      cards,
    });
    expect(payload.cards.map((c) => c.card_index)).toEqual([0, 1]);
  });

  it("13 same-author msgs stay in a single batch card (no cap)", () => {
    const messages = Array.from({ length: 13 }, (_, i) =>
      msg(`m${i}`, "alice", `2026-05-18T09:${String(i).padStart(2, "0")}:00Z`),
    );
    const cards = groupIntoCards(messages, new Set(["alice"]));
    const payload = buildExportPayload({
      page_id: "p1",
      page_name: "Test",
      week: { start: "x", end: "y" },
      watched_senders: ["alice"],
      messages,
      cards,
    });
    expect(payload.cards).toHaveLength(1);
    expect(payload.messages).toHaveLength(13);
    expect(payload.messages.every((m) => m.card_index === 0)).toBe(true);
  });

  it("batch card items carry kind + msg_id in chronological order", () => {
    const messages = [
      msg("c0", "carol", "2026-05-18T09:00:00Z"),
      msg("c1", "carol", "2026-05-18T09:01:00Z"),
      msg("c2", "carol", "2026-05-18T09:02:00Z"),
      msg("a0", "alice", "2026-05-18T09:03:00Z"),
      msg("d0", "dave", "2026-05-18T09:04:00Z"),
      msg("a1", "alice", "2026-05-18T09:05:00Z"),
    ];
    const cards = groupIntoCards(messages, new Set(["alice"]));
    const payload = buildExportPayload({
      page_id: "p1",
      page_name: "Test",
      week: { start: "x", end: "y" },
      watched_senders: ["alice"],
      messages,
      cards,
    });
    expect(payload.cards).toHaveLength(1);
    const card = payload.cards[0];
    expect(card.kind).toBe("batch");
    if (card.kind === "batch") {
      expect(card.items).toEqual([
        { kind: "context", msg_id: "c0" },
        { kind: "context", msg_id: "c1" },
        { kind: "context", msg_id: "c2" },
        { kind: "watched", msg_id: "a0" },
        { kind: "context", msg_id: "d0" },
        { kind: "watched", msg_id: "a1" },
      ]);
    }
    expect(payload.messages.every((m) => m.card_index === 0)).toBe(true);
  });

  it("quote card carries quoted ref + items including watched continuations", () => {
    const messages = [
      msg("q1", "alice", "2026-05-18T09:00:00Z", {
        quoted: { author: "bob", content: "earlier" },
      }),
      msg("a1", "alice", "2026-05-18T09:01:00Z"),
    ];
    const cards = groupIntoCards(messages, new Set(["alice"]));
    const payload = buildExportPayload({
      page_id: "p1",
      page_name: "Test",
      week: { start: "x", end: "y" },
      watched_senders: ["alice"],
      messages,
      cards,
    });
    expect(payload.cards).toHaveLength(1);
    const card = payload.cards[0];
    expect(card.kind).toBe("quote");
    if (card.kind === "quote") {
      expect(card.quoted.author).toBe("bob");
      expect(card.items).toEqual([
        { kind: "watched", msg_id: "q1" },
        { kind: "watched", msg_id: "a1" },
      ]);
    }
  });
});
