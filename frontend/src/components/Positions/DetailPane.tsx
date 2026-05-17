import { useEffect, useRef, useState, useCallback } from "react";
import { api } from "../../api/http";
import type { Position, TPair, Trade } from "../../api/domain-types";
import { useQuotesStore } from "../../stores/quotes";
import { useCandlesticksStore, candleCacheKey } from "../../stores/candlesticks";
import { useTradesStore } from "../../stores/trades";
import { usePairsStore } from "../../stores/pairs";
import { useDetailViewStore } from "../../stores/detailView";
import { resolveViewConfig, type ViewType } from "./viewConfig";
import { TabPopover } from "./TabPopover";
import { DetailSummary } from "./DetailSummary";
import { DetailChart } from "./DetailChart";
import { PairDetailModal } from "./PairDetailModal";
import { TradeList, type TradeListFilter } from "./TradeList";
import { ConfirmModal } from "./ConfirmModal";

interface PendingConfirm {
  title: string;
  description: string;
  confirmLabel: string;
  danger?: boolean;
  onConfirm(): Promise<void> | void;
}

/** Return the subset of ``trades`` referenced by ``pair``'s allocations,
 *  each with ``t_pair_tags`` updated to reflect the pair's current
 *  state. The server denormalises pair allocations into
 *  ``broker_executions.t_pair_tags`` but does NOT re-send the affected
 *  trade rows on a create/extend response — patching locally is what
 *  makes the做T column chips appear immediately without a re-fetch.
 *
 *  Stale entries for ``pair.id`` are filtered out first so extending a
 *  pair on an already-bound trade doesn't accumulate duplicate tags. */
function patchTradesWithPair(trades: Trade[], pair: TPair): Trade[] {
  const allocByTradeId = new Map<string, number>();
  for (const a of pair.buys) allocByTradeId.set(a.trade_id, a.qty);
  for (const a of pair.sells) allocByTradeId.set(a.trade_id, a.qty);
  return trades
    .filter((t) => allocByTradeId.has(t.id))
    .map((t) => {
      const allocQty = allocByTradeId.get(t.id)!;
      const otherTags = (t.t_pair_tags ?? []).filter(([pid]) => pid !== pair.id);
      return {
        ...t,
        t_pair_tags: [...otherTags, [pair.id, allocQty] as [number, number]],
      };
    });
}

const TABS: Array<{ view: ViewType; label: string; hasPopover: boolean }> = [
  { view: "intraday", label: "日内",  hasPopover: true },
  { view: "minute",   label: "分钟",  hasPopover: true },
  { view: "multiday", label: "多日",  hasPopover: true },
  { view: "day",      label: "日K",   hasPopover: false },
  { view: "week",     label: "周K",   hasPopover: false },
  { view: "month",    label: "月K",   hasPopover: false },
  { view: "year",     label: "年K",   hasPopover: false },
];

interface Props {
  position: Position;
  onBack(): void;
}

interface HeadProps {
  view: ViewType;
  setView(v: ViewType): void;
  intradaySessions: import("./viewConfig").IntradaySession;
  setIntradaySessions(s: import("./viewConfig").IntradaySession): void;
  minuteGranularity: import("./viewConfig").MinuteGranularity;
  setMinuteGranularity(g: import("./viewConfig").MinuteGranularity): void;
  multidayWindow: import("./viewConfig").MultidayWindow;
  setMultidayWindow(w: import("./viewConfig").MultidayWindow): void;
  showAvgCost: boolean;
  setShowAvgCost(v: boolean): void;
}

