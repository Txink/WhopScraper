import { describe, it, expect } from "vitest";
import { groupIntoCards, type ChatMessageOut } from "./chatCards";

function msg(
  id: string, author: string, posted_at: string,
  opts: { quoted?: { author: string; content: string } } = {},
): ChatMessageOut {
  return {
    id, page_id: "p1", author, content: `body ${id}`,
    posted_at,
    quoted: opts.quoted ? { message_id: null, ...opts.quoted, posted_at: null } : undefined,
  };
}

describe("groupIntoCards", () => {
  it("returns [] for empty input", () => {
    expect(groupIntoCards([], new Set(["alice"]), 5)).toEqual([]);
  });

  it("skips non-watched senders entirely", () => {
    const out = groupIntoCards(
      [msg("m1", "bob", "2026-05-18T09:00:00Z")],
      new Set(["alice"]),
      5,
    );
    expect(out).toEqual([]);
  });

  it("collapses consecutive unquoted msgs from one watched sender into one batch", () => {
    const msgs = ["09:00", "09:01", "09:02"].map((t, i) =>
      msg(`m${i}`, "alice", `2026-05-18T${t}:00Z`),
    );
    const out = groupIntoCards(msgs, new Set(["alice"]), 5);
    expect(out).toHaveLength(1);
    expect(out[0].kind).toBe("batch");
    if (out[0].kind === "batch") {
      expect(out[0].msgs.map(m => m.id)).toEqual(["m0", "m1", "m2"]);
      expect(out[0].overflow).toBe(0);
      expect(out[0].id).toBe("batch:m0");
    }
  });

  it("caps batch at maxN and counts overflow", () => {
    const msgs = Array.from({ length: 7 }, (_, i) =>
      msg(`m${i}`, "alice", `2026-05-18T09:${String(i).padStart(2, "0")}:00Z`),
    );
    const out = groupIntoCards(msgs, new Set(["alice"]), 5);
    expect(out).toHaveLength(1);
    if (out[0].kind === "batch") {
      expect(out[0].msgs).toHaveLength(5);
      expect(out[0].overflow).toBe(2);
    }
  });

  it("makes one quote card per quoted reply", () => {
    const m = msg("m1", "alice", "2026-05-18T09:00:00Z", {
      quoted: { author: "bob", content: "earlier" },
    });
    const out = groupIntoCards([m], new Set(["alice"]), 5);
    expect(out).toHaveLength(1);
    expect(out[0].kind).toBe("quote");
    if (out[0].kind === "quote") {
      expect(out[0].id).toBe("m1");
      expect(out[0].quoted.author).toBe("bob");
    }
  });

  it("the 4+1+3 example splits into 3 cards (batch / quote / batch)", () => {
    const msgs = [
      ...["09:00", "09:01", "09:02", "09:03"].map((t, i) =>
        msg(`a${i}`, "alice", `2026-05-18T${t}:00Z`)),
      msg("q1", "alice", "2026-05-18T09:05:00Z", {
        quoted: { author: "bob", content: "earlier" },
      }),
      ...["09:06", "09:07", "09:08"].map((t, i) =>
        msg(`b${i}`, "alice", `2026-05-18T${t}:00Z`)),
    ];
    const out = groupIntoCards(msgs, new Set(["alice"]), 5);
    expect(out.map(c => c.kind)).toEqual(["batch", "quote", "batch"]);
    if (out[0].kind === "batch") expect(out[0].msgs).toHaveLength(4);
    if (out[2].kind === "batch") expect(out[2].msgs).toHaveLength(3);
  });

  it("non-watched sender interleave does NOT split the batch", () => {
    const msgs = [
      msg("a0", "alice", "2026-05-18T09:00:00Z"),
      msg("a1", "alice", "2026-05-18T09:01:00Z"),
      msg("c1", "carol", "2026-05-18T09:02:00Z"),  // not watched
      msg("a2", "alice", "2026-05-18T09:03:00Z"),
      msg("a3", "alice", "2026-05-18T09:04:00Z"),
    ];
    const out = groupIntoCards(msgs, new Set(["alice"]), 5);
    expect(out).toHaveLength(1);
    if (out[0].kind === "batch") {
      expect(out[0].msgs.map(m => m.id)).toEqual(["a0", "a1", "a2", "a3"]);
    }
  });

  it("two watched senders alternating split into per-author batches", () => {
    const msgs = [
      msg("a0", "alice", "2026-05-18T09:00:00Z"),
      msg("b0", "bob", "2026-05-18T09:01:00Z"),
      msg("a1", "alice", "2026-05-18T09:02:00Z"),
      msg("b1", "bob", "2026-05-18T09:03:00Z"),
    ];
    const out = groupIntoCards(msgs, new Set(["alice", "bob"]), 5);
    expect(out).toHaveLength(4);
    expect(out.every(c => c.kind === "batch")).toBe(true);
  });

  it("empty watchedSenders → treat all as watched", () => {
    const msgs = [
      msg("a0", "alice", "2026-05-18T09:00:00Z"),
      msg("b0", "bob", "2026-05-18T09:01:00Z"),
    ];
    const out = groupIntoCards(msgs, new Set<string>(), 5);
    expect(out.length).toBeGreaterThan(0);
    // alice and bob both yield batches (different authors → 2 cards)
    expect(out).toHaveLength(2);
  });
});
