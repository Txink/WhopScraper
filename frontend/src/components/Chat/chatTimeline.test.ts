import { describe, expect, it } from "vitest";
import type { TaskSummary } from "../../api/domain-types";
import type { ChatMessageOut } from "./chatCards";
import {
  buildTimeline, buildFilterBlocks, buildStreamGroups,
} from "./chatTimeline";

function msg(id: string, author: string, at: string, content = "x"): ChatMessageOut {
  return { id, page_id: "p1", author, posted_at: at, content };
}
function signalTask(
  id: string,
  at: string,
  type: "stock" | "option",
  url: string,
): TaskSummary {
  return {
    id, type, status: "FILLED",
    message: {
      id, source: "whop", author: "monitor", content: "x",
      posted_at: at, received_at: at, url,
      raw_content: "x", quoted_message_id: null,
    },
    instruction: { instruction_type: "BUY", ticker: "X", symbol: "X.US", price: 1, quantity: 1 },
    last_cum_qty: 1, last_cum_avg_price: 1,
    created_at: at, updated_at: at,
    order_id: null, stage_timings: {}, reject_reason: null,
  } as unknown as TaskSummary;
}
const urlToName: Record<string, string> = {
  "https://stock-a": "TSLL 监听",
  "https://opt-b": "NVDA 期权监听",
};

describe("buildTimeline", () => {
  it("interleaves msgs and signals by posted_at", () => {
    const tl = buildTimeline(
      [msg("m1", "a", "2026-05-20T01:00Z"), msg("m2", "a", "2026-05-20T01:03Z")],
      [signalTask("t1", "2026-05-20T01:01Z", "stock", "https://stock-a")],
      urlToName,
    );
    expect(tl.map(e => e.kind)).toEqual(["msg", "signal", "msg"]);
  });
});

describe("buildFilterBlocks", () => {
  it("aggregates stock signals into one 正股 block, opt into one 期权 block", () => {
    const tl = buildTimeline(
      [msg("m1", "alpha", "2026-05-20T01:00Z")],
      [
        signalTask("t1", "2026-05-20T01:01Z", "stock", "https://stock-a"),
        signalTask("t2", "2026-05-20T01:02Z", "stock", "https://stock-a"),
        signalTask("t3", "2026-05-20T01:03Z", "option", "https://opt-b"),
      ],
      urlToName,
    );
    const blocks = buildFilterBlocks(tl, new Set(["alpha", "TSLL 监听", "NVDA 期权监听"]), urlToName);
    const kinds = blocks.map(b => b.kind);
    expect(kinds).toContain("aggregate-stock");
    expect(kinds).toContain("aggregate-option");
    const stockBlock = blocks.find(b => b.kind === "aggregate-stock");
    if (stockBlock && stockBlock.kind === "aggregate-stock") {
      expect(stockBlock.tasks).toHaveLength(2);
    }
  });

  it("aggregate block hidden when none of its monitor chips are watched", () => {
    const tl = buildTimeline(
      [], [signalTask("t1", "2026-05-20T01:01Z", "stock", "https://stock-a")],
      urlToName,
    );
    const blocks = buildFilterBlocks(tl, new Set(), urlToName);
    expect(blocks.find(b => b.kind === "aggregate-stock")).toBeUndefined();
  });

  it("watching only the chat sender — no aggregate blocks", () => {
    const tl = buildTimeline(
      [msg("m1", "alpha", "2026-05-20T01:00Z")],
      [signalTask("t1", "2026-05-20T01:01Z", "stock", "https://stock-a")],
      urlToName,
    );
    const blocks = buildFilterBlocks(tl, new Set(["alpha"]), urlToName);
    expect(blocks).toHaveLength(0);
  });
});

describe("buildStreamGroups", () => {
  it("merges consecutive same-author msgs into one group", () => {
    const tl = buildTimeline(
      [
        msg("m1", "a", "2026-05-20T01:00Z"),
        msg("m2", "a", "2026-05-20T01:01Z"),
        msg("m3", "b", "2026-05-20T01:02Z"),
      ], [],
      urlToName,
    );
    const groups = buildStreamGroups(tl, urlToName);
    expect(groups).toHaveLength(2);
    expect(groups[0].kind).toBe("msgs");
    if (groups[0].kind === "msgs") expect(groups[0].entries).toHaveLength(2);
    if (groups[1].kind === "msgs") expect(groups[1].entries).toHaveLength(1);
  });

  it("signal task breaks a same-author group", () => {
    const tl = buildTimeline(
      [
        msg("m1", "a", "2026-05-20T01:00Z"),
        msg("m2", "a", "2026-05-20T01:02Z"),
      ],
      [signalTask("t1", "2026-05-20T01:01Z", "stock", "https://stock-a")],
      urlToName,
    );
    const groups = buildStreamGroups(tl, urlToName);
    expect(groups.map(g => g.sender)).toEqual(["a", "TSLL 监听", "a"]);
  });

  it("signal task always gets its own group (no merging across signals)", () => {
    const tl = buildTimeline(
      [],
      [
        signalTask("t1", "2026-05-20T01:01Z", "stock", "https://stock-a"),
        signalTask("t2", "2026-05-20T01:02Z", "stock", "https://stock-a"),
      ],
      urlToName,
    );
    const groups = buildStreamGroups(tl, urlToName);
    expect(groups).toHaveLength(2);
    expect(groups.every(g => g.kind === "signal")).toBe(true);
  });
});