function DetailChartHead(props: HeadProps) {
  const {
    view, setView,
    intradaySessions, setIntradaySessions,
    minuteGranularity, setMinuteGranularity,
    multidayWindow, setMultidayWindow,
    showAvgCost, setShowAvgCost,
  } = props;

  const containerRef = useRef<HTMLDivElement | null>(null);
  const intradayAnchor = useRef<HTMLButtonElement | null>(null);
  const minuteAnchor = useRef<HTMLButtonElement | null>(null);
  const multidayAnchor = useRef<HTMLButtonElement | null>(null);
  const [openPopover, setOpenPopover] = useState<null | "intraday" | "minute" | "multiday">(null);

  return (
    <div className="detail-chart-head" ref={containerRef}>
      <div className="legend-row">
        <h4>价格</h4>
        <div className="legend">
          <span className="it"><span className="glyph buy">B</span>买入</span>
          <span className="it"><span className="glyph sell">S</span>卖出</span>
          <span className="it"><span className="glyph t">T</span>做T</span>
          <button
            className={`toggle-mini ${showAvgCost ? "on" : ""}`}
            onClick={() => setShowAvgCost(!showAvgCost)}
            title="显示/隐藏成本均价参考线"
          >
            <span className="glyph avg" />成本{showAvgCost ? "" : " · 隐藏"}
          </button>
        </div>
      </div>
      <div className="chart-tabs">
        {TABS.map((t) => {
          const isActive = view === t.view;
          // Every popover-tab carries its own sub-value as a quiet suffix
          // so the user can see what each tab will switch to before clicking.
          const ownSub =
            t.view === "intraday" ? (
              intradaySessions === "regular" ? "盘中"
              : intradaySessions === "pre" ? "盘前"
              : intradaySessions === "post" ? "盘后"
              : intradaySessions === "overnight" ? "夜盘"
              : "全部"
            )
            : t.view === "minute" ? minuteGranularity
            : t.view === "multiday" ? `${multidayWindow}日`
            : null;
          const popoverOpen = openPopover === t.view;
          return (
            <button
              key={t.view}
              ref={
                t.view === "intraday" ? intradayAnchor
                : t.view === "minute" ? minuteAnchor
                : t.view === "multiday" ? multidayAnchor
                : undefined
              }
              className={`chart-tab ${isActive ? "active" : ""} ${popoverOpen ? "popover-open" : ""}`}
              onClick={() => {
                if (!isActive) {
                  setView(t.view);
                  setOpenPopover(null);
                  return;
                }
                if (t.hasPopover) {
                  setOpenPopover((cur) =>
                    cur === t.view ? null : (t.view as "intraday" | "minute" | "multiday"),
                  );
                } else {
                  setOpenPopover(null);
                }
              }}
            >
              <span>{t.label}</span>
              {ownSub && <span className="sub">{ownSub}</span>}
            </button>
          );
        })}
      </div>

      {/* 日内 popover — sessions */}
      <TabPopover
        open={openPopover === "intraday"}
        anchorRef={intradayAnchor}
        containerRef={containerRef}
        onClose={() => setOpenPopover(null)}
      >
        {(["regular", "pre", "post", "overnight", "all"] as const).map((s) => (
          <button
            key={s}
            className={`popover-pill ${intradaySessions === s ? "active" : ""}`}
            onClick={() => { setIntradaySessions(s); setOpenPopover(null); }}
          >
            {s === "regular" ? "盘中" : s === "pre" ? "盘前" : s === "post" ? "盘后" : s === "overnight" ? "夜盘" : "全部"}
          </button>
        ))}
      </TabPopover>

      {/* 分钟 popover — granularity */}
      <TabPopover
        open={openPopover === "minute"}
        anchorRef={minuteAnchor}
        containerRef={containerRef}
        onClose={() => setOpenPopover(null)}
      >
        {(["1min", "2min", "3min", "5min"] as const).map((g) => (
          <button
            key={g}
            className={`popover-pill ${minuteGranularity === g ? "active" : ""}`}
            onClick={() => { setMinuteGranularity(g); setOpenPopover(null); }}
          >{g}</button>
        ))}
      </TabPopover>

      {/* 多日 popover — window */}
      <TabPopover
        open={openPopover === "multiday"}
        anchorRef={multidayAnchor}
        containerRef={containerRef}
        onClose={() => setOpenPopover(null)}
      >
        {([5, 7] as const).map((w) => (
          <button
            key={w}
            className={`popover-pill ${multidayWindow === w ? "active" : ""}`}
            onClick={() => { setMultidayWindow(w); setOpenPopover(null); }}
          >{w}日</button>
        ))}
      </TabPopover>
    </div>
  );
}

