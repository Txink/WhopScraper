import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { TradeList } from "./TradeList";
import type { Trade, TPair } from "../../api/domain-types";

// jsdom doesn't implement Element.scrollTo — TradeList resets scroll
// position on ticker/filter change via scrollRef.current?.scrollTo(...).
if (!Element.prototype.scrollTo) {
  Element.prototype.scrollTo = function () {} as typeof Element.prototype.scrollTo;
}

const trades: Trade[] = [];
const pairs: TPair[] = [];

describe("TradeList — pull-recent menu item", () => {
  it("renders '拉取最新（近 1 周）' above '重新拉取（近 2 年）' and invokes onSyncRecentTrades", () => {
    const onSync = vi.fn();
    const onRefetch = vi.fn();

    render(
      <TradeList
        trades={trades}
        pairs={pairs}
        ticker="TSLA"
        onConfirmBind={vi.fn()}
        onExtendPair={vi.fn()}
        onSyncRecentTrades={onSync}
        onRefetchTrades={onRefetch}
      />,
    );

    // Open the gear menu.
    fireEvent.click(screen.getByLabelText("交易记录设置"));

    // Both items present; pull-recent placed above 2-year refetch.
    const sync = screen.getByText("拉取最新（近 1 周）");
    const refetch = screen.getByText("重新拉取（近 2 年）");
    expect(sync).toBeTruthy();
    expect(refetch).toBeTruthy();
    expect(sync.compareDocumentPosition(refetch) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();

    // Click → callback fires, no confirm modal involved.
    fireEvent.click(sync);
    expect(onSync).toHaveBeenCalledTimes(1);
    expect(onRefetch).not.toHaveBeenCalled();
  });
});
