import { describe, it, expect, beforeEach } from "vitest";
import { usePageTabsStore } from "./pageTabs";
import type { WhopPage } from "../api/domain-types";

const makePage = (overrides: Partial<WhopPage> = {}): WhopPage => ({
  id: "p1",
  url: "https://whop.com/p1/app/",
  source: "stock",
  name: "Stock1",
  added_at: "2026-04-25T00:00:00Z",
  settings: { dedupe_processed_messages: true, price_deviation_tolerance: 1, block_historical_messages: false, tickers: {} },
  running: true,
  started_at: null,
  last_poll_at: null,
  messages_published: 0,
  last_error: null,
  ...overrides,
});

describe("pageTabs store", () => {
  beforeEach(() => {
    usePageTabsStore.getState().reset();
    localStorage.clear();
  });

  it("setPages stores list and auto-selects first when no last_active", () => {
    usePageTabsStore.getState().setPages([makePage({ id: "a" }), makePage({ id: "b" })]);
    expect(usePageTabsStore.getState().pages).toHaveLength(2);
    expect(usePageTabsStore.getState().activeTabId).toBe("a");
  });

  it("setPages restores last_active from localStorage", () => {
    localStorage.setItem("DASHBOARD_LAST_TAB", "b");
    usePageTabsStore.getState().setPages([makePage({ id: "a" }), makePage({ id: "b" })]);
    expect(usePageTabsStore.getState().activeTabId).toBe("b");
  });

  it("setPages falls back to first when last_active missing", () => {
    localStorage.setItem("DASHBOARD_LAST_TAB", "nonexistent");
    usePageTabsStore.getState().setPages([makePage({ id: "a" })]);
    expect(usePageTabsStore.getState().activeTabId).toBe("a");
  });

  it("setPages with empty list sets activeTabId to null", () => {
    usePageTabsStore.getState().setPages([]);
    expect(usePageTabsStore.getState().activeTabId).toBeNull();
  });

  it("setActiveTab persists to localStorage", () => {
    usePageTabsStore.getState().setPages([makePage({ id: "a" }), makePage({ id: "b" })]);
    usePageTabsStore.getState().setActiveTab("b");
    expect(localStorage.getItem("DASHBOARD_LAST_TAB")).toBe("b");
  });

  it("setActiveTab(orphan) does not write localStorage", () => {
    usePageTabsStore.getState().setPages([makePage({ id: "a" })]);
    usePageTabsStore.getState().setActiveTab("orphan");
    expect(usePageTabsStore.getState().activeTabId).toBe("orphan");
    expect(localStorage.getItem("DASHBOARD_LAST_TAB")).toBeNull();
  });

  it("toggleExpandedTask: same id twice collapses; different id switches the open slot", () => {
    // Expand t1.
    usePageTabsStore.getState().toggleExpandedTask("a", "t1");
    expect(usePageTabsStore.getState().expandedTaskIdByTab["a"]).toBe("t1");
    // Click t1 again → collapse.
    usePageTabsStore.getState().toggleExpandedTask("a", "t1");
    expect(usePageTabsStore.getState().expandedTaskIdByTab["a"]).toBeNull();
    // Expand t1 then click t2 → t2 takes the slot.
    usePageTabsStore.getState().toggleExpandedTask("a", "t1");
    usePageTabsStore.getState().toggleExpandedTask("a", "t2");
    expect(usePageTabsStore.getState().expandedTaskIdByTab["a"]).toBe("t2");
  });

  it("toggleExpandedTask is per-tab — different tabs have independent slots", () => {
    usePageTabsStore.getState().toggleExpandedTask("a", "t1");
    usePageTabsStore.getState().toggleExpandedTask("b", "t9");
    expect(usePageTabsStore.getState().expandedTaskIdByTab["a"]).toBe("t1");
    expect(usePageTabsStore.getState().expandedTaskIdByTab["b"]).toBe("t9");
  });

  it("applyPageChanged action=added appends to pages", () => {
    usePageTabsStore.getState().setPages([makePage({ id: "a" })]);
    usePageTabsStore.getState().applyPageChanged({
      type: "whop.page_changed",
      event_id: 1,
      payload: { action: "added", page: makePage({ id: "b" }) },
    });
    expect(usePageTabsStore.getState().pages.map(p => p.id)).toEqual(["a", "b"]);
  });

  it("applyPageChanged action=removed drops from pages", () => {
    usePageTabsStore.getState().setPages([makePage({ id: "a" }), makePage({ id: "b" })]);
    usePageTabsStore.getState().applyPageChanged({
      type: "whop.page_changed",
      event_id: 2,
      payload: { action: "removed", page: makePage({ id: "a" }) },
    });
    expect(usePageTabsStore.getState().pages.map(p => p.id)).toEqual(["b"]);
  });

  it("applyPageChanged action=settings_updated replaces page in place", () => {
    usePageTabsStore.getState().setPages([makePage({ id: "a", name: "old" })]);
    usePageTabsStore.getState().applyPageChanged({
      type: "whop.page_changed",
      event_id: 3,
      payload: { action: "settings_updated", page: makePage({ id: "a", name: "new" }) },
    });
    expect(usePageTabsStore.getState().pages[0].name).toBe("new");
  });

  it("applyPageChanged action=restarted replaces page in place", () => {
    usePageTabsStore.getState().setPages([makePage({ id: "a", running: false })]);
    usePageTabsStore.getState().applyPageChanged({
      type: "whop.page_changed",
      event_id: 4,
      payload: { action: "restarted", page: makePage({ id: "a", running: true }) },
    });
    expect(usePageTabsStore.getState().pages[0].running).toBe(true);
  });

  it("pagesLoaded defaults to false", () => {
    expect(usePageTabsStore.getState().pagesLoaded).toBe(false);
  });

  it("setPages flips pagesLoaded to true", () => {
    expect(usePageTabsStore.getState().pagesLoaded).toBe(false);
    usePageTabsStore.getState().setPages([makePage({ id: "a" })]);
    expect(usePageTabsStore.getState().pagesLoaded).toBe(true);
  });

  it("setPages with empty list still flips pagesLoaded to true", () => {
    usePageTabsStore.getState().setPages([]);
    expect(usePageTabsStore.getState().pagesLoaded).toBe(true);
  });

  it("markPagesLoaded sets pagesLoaded to true", () => {
    usePageTabsStore.getState().markPagesLoaded();
    expect(usePageTabsStore.getState().pagesLoaded).toBe(true);
  });

  it("reset() resets pagesLoaded to false", () => {
    usePageTabsStore.getState().setPages([makePage({ id: "a" })]);
    expect(usePageTabsStore.getState().pagesLoaded).toBe(true);
    usePageTabsStore.getState().reset();
    expect(usePageTabsStore.getState().pagesLoaded).toBe(false);
  });

  it("applyPageChanged removed-active falls back to first page", () => {
    usePageTabsStore.getState().setPages([makePage({ id: "a" }), makePage({ id: "b" })]);
    usePageTabsStore.getState().setActiveTab("a");
    usePageTabsStore.getState().applyPageChanged({
      type: "whop.page_changed",
      event_id: 5,
      payload: { action: "removed", page: makePage({ id: "a" }) },
    });
    expect(usePageTabsStore.getState().activeTabId).toBe("b");
  });

  it("removePageIfPresent drops the page when present, no-op otherwise", () => {
    const p: WhopPage = makePage({ id: "p1" });
    usePageTabsStore.setState({ pages: [p], activeTabId: "p1", expandedTaskIdByTab: {}, orphanCount: 0, pagesLoaded: true });
    usePageTabsStore.getState().removePageIfPresent("missing");
    expect(usePageTabsStore.getState().pages).toEqual([p]);
    usePageTabsStore.getState().removePageIfPresent("p1");
    expect(usePageTabsStore.getState().pages).toEqual([]);
  });
});
