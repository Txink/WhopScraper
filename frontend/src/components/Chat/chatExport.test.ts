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
    const messages = [
      msg("a0", "alice", "2026-05-18T09:00:00Z"),
      msg("a1", "alice", "2026-05-18T09:01:00Z"),
      msg("q1", "alice", "2026-05-18T09:02:00Z", {
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

  it("messages preserve order and carry card_index", () => {
    const messages = [
      msg("a0", "alice", "2026-05-18T09:00:00Z"),
      msg("q1", "alice", "2026-05-18T09:02:00Z", {
        quoted: { author: "bob", content: "earlier" },
      }),
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
    expect(payload.messages.map((m) => m.id)).toEqual(["a0", "q1"]);
    expect(payload.messages[0].card_index).toBe(0);
    expect(payload.messages[1].card_index).toBe(1);
  });

  it("splits 13 same-author msgs into 8 + 5 across two batch cards (export-side)", () => {
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
    expect(payload.cards).toHaveLength(2);
    expect(payload.messages).toHaveLength(13);
    expect(payload.messages.slice(0, 8).every((m) => m.card_index === 0)).toBe(true);
    expect(payload.messages.slice(8).every((m) => m.card_index === 1)).toBe(true);
  });
});