/** Drilled-down view for a single position. Fetches trades + the requested
 *  period's candlesticks on mount / period change; mutations (create /
 *  extend / delete pair) hit the backend then refresh state.
 *
 *  Options (``position.type === "option"``) suppress做T pair UI — pairs
 *  don't apply to single contracts, and broker-side P/L for options is
 *  tracked at the contract level rather than via FIFO BUY/SELL matching.
 *  The trade list filters to the contract's symbol so adjacent option
 *  contracts on the same underlying don't bleed into the view.
 */
export function DetailPane({ position, onBack }: Props) {
  const ticker = position.ticker;
  const symbol = position.symbol;
  const isOption = position.type === "option";

  const quote = useQuotesStore((s) => s.quotesBySymbol[symbol]);
  const view = useDetailViewStore((s) => s.view);
  const setView = useDetailViewStore((s) => s.setView);
  const intradaySessions = useDetailViewStore((s) => s.intradaySessions);
  const setIntradaySessions = useDetailViewStore((s) => s.setIntradaySessions);
  const minuteGranularity = useDetailViewStore((s) => s.minuteGranularity);
  const setMinuteGranularity = useDetailViewStore((s) => s.setMinuteGranularity);
  const multidayWindow = useDetailViewStore((s) => s.multidayWindow);
  const setMultidayWindow = useDetailViewStore((s) => s.setMultidayWindow);
  const selectedBuys = useDetailViewStore((s) => s.selectedBuys);
  const selectedSells = useDetailViewStore((s) => s.selectedSells);
  const activePairId = useDetailViewStore((s) => s.activePairId);
  const setActivePair = useDetailViewStore((s) => s.setActivePair);
  const clearSelection = useDetailViewStore((s) => s.clearSelection);

  const viewCfg = resolveViewConfig(view, {
    intradaySessions, minuteGranularity, multidayWindow,
  });

  // For stocks: all trades on the underlying are pair-bindable.
  // For options: narrow to fills on THIS specific contract (same ticker
  // can have many distinct option symbols).
  const allTickerTrades = useTradesStore((s) => s.byTicker[ticker]) ?? [];
  const trades = isOption
    ? allTickerTrades.filter((t) => t.symbol === symbol)
    : allTickerTrades;
  const setTrades = useTradesStore((s) => s.setTrades);
  const appendTrades = useTradesStore((s) => s.appendTrades);
  const pairs = usePairsStore((s) => s.byTicker[ticker]) ?? [];
  const upsertPair = usePairsStore((s) => s.upsertPair);
  const setPairs = usePairsStore((s) => s.setPairs);
  const barsKey = candleCacheKey(symbol, viewCfg.period, viewCfg.granularity, viewCfg.sessions);
  const bars = useCandlesticksStore((s) => s.byKey[barsKey]);
  const setBars = useCandlesticksStore((s) => s.setBars);
  // Last bars cache key the period-fetch effect has fully resolved for.
  // Used to gate DetailChart mount on period/granularity/session switches
  // so a cached-bars instant-mount + subsequent refetch overwrite doesn't
  // produce a visible destroy+rebuild flicker. Derives ``barsInitialized``
  // from this against the current ``barsKey``.
  const [fetchedBarsKey, setFetchedBarsKey] = useState<string | null>(null);
  const barsInitialized = fetchedBarsKey === barsKey;

  // Track the latest broker→DB sync timestamp so the trade list can
  // surface "上次更新：xxx". null until the first incremental sync has
  // run on this detail-pane open.
  const [lastSyncedAt, setLastSyncedAt] = useState<string | null>(null);

  // Server-driven trade pagination: on open, request the first 2 view
  // pages worth (16 = 8/page × 2). When the user navigates to a page
  // whose first row isn't loaded yet, ``loadMoreTrades`` fetches the
  // next batch. Keeping every loaded row in the store preserves cross-
  // page做T binding (selectedBuys/Sells reference IDs that remain in
  // the store even after page navigation).
  const TRADES_PAGE_SIZE = 16;
  const [tradesTotal, setTradesTotal] = useState(0);
  const [tradesLoading, setTradesLoading] = useState(false);
  // True once the first executions fetch has settled. Gates DetailChart
  // mount so the chart isn't created with empty trades and then
  // immediately destroyed + rebuilt when trades arrive.
  const [tradesInitialized, setTradesInitialized] = useState(false);

  // 做T pair list UI was removed (#3), so the detail pane no longer
  // paginates pairs. Fetch once up to the backend's per-call max (500)
  // — the entire ticker's pairs land in the store so TradeList chips +
  // DetailSummary's做T row + the做T detail popup all read from one source.
  // An account
  // that accumulates >500 pairs for a single ticker is implausible.
  const PAIRS_PAGE_SIZE = 500;
  // Same idea as ``tradesInitialized``. For options we skip the pairs
  // fetch entirely, so the gate flips to true immediately in that branch.
  const [pairsInitialized, setPairsInitialized] = useState(false);

  // Fetch trades + pairs once per ticker, candlesticks per (ticker, period).
  //
  // Trade history comes from broker.history_executions via an
  // INCREMENTAL sync — the backend reads MAX(ts) for this account+ticker
  // and pulls only the gap from LongBridge. First-ever open falls back
  // to a 90-day window. Manual fills placed via the LongBridge app / web
  // are included.
  useEffect(() => {
    let alive = true;
    // Reset gates on ticker swap so the chart waits for the NEW ticker's
    // initial fetches before mounting (otherwise a fast re-open would
    // mount the chart against stale store contents from the previous
    // ticker for a frame).
    setTradesInitialized(false);
    setPairsInitialized(false);
    api.executions(ticker, { offset: 0, limit: TRADES_PAGE_SIZE })
      .then((r) => {
        if (!alive) return;
        const trades = r.executions.map((e) => ({
          id: e.order_id,
          ticker: e.ticker,
          symbol: e.symbol,
          side: e.side,
          qty: e.qty,
          price: e.price,
          ts: e.ts,
          source: null,
          tag: null,
          t_pair_tags: (e as { t_pair_tags?: [number, number][] }).t_pair_tags ?? [],
        }));
        // setTrades replaces — re-opening the same ticker (or switching
        // back from another) starts from a clean slate so stale rows
        // from a prior account don't leak.
        setTrades(ticker, trades);
        setTradesTotal(r.total_count);
        setLastSyncedAt(r.last_synced_at ?? null);
      })
      .catch((e) => console.warn("executions fetch failed", e))
      .finally(() => {
        if (!alive) return;
        setTradesInitialized(true);
      });
    // 做T pairs are stock-only — skip the fetch entirely on option detail
    // panes so we don't waste a round-trip (and don't paint zero-pair
    // affordances that aren't even rendered for options).
    if (!isOption) {
      api.listPairs(ticker, { offset: 0, limit: PAIRS_PAGE_SIZE })
        .then((r) => {
          if (!alive) return;
          setPairs(ticker, r.pairs);
        })
        .catch((e) => console.warn("pairs fetch failed", e))
        .finally(() => {
          if (!alive) return;
          setPairsInitialized(true);
        });
    } else {
      // No pairs fetch for options — flip the gate immediately so the
      // chart doesn't wait on a request that will never fire.
      setPairsInitialized(true);
    }
    return () => { alive = false; };
  }, [ticker, setTrades, setPairs, isOption]);

  const loadMoreTrades = useCallback(async () => {
    if (tradesLoading) return;
    const loaded = useTradesStore.getState().byTicker[ticker]?.length ?? 0;
    if (loaded >= tradesTotal && tradesTotal > 0) return;
    setTradesLoading(true);
    try {
      const r = await api.executions(ticker, {
        offset: loaded,
        limit: TRADES_PAGE_SIZE,
      });
      const newTrades = r.executions.map((e) => ({
        id: e.order_id,
        ticker: e.ticker,
        symbol: e.symbol,
        side: e.side,
        qty: e.qty,
        price: e.price,
        ts: e.ts,
        source: null,
        tag: null,
        t_pair_tags: (e as { t_pair_tags?: [number, number][] }).t_pair_tags ?? [],
      }));
      appendTrades(ticker, newTrades);
      setTradesTotal(r.total_count);
      if (r.last_synced_at) setLastSyncedAt(r.last_synced_at);
    } catch (e) {
      console.warn("loadMoreTrades failed", e);
    } finally {
      setTradesLoading(false);
    }
  }, [ticker, tradesLoading, tradesTotal, appendTrades]);

  useEffect(() => {
    let alive = true;
    const opts = viewCfg.period === "today"
      ? { granularity: viewCfg.granularity, sessions: viewCfg.sessions }
      : {};
    const key = candleCacheKey(symbol, viewCfg.period, viewCfg.granularity, viewCfg.sessions);
    api.candlesticks(symbol, viewCfg.period, opts)
      .then((r) => {
        if (!alive) return;
        setBars(key, r);
      })
      .catch((e) => console.warn("candlesticks fetch failed", e))
      .finally(() => {
        if (alive) setFetchedBarsKey(key);
      });
    return () => { alive = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [symbol, view, intradaySessions, minuteGranularity, multidayWindow, setBars]);

  const onConfirmBind = useCallback(async () => {
    if (selectedBuys.size === 0 && selectedSells.size === 0) return;
    try {
      const pair: TPair = await api.createPair({
        ticker,
        symbol,
        buy_trade_ids: [...selectedBuys],
        sell_trade_ids: [...selectedSells],
      });
      upsertPair(ticker, pair);
      // Patch the affected trades' t_pair_tags locally so the做T column
      // chips render immediately. Reads via ``getState()`` to bypass the
      // stale-closure trap on subscribed values inside useCallback.
      const currentTrades = useTradesStore.getState().byTicker[ticker] ?? [];
      appendTrades(ticker, patchTradesWithPair(currentTrades, pair));
      clearSelection();
      // Intentionally NOT calling setActivePair(pair.id) — auto-opening
      // the PairDetailModal right after creation was confusing because
      // the trade list already shows the new chips. The user can click
      // a chip when they want the detail popup.
    } catch (e) {
      console.error("createPair failed", e);
    }
  }, [ticker, symbol, selectedBuys, selectedSells, upsertPair, appendTrades, clearSelection]);

  const onExtendPair = useCallback(async (pairId: number) => {
    if (selectedBuys.size === 0 && selectedSells.size === 0) return;
    try {
      const pair: TPair = await api.extendPair(pairId, {
        buy_trade_ids: [...selectedBuys],
        sell_trade_ids: [...selectedSells],
      });
      upsertPair(ticker, pair);
      const currentTrades = useTradesStore.getState().byTicker[ticker] ?? [];
      appendTrades(ticker, patchTradesWithPair(currentTrades, pair));
      clearSelection();
      // Same reasoning as onConfirmBind — don't auto-open the modal.
    } catch (e) {
      console.error("extendPair failed", e);
    }
  }, [ticker, selectedBuys, selectedSells, upsertPair, appendTrades, clearSelection]);

  // Trade-list settings-menu state. Ephemeral by intent: leaving and
  // re-entering the detail pane resets to "all" (the user explicitly
  // asked for "退出重进刷新过滤状态").
  const [tradeFilter, setTradeFilter] = useState<TradeListFilter>("all");

  // In-panel confirm dialog state. ``null`` = no dialog shown. Each
  // destructive trade-menu action builds a PendingConfirm and the
  // ConfirmModal renders it inside the detail-pane (NOT the viewport).
  const [pendingConfirm, setPendingConfirm] = useState<PendingConfirm | null>(null);

  const onClearAllPairs = useCallback(() => {
    setPendingConfirm({
      title: `清除 ${ticker} 的所有做T 绑定`,
      description: `此操作不可恢复 —— 该股票下所有做T 配对会被删除，对应的交易记录"做T"列会清空。`,
      confirmLabel: "确认清除",
      danger: true,
      onConfirm: async () => {
        try {
          await api.deletePairsByTicker(ticker);
          setPairs(ticker, []);
          setActivePair(null);
          // Strip pair tags from any trade that previously carried them
          // so the chip column flips empty without a re-fetch.
          const currentTrades = useTradesStore.getState().byTicker[ticker] ?? [];
          const cleared = currentTrades
            .filter((t) => (t.t_pair_tags ?? []).length > 0)
            .map((t) => ({ ...t, t_pair_tags: [] as [number, number][] }));
          if (cleared.length > 0) appendTrades(ticker, cleared);
        } catch (e) {
          console.error("clearAllPairs failed", e);
        }
      },
    });
  }, [ticker, setPairs, setActivePair, appendTrades]);

  const onClearAllTrades = useCallback(() => {
    setPendingConfirm({
      title: `清空 ${ticker} 的所有交易记录`,
      description: `此操作不可恢复 —— 该股票下所有 broker 成交记录会从本地清空（broker 端的数据不受影响）。需要重新查看时可走"重新拉取"。`,
      confirmLabel: "确认清空",
      danger: true,
      onConfirm: async () => {
        try {
          await api.deleteBrokerExecutions(ticker);
          setTrades(ticker, []);
          setTradesTotal(0);
          setLastSyncedAt(null);
        } catch (e) {
          console.error("clearAllTrades failed", e);
        }
      },
    });
  }, [ticker, setTrades]);

  const onUnbindPair = useCallback((pairId: number) => {
    setPendingConfirm({
      title: `解绑 T-${pairId} 配对`,
      description: `该配对会被删除，关联的交易回到"未做T"状态，可重新参与其他做T 绑定。`,
      confirmLabel: "解绑",
      danger: true,
      onConfirm: async () => {
        try {
          await api.deletePair(pairId);
          // Drop the pair from the local store.
          const livePairs = usePairsStore.getState().byTicker[ticker] ?? [];
          setPairs(ticker, livePairs.filter((p) => p.id !== pairId));
          // Strip [pairId, *] from any trade tags so the做T chip column
          // updates immediately without a re-fetch.
          const currentTrades = useTradesStore.getState().byTicker[ticker] ?? [];
          const cleared = currentTrades
            .filter((t) => (t.t_pair_tags ?? []).some(([pid]) => pid === pairId))
            .map((t) => ({
              ...t,
              t_pair_tags: (t.t_pair_tags ?? []).filter(([pid]) => pid !== pairId),
            }));
          if (cleared.length > 0) appendTrades(ticker, cleared);
          // Close the pair-detail modal by clearing activePairId.
          setActivePair(null);
        } catch (e) {
          console.error("unbindPair failed", e);
        }
      },
    });
  }, [ticker, setPairs, appendTrades, setActivePair]);

  const onRefetchTrades = useCallback(() => {
    setPendingConfirm({
      title: `重新拉取 ${ticker} 近 2 年交易记录`,
      description: `现有本地缓存会先清空，再从 broker 重新分块回填（最多 8 次调用）。期间界面短暂显示"加载中…"。`,
      confirmLabel: "重新拉取",
      onConfirm: async () => {
        try {
          setTradesInitialized(false);
          await api.deleteBrokerExecutions(ticker);
          // history_synced is now false on the server, so this GET
          // triggers the full chunked 2-year backfill.
          const r = await api.executions(ticker, { offset: 0, limit: TRADES_PAGE_SIZE });
          const trades = r.executions.map((e) => ({
            id: e.order_id,
            ticker: e.ticker,
            symbol: e.symbol,
            side: e.side,
            qty: e.qty,
            price: e.price,
            ts: e.ts,
            source: null,
            tag: null,
            t_pair_tags: (e as { t_pair_tags?: [number, number][] }).t_pair_tags ?? [],
          }));
          setTrades(ticker, trades);
          setTradesTotal(r.total_count);
          setLastSyncedAt(r.last_synced_at ?? null);
        } catch (e) {
          console.error("refetchTrades failed", e);
        } finally {
          setTradesInitialized(true);
        }
      },
    });
  }, [ticker, setTrades]);

  // Avg-cost line is opt-in per the prototype review — it often draws the
  // user's eye to a flat horizontal that visually pins the chart.
  const [showAvgCost, setShowAvgCost] = useState(false);

  return (
    <div className="detail-pane">
      <DetailSummary
        position={position}
        quote={quote}
        pairsCount={pairs.length}
        onBack={onBack}
      />

      <div className="detail-chart-card">
        <DetailChartHead
          view={view}
          setView={setView}
          intradaySessions={intradaySessions}
          setIntradaySessions={setIntradaySessions}
          minuteGranularity={minuteGranularity}
          setMinuteGranularity={setMinuteGranularity}
          multidayWindow={multidayWindow}
          setMultidayWindow={setMultidayWindow}
          showAvgCost={showAvgCost}
          setShowAvgCost={setShowAvgCost}
        />
        <div className="detail-chart-wrap">
          {bars && bars.bars.length > 0 && tradesInitialized && pairsInitialized && barsInitialized ? (
            <DetailChart
              symbol={symbol}
              bars={bars.bars}
              view={view}
              viewCfg={viewCfg}
              trades={trades}
              avgCost={position.avg_cost}
              showAvgCost={showAvgCost}
            />
          ) : (
            <div className="empty-pat" style={{ height: "100%", display: "flex", alignItems: "center", justifyContent: "center" }}>
              {barsInitialized && bars && bars.bars.length === 0 ? "暂无 K 线数据" : "加载中..."}
            </div>
          )}
        </div>
      </div>

      <TradeList
        trades={trades}
        pairs={isOption ? [] : pairs}
        ticker={ticker}
        lastSyncedAt={lastSyncedAt}
        disableBinding={isOption}
        totalCount={tradesTotal}
        loading={tradesLoading}
        onRequestMore={loadMoreTrades}
        onConfirmBind={onConfirmBind}
        onExtendPair={onExtendPair}
        filter={tradeFilter}
        onFilterChange={setTradeFilter}
        onClearAllPairs={onClearAllPairs}
        onRefetchTrades={onRefetchTrades}
        onClearAllTrades={onClearAllTrades}
      />

      {/* Clicking a T-N chip on a trade row sets activePairId in the
         store; we render the modal whenever a known pair is selected.
         For options we never set activePairId, so the modal stays hidden.
         Closing the modal clears activePairId. */}
      {(() => {
        if (activePairId == null || isOption) return null;
        const pair = pairs.find((p) => p.id === activePairId);
        if (!pair) return null;
        return (
          <PairDetailModal
            pair={pair}
            trades={trades}
            allPairs={pairs}
            onClose={() => setActivePair(null)}
            onUnbind={onUnbindPair}
          />
        );
      })()}

      {/* Panel-scoped confirm dialog for destructive trade-menu actions.
         Anchors inside ``.detail-pane`` (which is ``position: relative``)
         so the popover sits centered over the detail content rather
         than over the whole viewport. */}
      {pendingConfirm && (
        <ConfirmModal
          title={pendingConfirm.title}
          description={pendingConfirm.description}
          confirmLabel={pendingConfirm.confirmLabel}
          danger={pendingConfirm.danger}
          onCancel={() => setPendingConfirm(null)}
          onConfirm={async () => {
            const action = pendingConfirm.onConfirm;
            setPendingConfirm(null);
            await action();
          }}
        />
      )}
    </div>
  );
}
