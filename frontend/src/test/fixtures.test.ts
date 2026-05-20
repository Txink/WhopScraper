// frontend/src/test/fixtures.test.ts
import { describe, expect, it } from "vitest";
import {
  makeMessage,
  makeStockTask,
  makeOptionTask,
  makePushEvent,
  makeConsecutiveMessages,
  makeQuotedMessage,
  makeFailedParseTask,
} from "./fixtures";

describe("fixtures defaults are deterministic", () => {
  it("first message has id m0 + default sender alpha", () => {
    const m = makeMessage();
    expect(m.id).toBe("m0");
    expect(m.author).toBe("alpha");
    expect(m.posted_at).toBe("2026-05-21T01:00:00.000Z");
  });

  it("consecutive messages share author and increment time", () => {
    const list = makeConsecutiveMessages("bob", ["hi", "yo"]);
    expect(list.map((m) => m.author)).toEqual(["bob", "bob"]);
    expect(list[0].posted_at).not.toBe(list[1].posted_at);
  });

  it("makeStockTask defaults to FILLED + instruction set", () => {
    const t = makeStockTask();
    expect(t.type).toBe("stock");
    expect(t.status).toBe("FILLED");
    expect(t.instruction?.ticker).toBe("TSLL");
  });

  it("makeOptionTask carries strike/expiry", () => {
    const t = makeOptionTask();
    expect(t.type).toBe("option");
    expect(t.instruction?.strike).toBe(880);
    expect(t.instruction?.expiry).toBe("2026-12-15");
  });

  it("makeFailedParseTask has no instruction + PARSE_ERROR", () => {
    const t = makeFailedParseTask();
    expect(t.status).toBe("PARSE_ERROR");
    expect(t.instruction).toBeNull();
  });

  it("makeQuotedMessage embeds quoted block", () => {
    const m = makeQuotedMessage("a", "same — looking", { author: "b", content: "if we break 470" });
    expect(m.quoted?.author).toBe("b");
    expect(m.quoted?.content).toBe("if we break 470");
  });

  it("makePushEvent returns a sensible default", () => {
    const e = makePushEvent();
    expect(e.state).toBe("submit");
  });
});
