import { describe, it, expect } from "vitest";
import {
  groupIntoCards,
  watchedCount,
  type BatchItem,
  type ChatMessageOut,
} from "./chatCards";

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

const sig = (items: BatchItem[]): string =>
  items.map((i) => `${i.kind[0]}:${i.msg.id}`).join(",");

describe("groupIntoCards", () => {
  it("returns [] for empty input", () => {
    expect(groupIntoCards([], new Set(["alice"]))).toEqual([]);
  });

  it("returns [] when only non-watched messages are present", () => {
    const out = groupIntoCards(
      [msg("m1", "bob", "2026-05-18T09:00:00Z")],
      new Set(["alice"]),
    );
    expect(out).toEqual([]);
  });

  it("collapses consecutive same-author watched msgs into one batch", () => {
    const msgs = ["09:00", "09:01", "09:02"].map((t, i) =>
      msg(`m${i}`, "alice", `2026-05-18T${t}:00Z`),
    );
    const out = groupIntoCards(msgs, new Set(["alice"]));
    expect(out).toHaveLength(1);
    expect(out[0].kind).toBe("batch");
    if (out[0].kind === "batch") {
      expect(sig(out[0].items)).toBe("w:m0,w:m1,w:m2");
      expect(out[0].id).toBe("batch:m0");
    }
  });

  it("no cap on batch size — 13 consecutive same-author msgs stay in one card", () => {
    const msgs = Array.from({ length: 13 }, (_, i) =>
      msg(`m${i}`, "alice", `2026-05-18T09:${String(i).padStart(2, "0")}:00Z`),
    );
    const out = groupIntoCards(msgs, new Set(["alice"]));
    expect(out).toHaveLength(1);
    if (out[0].kind === "batch") {
      expect(watchedCount(out[0])).toBe(13);
    }
  });

  it("emits a quote card with the quoted ref + the quoting watched msg", () => {
    const m = msg("m1", "alice", "2026-05-18T09:00:00Z", {
      quoted: { author: "bob", content: "earlier" },
    });
    const out = groupIntoCards([m], new Set(["alice"]));
    expect(out).toHaveLength(1);
    expect(out[0].kind).toBe("quote");
    if (out[0].kind === "quote") {
      expect(out[0].id).toBe("m1");
      expect(out[0].quoted.author).toBe("bob");
      expect(sig(out[0].items)).toBe("w:m1");
    }
  });

  it("same-author watched continuation after a quote extends the quote card", () => {
    const msgs = [
      msg("q1", "alice", "2026-05-18T09:00:00Z", {
        quoted: { author: "bob", content: "earlier" },
      }),
      msg("a1", "alice", "2026-05-18T09:01:00Z"),
      msg("a2", "alice", "2026-05-18T09:02:00Z"),
    ];
    const out = groupIntoCards(msgs, new Set(["alice"]));
    expect(out).toHaveLength(1);
    if (out[0].kind === "quote") {
      expect(sig(out[0].items)).toBe("w:q1,w:a1,w:a2");
      expect(watchedCount(out[0])).toBe(3);
    }
  });

  it("a same-author quote within an existing run merges into the SAME card", () => {
    const msgs = [
      msg("a0", "alice", "2026-05-18T09:00:00Z"),
      msg("a1", "alice", "2026-05-18T09:01:00Z"),
      msg("q1", "alice", "2026-05-18T09:02:00Z", {
        quoted: { author: "bob", content: "earlier" },
      }),
    ];
    const out = groupIntoCards(msgs, new Set(["alice"]));
    expect(out).toHaveLength(1);
    // Opening message a0 had no quote → batch kind. The quoted reply
    // q1 absorbs into the same card; its quoted snippet renders inline
    // via m.quoted on the bubble itself.
    expect(out[0].kind).toBe("batch");
    if (out[0].kind === "batch") {
      expect(sig(out[0].items)).toBe("w:a0,w:a1,w:q1");
    }
  });

  it("two consecutive quotes within a same-author run stay in ONE card", () => {
    const msgs = [
      msg("q1", "alice", "2026-05-18T09:00:00Z", {
        quoted: { author: "bob", content: "earlier" },
      }),
      msg("a1", "alice", "2026-05-18T09:01:00Z"),
      msg("q2", "alice", "2026-05-18T09:02:00Z", {
        quoted: { author: "carol", content: "later" },
      }),
    ];
    const out = groupIntoCards(msgs, new Set(["alice"]));
    expect(out).toHaveLength(1);
    expect(out[0].kind).toBe("quote");
    if (out[0].kind === "quote") {
      expect(sig(out[0].items)).toBe("w:q1,w:a1,w:q2");
      expect(out[0].quoted.author).toBe("bob");
    }
  });

  it("MERGES across a non-watched gap of <5: gap msgs are absorbed inline", () => {
    const msgs = [
      msg("a0", "alice", "2026-05-18T09:00:00Z"),
      msg("a1", "alice", "2026-05-18T09:01:00Z"),
      msg("c1", "carol", "2026-05-18T09:02:00Z"),  // not watched
      msg("a2", "alice", "2026-05-18T09:03:00Z"),
      msg("a3", "alice", "2026-05-18T09:04:00Z"),
    ];
    const out = groupIntoCards(msgs, new Set(["alice"]));
    expect(out).toHaveLength(1);
    if (out[0].kind === "batch") {
      // chronological: a0 a1 c1 a2 a3 — c1 is inline context.
      expect(sig(out[0].items)).toBe("w:a0,w:a1,c:c1,w:a2,w:a3");
    }
  });

  it("merges multiple small gaps end-to-end (never reaches the 5-msg threshold)", () => {
    const msgs = [
      msg("a0", "alice", "2026-05-18T09:00:00Z"),
      msg("c0", "carol", "2026-05-18T09:01:00Z"),
      msg("a1", "alice", "2026-05-18T09:02:00Z"),
      msg("d0", "dave", "2026-05-18T09:03:00Z"),
      msg("d1", "dave", "2026-05-18T09:04:00Z"),
      msg("a2", "alice", "2026-05-18T09:05:00Z"),
      msg("e0", "eve", "2026-05-18T09:06:00Z"),
      msg("a3", "alice", "2026-05-18T09:07:00Z"),
    ];
    const out = groupIntoCards(msgs, new Set(["alice"]));
    expect(out).toHaveLength(1);
    if (out[0].kind === "batch") {
      expect(sig(out[0].items)).toBe(
        "w:a0,c:c0,w:a1,c:d0,c:d1,w:a2,c:e0,w:a3",
      );
    }
  });

  it("SPLITS on a non-watched gap of exactly 5 — last 5 become next card's lead-in", () => {
    const msgs = [
      msg("a0", "alice", "2026-05-18T09:00:00Z"),
      msg("c0", "carol", "2026-05-18T09:01:00Z"),
      msg("c1", "carol", "2026-05-18T09:02:00Z"),
      msg("c2", "carol", "2026-05-18T09:03:00Z"),
      msg("c3", "carol", "2026-05-18T09:04:00Z"),
      msg("c4", "carol", "2026-05-18T09:05:00Z"),
      msg("a1", "alice", "2026-05-18T09:06:00Z"),
    ];
    const out = groupIntoCards(msgs, new Set(["alice"]));
    expect(out).toHaveLength(2);
    if (out[0].kind === "batch") {
      expect(sig(out[0].items)).toBe("w:a0");
    }
    if (out[1].kind === "batch") {
      // Gap was 5 carol msgs → new card opens with all 5 as lead-in.
      expect(sig(out[1].items)).toBe("c:c0,c:c1,c:c2,c:c3,c:c4,w:a1");
    }
  });

  it("on a gap of 7 keeps only the most-recent 5 non-watched as lead-in", () => {
    const msgs = [
      msg("a0", "alice", "2026-05-18T09:00:00Z"),
      ...Array.from({ length: 7 }, (_, i) =>
        msg(`c${i}`, "carol", `2026-05-18T09:${String(i + 1).padStart(2, "0")}:00Z`)),
      msg("a1", "alice", "2026-05-18T09:08:00Z"),
    ];
    const out = groupIntoCards(msgs, new Set(["alice"]));
    expect(out).toHaveLength(2);
    if (out[1].kind === "batch") {
      // c0,c1 dropped (oldest); c2..c6 retained.
      expect(sig(out[1].items)).toBe("c:c2,c:c3,c:c4,c:c5,c:c6,w:a1");
    }
  });

  it("two different watched senders split into per-author cards", () => {
    const msgs = [
      msg("a0", "alice", "2026-05-18T09:00:00Z"),
      msg("b0", "bob", "2026-05-18T09:01:00Z"),
      msg("a1", "alice", "2026-05-18T09:02:00Z"),
      msg("b1", "bob", "2026-05-18T09:03:00Z"),
    ];
    const out = groupIntoCards(msgs, new Set(["alice", "bob"]));
    expect(out).toHaveLength(4);
    expect(out.every(c => c.kind === "batch")).toBe(true);
  });

  it("empty watchedSenders → every author counts as watched", () => {
    const msgs = [
      msg("a0", "alice", "2026-05-18T09:00:00Z"),
      msg("b0", "bob", "2026-05-18T09:01:00Z"),
    ];
    const out = groupIntoCards(msgs, new Set<string>());
    expect(out).toHaveLength(2);
  });

  it("attaches up to 5 preceding non-watched msgs as lead-in for a new card", () => {
    const msgs = [
      ...["09:00", "09:01", "09:02", "09:03", "09:04", "09:05", "09:06"].map((t, i) =>
        msg(`c${i}`, "carol", `2026-05-18T${t}:00Z`),
      ),
      msg("a0", "alice", "2026-05-18T09:07:00Z"),
      msg("a1", "alice", "2026-05-18T09:08:00Z"),
    ];
    const out = groupIntoCards(msgs, new Set(["alice"]));
    expect(out).toHaveLength(1);
    if (out[0].kind === "batch") {
      // Gap pre-empts the first watched run: 7 carol msgs ≥ 5 → split
      // never happens because there's no PREVIOUS card. So the new
      // card opens with last 5 of the lead-in.
      expect(sig(out[0].items)).toBe("c:c2,c:c3,c:c4,c:c5,c:c6,w:a0,w:a1");
    }
  });

  it("lead-in excludes other watched senders' messages (they're in their own card)", () => {
    const msgs = [
      msg("b0", "bob", "2026-05-18T09:00:00Z"),          // also watched
      msg("c0", "carol", "2026-05-18T09:01:00Z"),
      msg("c1", "carol", "2026-05-18T09:02:00Z"),
      msg("a0", "alice", "2026-05-18T09:03:00Z"),
    ];
    const out = groupIntoCards(msgs, new Set(["alice", "bob"]));
    expect(out.map((c) => c.kind)).toEqual(["batch", "batch"]);
    if (out[1].kind === "batch") {
      // bob already had his own card; alice's lead-in is just the carol
      // messages between bob and alice.
      expect(sig(out[1].items)).toBe("c:c0,c:c1,w:a0");
    }
  });
});
