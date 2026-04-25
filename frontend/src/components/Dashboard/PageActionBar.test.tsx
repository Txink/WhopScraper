import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { usePageTabsStore } from "../../stores/pageTabs";
import { PageActionBar } from "./PageActionBar";

const stockPage = {
  id: "a", url: "u", source: "stock" as const, name: "S", added_at: "2026-04-25T00:00:00Z",
  settings: { dedupe_processed_messages: true, price_deviation_tolerance: 1, tickers: {} },
  running: true, started_at: null, last_poll_at: null, messages_published: 0, last_error: null,
};

describe("<PageActionBar>", () => {
  beforeEach(() => { usePageTabsStore.getState().reset(); });

  it("disables restart/settings when orphan", () => {
    render(<PageActionBar page={null} onOpenSettings={vi.fn()} />);
    expect(screen.getByText(/重启/)).toBeDisabled();
    expect(screen.getByText(/设置/)).toBeDisabled();
  });

  it("toggle expand mode persists in store", () => {
    render(<PageActionBar page={stockPage} onOpenSettings={vi.fn()} />);
    fireEvent.click(screen.getByText("⤓ 全展开"));
    expect(usePageTabsStore.getState().expandModeByTab["a"]).toBe("all-open");
    fireEvent.click(screen.getByText("⤒ 全收缩"));
    expect(usePageTabsStore.getState().expandModeByTab["a"]).toBe("all-closed");
  });
});
