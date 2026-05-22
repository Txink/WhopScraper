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
  });

  it("setPages stores list and flips pagesLoaded", () => {
    usePageTabsStore.getState().setPages([makePage({ id: "a" }), makePage({ id: "b" })]);
    expect(usePageTabsStore.getState().pages).toHaveLength(2);
    expect(usePageTabsStore.getState().pagesLoaded).toBe(true);
  });

  it("setPages with empty list still flips pagesLoaded", () => {
    usePageTabsStore.getState().setPages([]);
    expect(usePageTabsStore.getState().pages).toHaveLength(0);
    expect(usePageTabsStore.getState().pagesLoaded).toBe(true);
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

  it("removePageIfPresent drops the page when present, no-op otherwise", () => {
    const p: WhopPage = makePage({ id: "p1" });
    usePageTabsStore.setState({ pages: [p], expandedTaskIdByTab: {}, pagesLoaded: true });
    usePageTabsStore.getState().removePageIfPresent("missing");
    expect(usePageTabsStore.getState().pages).toEqual([p]);
    usePageTabsStore.getState().removePageIfPresent("p1");
    expect(usePageTabsStore.getState().pages).toEqual([]);
  });
});
