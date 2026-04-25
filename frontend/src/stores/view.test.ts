import { describe, expect, it, beforeEach } from "vitest";
import { useViewStore } from "./view";

describe("view store", () => {
  beforeEach(() => {
    useViewStore.setState({ view: "dashboard" });
  });

  it("starts at dashboard", () => {
    expect(useViewStore.getState().view).toBe("dashboard");
  });

  it("can switch to whop", () => {
    useViewStore.getState().setView("whop");
    expect(useViewStore.getState().view).toBe("whop");
  });

  it("can switch to database", () => {
    useViewStore.getState().setView("database");
    expect(useViewStore.getState().view).toBe("database");
  });
});
