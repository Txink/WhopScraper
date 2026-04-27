import { describe, it, expect, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { usePageTabsStore } from "../../stores/pageTabs";
import { PageTabs } from "./PageTabs";
import type { WhopPage } from "../../api/domain-types";

const makePage = (overrides: Partial<WhopPage> = {}): WhopPage => ({
  id: "p1", url: "u1", source: "stock", name: "Stock1", added_at: "2026-04-25T00:00:00Z",
  settings: { dedupe_processed_messages: true, price_deviation_tolerance: 1, block_historical_messages: false, tickers: {} },
  running: true, started_at: null, last_poll_at: null, messages_published: 0, last_error: null,
  ...overrides,
});

describe("<PageTabs>", () => {
  beforeEach(() => { usePageTabsStore.getState().reset(); localStorage.clear(); });

  it("renders nothing when no pages", () => {
    const { container } = render(<PageTabs />);
    expect(container.firstChild).toBeNull();
  });

  it("renders tab per page and highlights active", () => {
    usePageTabsStore.getState().setPages([
      makePage({ id: "a", name: "Stock1" }),
      makePage({ id: "b", source: "option", name: "Opt1" }),
    ]);
    render(<PageTabs />);
    expect(screen.getByRole("tab", { name: /Stock1/ })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tab", { name: /Opt1/ })).toHaveAttribute("aria-selected", "false");
  });

  it("clicking switches active tab", () => {
    usePageTabsStore.getState().setPages([
      makePage({ id: "a", name: "Stock1" }),
      makePage({ id: "b", source: "option", name: "Opt1" }),
    ]);
    render(<PageTabs />);
    fireEvent.click(screen.getByRole("tab", { name: /Opt1/ }));
    expect(usePageTabsStore.getState().activeTabId).toBe("b");
  });

  it("shows orphan tab when orphanCount > 0", () => {
    usePageTabsStore.getState().setPages([makePage({ id: "a", name: "Stock1" })]);
    usePageTabsStore.getState().setOrphanCount(3);
    render(<PageTabs />);
    expect(screen.getByRole("tab", { name: /已停用/ })).toBeInTheDocument();
  });

  it("renders orphan tab even when no pages exist (orphan-only mode)", () => {
    usePageTabsStore.getState().setPages([]);
    usePageTabsStore.getState().setOrphanCount(7);
    render(<PageTabs />);
    expect(screen.getByRole("tab", { name: /已停用/ })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /已停用/ })).toHaveTextContent("7");
  });

  it("returns null when no pages AND no orphans", () => {
    usePageTabsStore.getState().setPages([]);
    usePageTabsStore.getState().setOrphanCount(0);
    const { container } = render(<PageTabs />);
    expect(container.firstChild).toBeNull();
  });
});
