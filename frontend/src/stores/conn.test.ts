import { describe, expect, it, beforeEach } from "vitest";
import { useConnStore } from "./conn";

describe("conn store", () => {
  beforeEach(() => {
    useConnStore.setState({
      ws: "closed", whop: "unknown", longport: "unknown",
      mode: "", dryRun: true, autoTrade: true, lastEventId: null,
    });
  });

  it("setWs updates status", () => {
    useConnStore.getState().setWs("open");
    expect(useConnStore.getState().ws).toBe("open");
  });

  it("setHealth normalizes account_label + dry_run", () => {
    useConnStore.getState().setHealth({
      whop: "up",
      longport: "up",
      account_label: "real",
      dry_run: false,
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

  it("setRuntimeSettings reflects active account's label", () => {
    useConnStore.getState().setRuntimeSettings({
      active_account_id: "acct-2",
      accounts: [
        { account_id: "acct-1", label: "paper", authorized: true },
        { account_id: "acct-2", label: "real", authorized: true },
      ],
      auto_trade: false,
      region: "cn",
      dry_run: false,
    });
    const s = useConnStore.getState();
    expect(s.mode).toBe("real");
    expect(s.dryRun).toBe(false);
    expect(s.autoTrade).toBe(false);
  });
});
