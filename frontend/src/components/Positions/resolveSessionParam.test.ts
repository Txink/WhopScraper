import { describe, it, expect } from "vitest";
import { resolveSessionParam } from "./resolveSessionParam";

describe("resolveSessionParam", () => {
  it("US always returns 'all' (unified day window covers every region)", () => {
    expect(resolveSessionParam("US", "pre")).toBe("all");
    expect(resolveSessionParam("US", "regular")).toBe("all");
    expect(resolveSessionParam("US", "post")).toBe("all");
    expect(resolveSessionParam("US", "overnight")).toBe("all");
    expect(resolveSessionParam("US", "closed")).toBe("all");
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
