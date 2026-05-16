import { describe, it, expect } from "vitest";
import { resolveSessionParam } from "./resolveSessionParam";

describe("resolveSessionParam", () => {
  it("passes US active sessions through unchanged", () => {
    expect(resolveSessionParam("US", "pre")).toBe("pre");
    expect(resolveSessionParam("US", "regular")).toBe("regular");
    expect(resolveSessionParam("US", "post")).toBe("post");
    expect(resolveSessionParam("US", "overnight")).toBe("overnight");
  });

  it("US closed → falls back to post", () => {
    expect(resolveSessionParam("US", "closed")).toBe("post");
  });

  it("HK regular → regular", () => {
    expect(resolveSessionParam("HK", "regular")).toBe("regular");
  });

  it("HK closed → regular", () => {
    expect(resolveSessionParam("HK", "closed")).toBe("regular");
  });

  it("CN closed → regular", () => {
    expect(resolveSessionParam("CN", "closed")).toBe("regular");
  });

  it("HK with unreachable session → regular fallback", () => {
    expect(resolveSessionParam("HK", "pre")).toBe("regular");
    expect(resolveSessionParam("HK", "post")).toBe("regular");
    expect(resolveSessionParam("HK", "overnight")).toBe("regular");
  });
});
