import { describe, expect, it, beforeEach } from "vitest";
import { useConnStore } from "./conn";

describe("conn store", () => {
  beforeEach(() => {
    useConnStore.setState({
      ws: "closed", whop: "unknown", longport: "unknown",
      mode: "paper", dryRun: true, lastEventId: null,
    });
  });

  it("setWs updates status", () => {
    useConnStore.getState().setWs("open");
    expect(useConnStore.getState().ws).toBe("open");
  });

  it("setHealth normalizes mode + dry_run", () => {
    useConnStore.getState().setHealth({
      whop: "up", longport: "up", mode: "real", dry_run: false,
    });
    const s = useConnStore.getState();
    expect(s.mode).toBe("real");
    expect(s.dryRun).toBe(false);
    expect(s.whop).toBe("up");
  });

  it("setLastEventId updates cursor", () => {
    useConnStore.getState().setLastEventId(42);
    expect(useConnStore.getState().lastEventId).toBe(42);
  });
});
