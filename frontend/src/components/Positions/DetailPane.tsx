import { useEffect, useState, useCallback } from "react";
import { api } from "../../api/http";
import type { Position, TPair } from "../../api/domain-types";
import { useQuotesStore } from "../../stores/quotes";
import { useCandlesticksStore, candleCacheKey, type Period } from "../../stores/candlesticks";
import { useTradesStore } from "../../stores/trades";
import { usePairsStore } from "../../stores/pairs";
import { useDetailViewStore } from "../../stores/detailView";
import { DetailSummary } from "./DetailSummary";
import { DetailChart } from "./DetailChart";
import { PairDetailModal } from "./PairDetailModal";
import { PairKPIs } from "./PairKPIs";
import { TradeList } from "./TradeList";

const PERIODS: { id: Period; label: string }[] = [
  { id: "today", label: "日内" },
  { id: "5",     label: "5D" },
  { id: "7",     label: "7D" },
  { id: "15",    label: "15D" },
  { id: "30",    label: "30D" },
  { id: "60",    label: "60D" },
  { id: "90",    label: "90D" },
];

interface Props {
  position: Position;
  onBack(): void;
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
  const period = useDetailViewStore((s) => s.period);
  const setPeriod = useDetailViewStore((s) => s.setPeriod);
  const todayGranularity = useDetailViewStore((s) => s.todayGranularity);
  const setTodayGranularity = useDetailViewStore((s) => s.setTodayGranularity);
  const todaySessions = useDetailViewStore((s) => s.todaySessions);
  const setTodaySessions = useDetailViewStore((s) => s.setTodaySessions);
  const selectedBuys = useDetailViewStore((s) => s.selectedBuys);
  const selectedSells = useDetailViewStore((s) => s.selectedSells);
  const activePairId = useDetailViewStore((s) => s.activePairId);
  const setActivePair = useDetailViewStore((s) => s.setActivePair);
  const clearSelection = useDetailViewStore((s) => s.clearSelection);

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
  const barsKey = candleCacheKey(symbol, period, todayGranularity, todaySessions);
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
  // PairKPIs + the做T detail popup all read from one source. An account
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
    // For `today`, granularity + sessions affect both the request and the
    // cache key; for other periods these are ignored on both sides.
    const opts = period === "today"
      ? { granularity: todayGranularity, sessions: todaySessions }
      : {};
    const key = candleCacheKey(symbol, period, todayGranularity, todaySessions);
    api.candlesticks(symbol, period, opts)
      .then((r) => {
        if (!alive) return;
        setBars(key, r);
      })
      .catch((e) => console.warn("candlesticks fetch failed", e))
      .finally(() => {
        // Flip the gate AFTER setBars so a cached-bars hit doesn't
        // mount the chart with stale data then rebuild when the fresh
        // fetch lands. Single mount per period/granularity/session switch.
        if (alive) setFetchedBarsKey(key);
      });
    return () => { alive = false; };
  }, [symbol, period, todayGranularity, todaySessions, setBars]);

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
      setActivePair(pair.id);
      clearSelection();
    } catch (e) {
      console.error("createPair failed", e);
    }
  }, [ticker, symbol, selectedBuys, selectedSells, upsertPair, setActivePair, clearSelection]);

  const onExtendPair = useCallback(async (pairId: number) => {
    if (selectedBuys.size === 0 && selectedSells.size === 0) return;
    try {
      const pair: TPair = await api.extendPair(pairId, {
        buy_trade_ids: [...selectedBuys],
        sell_trade_ids: [...selectedSells],
      });
      upsertPair(ticker, pair);
      setActivePair(pair.id);
      clearSelection();
    } catch (e) {
      console.error("extendPair failed", e);
    }
  }, [ticker, selectedBuys, selectedSells, upsertPair, setActivePair, clearSelection]);

  // Avg-cost line is opt-in per the prototype review — it often draws the
  // user's eye to a flat horizontal that visually pins the chart.
  const [showAvgCost, setShowAvgCost] = useState(false);
  // Today's sub-config (粒度 + 时段) lives in a dropdown that opens when
  // the user clicks "日内" again after it's already active. Hidden by
  // default to keep the chart header clean.
  const [todayDropdownOpen, setTodayDropdownOpen] = useState(false);

  return (
    <div className="detail-pane">
      <button className="detail-back" onClick={onBack}>
        <span style={{ fontFamily: "var(--font-mono)" }}>←</span> 返回持仓总览
      </button>

      <DetailSummary position={position} quote={quote} />

      <div className="detail-chart-card">
        <div className="detail-chart-head">
          <div className="legend-row">
            <h4>价格 · {
              period === "today" ? (
                `今日 ${todayGranularity} · ${
                  todaySessions === "regular" ? "盘中"
                  : todaySessions === "pre" ? "盘前"
                  : todaySessions === "post" ? "盘后"
                  : todaySessions === "overnight" ? "夜盘"
                  : "全部"
                }`
              ) :
              period === "5" || period === "7" ? `近 ${period} 日 · 5 分钟` :
              period === "15" ? "近 15 日 · 15 分钟" :
              `近 ${period} 日 · 日K`
            }</h4>
            <div className="legend">
              <span className="it"><span className="glyph buy">▲</span>买入</span>
              <span className="it"><span className="glyph sell">▼</span>卖出</span>
              <button
                className={`toggle-mini ${showAvgCost ? "on" : ""}`}
                onClick={() => setShowAvgCost(!showAvgCost)}
                title="显示/隐藏成本均价参考线"
              >
                <span className="glyph avg" />成本{showAvgCost ? "" : " · 隐藏"}
              </button>
            </div>
          </div>
          <div className="period-tabs">
            {PERIODS.map((p) => {
              const isActive = period === p.id;
              // "日内" doubles as a dropdown trigger when it's already
              // active — clicking it again toggles the 粒度/时段 picker.
              // Other tabs are simple period switches.
              const isTodayActive = p.id === "today" && isActive;
              return (
                <button
                  key={p.id}
                  className={`p ${isActive ? "active" : ""}`}
                  onClick={() => {
                    if (p.id === "today" && isActive) {
                      setTodayDropdownOpen((v) => !v);
                    } else {
                      setPeriod(p.id);
                      if (p.id !== "today") setTodayDropdownOpen(false);
                    }
                  }}
                >
                  {p.label}{isTodayActive && <span className="caret">▾</span>}
                </button>
              );
            })}
          </div>
        </div>
        {period === "today" && todayDropdownOpen && (
          <div className="today-dropdown" role="menu">
            <div className="subopt-group">
              <span className="lbl">粒度</span>
              {(["分时", "1min", "2min", "3min", "5min"] as const).map((g) => (
                <button
                  key={g}
                  className={`pill ${todayGranularity === g ? "active" : ""}`}
                  onClick={() => setTodayGranularity(g)}
                >{g}</button>
              ))}
            </div>
            {/* 时段 selector only makes sense for 分时 (1-min line). For K-line
               granularities (2/3/5min) we always show regular session, so
               hide the row entirely to avoid an option with one choice. */}
            {todayGranularity === "分时" && (
              <div className="subopt-group">
                <span className="lbl">时段</span>
                <button
                  className={`pill ${todaySessions === "regular" ? "active" : ""}`}
                  onClick={() => setTodaySessions("regular")}
                >盘中</button>
                <button
                  className={`pill ${todaySessions === "pre" ? "active" : ""}`}
                  onClick={() => setTodaySessions("pre")}
                >盘前</button>
                <button
                  className={`pill ${todaySessions === "post" ? "active" : ""}`}
                  onClick={() => setTodaySessions("post")}
                >盘后</button>
                <button
                  className={`pill ${todaySessions === "overnight" ? "active" : ""}`}
                  onClick={() => setTodaySessions("overnight")}
                >夜盘</button>
                <button
                  className={`pill ${todaySessions === "all" ? "active" : ""}`}
                  onClick={() => setTodaySessions("all")}
                >全部</button>
              </div>
            )}
          </div>
        )}
        <div className="detail-chart-wrap">
          {/* Gate the chart on bars + initial trades + initial pairs +
             barsInitialized so it mounts exactly once on open AND on every
             period/granularity/session switch. Without the bars gate, a
             cached barsKey would mount the chart immediately and then
             rebuild when the refetch landed — visible as the same 240ms
             entry animation playing twice. */}
          {bars && bars.bars.length > 0 && tradesInitialized && pairsInitialized && barsInitialized ? (
            <DetailChart
              symbol={symbol}
              bars={bars.bars}
              period={period}
              trades={trades}
              avgCost={position.avg_cost}
              showAvgCost={showAvgCost}
              todayGranularity={todayGranularity}
              todaySessions={todaySessions}
            />
          ) : (
            <div className="empty-pat" style={{ height: "100%", display: "flex", alignItems: "center", justifyContent: "center" }}>
              {barsInitialized && bars && bars.bars.length === 0 ? "暂无 K 线数据" : "加载中..."}
            </div>
          )}
        </div>
      </div>

      {!isOption && <PairKPIs ticker={ticker} pairsCount={pairs.length} />}

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
          />
        );
      })()}
    </div>
  );
}
