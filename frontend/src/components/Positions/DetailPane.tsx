import { useEffect, useRef, useState, useCallback, useMemo } from "react";
import { api } from "../../api/http";
import type { Position, TPair, Trade } from "../../api/domain-types";
import { fmtBjHM, fmtBjDate } from "./timeFmt";
import { useQuotesStore } from "../../stores/quotes";
import { useCandlesticksStore, candleCacheKey } from "../../stores/candlesticks";
import { useTradesStore } from "../../stores/trades";
import { usePairsStore } from "../../stores/pairs";
import { useDetailViewStore } from "../../stores/detailView";
import { resolveViewConfig, type ViewType } from "./viewConfig";
import { TabPopover } from "./TabPopover";
import { CalendarPopover } from "./CalendarPopover";
import { DetailSummary } from "./DetailSummary";
import { DetailChart } from "./DetailChart";
import {
  DetailChartOverlay, OVERLAY_COLORS, useOverlayBars, overlayBarSlot,
} from "./DetailChartOverlay";
import { PairDetailModal } from "./PairDetailModal";
import { TradeList, type TradeListFilter } from "./TradeList";
import { ConfirmModal } from "./ConfirmModal";
import { FullOrderModal } from "./TradingPanel/FullOrderModal";
import { AlertModal } from "./AlertsPanel/AlertModal";
import { cancelOrder, submitOrder } from "../../api/orders";
import { alertsApi } from "../../api/alerts";
import { useOrdersStore } from "../../stores/orders";
import { useAlertsStore } from "../../stores/alerts";
import { notice } from "../../stores/notices";
import { NoticeStack } from "../Notice/NoticeStack";
import type { OrderOut, SubmitOrderRequest } from "../../api/orders";
import type { AlertCreate, AlertOut } from "../../api/alerts";
import { DetailTabSwipe, type TabDef } from "./DetailTabSwipe";
import { TradingPanel } from "./TradingPanel/TradingPanel";
import { AlertsPanel } from "./AlertsPanel/AlertsPanel";
import { findBarForTrade, buildDayBoundaries } from "./tradeToBar";

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

type AggMarker = { type: "B" | "S" | "T"; qty: number; price: number };

export type HoverInfo =
  | { kind: "line"; time: string; close: number; agg: AggMarker | null }
  | { kind: "candle"; time: string; open: number; close: number; high: number; low: number; agg: AggMarker | null }
  | null;

/** Visible chart tabs. The `dayK` tab is a tab-group: it represents
 *  whichever of day/week/month/year is currently set via its popover
 *  (1 / 7 / 30 / 365日). Other tabs map 1:1 onto a single ViewType. */
type TabId = "intraday" | "minute" | "multiday" | "overlay" | "dayK";
const TABS: Array<{ id: TabId; label: string }> = [
  { id: "intraday", label: "日内" },
  { id: "multiday", label: "多日" },
  { id: "overlay",  label: "多日重叠" },
  { id: "minute",   label: "分钟" },
  { id: "dayK",     label: "日K" },
];

const DAYK_OPTIONS: Array<{ days: 1 | 7 | 30 | 365; view: import("./viewConfig").DayKGranularity }> = [
  { days: 1,   view: "day" },
  { days: 7,   view: "week" },
  { days: 30,  view: "month" },
  { days: 365, view: "year" },
];

function tabIdForView(view: ViewType): TabId {
  if (view === "day" || view === "week" || view === "month" || view === "year") return "dayK";
  return view;
}

function dayKDaysLabel(g: import("./viewConfig").DayKGranularity): string {
  return DAYK_OPTIONS.find((o) => o.view === g)?.days.toString() + "日";
}

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
  dayKGranularity: import("./viewConfig").DayKGranularity;
  setDayKGranularity(g: import("./viewConfig").DayKGranularity): void;
  overlayDates: string[];
  toggleOverlayDate(date: string): void;
  /** Map of ET trading-day → last close (latest bar's close on that
   *  date). null when bars haven't arrived yet so the legend can show
   *  a placeholder instead of a stale number. */
  overlayCloseByDate: Record<string, number | null>;
  hoverInfo: HoverInfo;
}

function DetailChartHead(props: HeadProps) {
  const {
    view, setView,
    intradaySessions, setIntradaySessions,
    minuteGranularity, setMinuteGranularity,
    multidayWindow, setMultidayWindow,
    dayKGranularity, setDayKGranularity,
    overlayDates, toggleOverlayDate, overlayCloseByDate,
    hoverInfo,
  } = props;

  const containerRef = useRef<HTMLDivElement | null>(null);
  const intradayAnchor = useRef<HTMLButtonElement | null>(null);
  const minuteAnchor = useRef<HTMLButtonElement | null>(null);
  const multidayAnchor = useRef<HTMLButtonElement | null>(null);
  const overlayAnchor = useRef<HTMLButtonElement | null>(null);
  const dayKAnchor = useRef<HTMLButtonElement | null>(null);
  const [openPopover, setOpenPopover] = useState<TabId | null>(null);

  const activeTab = tabIdForView(view);

  return (
    <div className="detail-chart-head" ref={containerRef}>
      <div className="chart-tabs">
        {TABS.map((t) => {
          const isActive = activeTab === t.id;
          // Every popover-tab carries its own sub-value as a quiet suffix
          // so the user can see what each tab will switch to before clicking.
          const ownSub =
            t.id === "intraday" ? (
              intradaySessions === "regular" ? "盘中"
              : intradaySessions === "pre" ? "盘前"
              : intradaySessions === "post" ? "盘后"
              : intradaySessions === "overnight" ? "夜盘"
              : "全部"
            )
            : t.id === "minute" ? minuteGranularity
            : t.id === "multiday" ? `${multidayWindow}日`
            : t.id === "overlay" ? (overlayDates.length > 0 ? `${overlayDates.length}日` : "选择")
            : t.id === "dayK" ? dayKDaysLabel(dayKGranularity)
            : null;
          const popoverOpen = openPopover === t.id;
          const anchor =
            t.id === "intraday" ? intradayAnchor
            : t.id === "minute" ? minuteAnchor
            : t.id === "multiday" ? multidayAnchor
            : t.id === "overlay" ? overlayAnchor
            : t.id === "dayK" ? dayKAnchor
            : undefined;
          return (
            <button
              key={t.id}
              ref={anchor}
              className={`chart-tab ${isActive ? "active" : ""} ${popoverOpen ? "popover-open" : ""}`}
              onClick={() => {
                if (!isActive) {
                  // dayK tab maps to whichever sub-view the user last picked.
                  const targetView: ViewType =
                    t.id === "dayK" ? dayKGranularity : t.id;
                  setView(targetView);
                  setOpenPopover(null);
                  return;
                }
                setOpenPopover((cur) => (cur === t.id ? null : t.id));
              }}
            >
              <span>{t.label}</span>
              {ownSub && <span className="sub">{ownSub}</span>}
            </button>
          );
        })}
      </div>

      {/* Overlay tab swaps the hover-info readout for a date↔color
          legend. The legend lives outside .chart-hover-info so it can
          pin to the card's top-right edge directly and wrap its own
          items into a second line without dragging the tabs row down. */}
      {view === "overlay" ? (
        overlayDates.length > 0 && (
          <div className="overlay-legend">
            {overlayDates.map((d, i) => {
              // YYYY-MM-DD → MM-DD (year omitted; legend is always for
              // the current viewing context, so the year adds no info).
              const shortDate = d.slice(5);
              const close = overlayCloseByDate[d];
              return (
                <span key={d} className="overlay-legend-item">
                  <span
                    className="overlay-legend-swatch"
                    style={{ background: OVERLAY_COLORS[i % OVERLAY_COLORS.length] }}
                    aria-hidden
                  />
                  <span className="overlay-legend-date">{shortDate}</span>
                  <span className="overlay-legend-price">
                    {close == null ? "—" : `$${close.toFixed(2)}`}
                  </span>
                </span>
              );
            })}
          </div>
        )
      ) : (
        <div className="chart-hover-info">
          {hoverInfo && (
            <>
              <div className="hover-row-1">
                <span className="time">{hoverInfo.time}</span>
                {hoverInfo.kind === "candle" ? (
                  <>
                    <span className="ohlc-item">开 <b>${hoverInfo.open.toFixed(3)}</b></span>
                    <span className="ohlc-item">收 <b>${hoverInfo.close.toFixed(3)}</b></span>
                    <span className="ohlc-item">高 <b>${hoverInfo.high.toFixed(3)}</b></span>
                    <span className="ohlc-item">低 <b>${hoverInfo.low.toFixed(3)}</b></span>
                  </>
                ) : (
                  <span className="price">${hoverInfo.close.toFixed(3)}</span>
                )}
              </div>
              {hoverInfo.agg && (
                <div className={`hover-row-2 agg-${hoverInfo.agg.type.toLowerCase()}`}>
                  {hoverInfo.agg.type === "B" ? "买入" : hoverInfo.agg.type === "S" ? "卖出" : "做T"}
                  {" "}
                  {hoverInfo.agg.qty.toLocaleString("en-US")} 股 @ ${hoverInfo.agg.price.toFixed(3)}
                </div>
              )}
            </>
          )}
        </div>
      )}

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

      {/* 多日重叠 popover — calendar. Toggling a date adds/removes it
          from overlayDates; the chart subscribes via the store. */}
      <CalendarPopover
        open={openPopover === "overlay"}
        anchorRef={overlayAnchor}
        containerRef={containerRef}
        selectedDates={overlayDates}
        max={5}
        slotColors={OVERLAY_COLORS as readonly string[] as string[]}
        onToggle={toggleOverlayDate}
        onClose={() => setOpenPopover(null)}
      />

      {/* 日K popover — collapses day/week/month/year into one tab; each
          option remembers itself in dayKGranularity and immediately
          switches the chart view to its bar size. */}
      <TabPopover
        open={openPopover === "dayK"}
        anchorRef={dayKAnchor}
        containerRef={containerRef}
        onClose={() => setOpenPopover(null)}
      >
        {DAYK_OPTIONS.map((o) => (
          <button
            key={o.view}
            className={`popover-pill ${dayKGranularity === o.view ? "active" : ""}`}
            onClick={() => {
              setDayKGranularity(o.view);
              setView(o.view);
              setOpenPopover(null);
            }}
          >{o.days}日</button>
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

  const [hoverBarIndex, setHoverBarIndex] = useState<number | null>(null);

  const quote = useQuotesStore((s) => s.quotesBySymbol[symbol]);
  const view = useDetailViewStore((s) => s.view);
  const setView = useDetailViewStore((s) => s.setView);
  const intradaySessions = useDetailViewStore((s) => s.intradaySessions);
  const setIntradaySessions = useDetailViewStore((s) => s.setIntradaySessions);
  const minuteGranularity = useDetailViewStore((s) => s.minuteGranularity);
  const setMinuteGranularity = useDetailViewStore((s) => s.setMinuteGranularity);
  const multidayWindow = useDetailViewStore((s) => s.multidayWindow);
  const setMultidayWindow = useDetailViewStore((s) => s.setMultidayWindow);
  const dayKGranularity = useDetailViewStore((s) => s.dayKGranularity);
  const setDayKGranularity = useDetailViewStore((s) => s.setDayKGranularity);
  const overlayDates = useDetailViewStore((s) => s.overlayDates);
  const toggleOverlayDate = useDetailViewStore((s) => s.toggleOverlayDate);
  const tabIndex = useDetailViewStore((s) => s.tabIndex);
  const setTabIndex = useDetailViewStore((s) => s.setTabIndex);
  // Shared between the head's legend (date + price) and the overlay
  // chart so both render off the same cached fetch.
  const overlayBars = useOverlayBars(symbol, overlayDates);
  // Slot index (0…959 minutes from 04:00 ET) the cursor is currently
  // on inside the overlay chart, or null when not hovering. Drives the
  // legend's per-day price column so the numbers track the cursor.
  const [overlayHoverSlot, setOverlayHoverSlot] = useState<number | null>(null);
  const overlayCloseByDate = useMemo<Record<string, number | null>>(() => {
    const out: Record<string, number | null> = {};
    for (const d of overlayDates) {
      const dayBars = overlayBars.barsByDate[d] ?? [];
      if (dayBars.length === 0) { out[d] = null; continue; }
      if (overlayHoverSlot != null) {
        // Hovering — find the bar at the cursor's slot. Missing slot =
        // gap in that day's line, render "—" rather than a stale price.
        let match: number | null = null;
        for (const b of dayBars) {
          if (!b.timestamp) continue;
          if (overlayBarSlot(b.timestamp) === overlayHoverSlot) {
            match = b.close;
            break;
          }
        }
        out[d] = match;
      } else {
        // Idle state — show the day's last close.
        const last = dayBars[dayBars.length - 1]!;
        out[d] = last.close;
      }
    }
    return out;
  }, [overlayDates, overlayBars.barsByDate, overlayHoverSlot]);
  const selectedBuys = useDetailViewStore((s) => s.selectedBuys);
  const selectedSells = useDetailViewStore((s) => s.selectedSells);
  const activePairId = useDetailViewStore((s) => s.activePairId);
  const setActivePair = useDetailViewStore((s) => s.setActivePair);
  const clearSelection = useDetailViewStore((s) => s.clearSelection);

  const viewCfg = resolveViewConfig(view, {
    intradaySessions, minuteGranularity, multidayWindow, dayKGranularity,
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
  const prependBars = useCandlesticksStore((s) => s.prependBars);
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

  // Server-driven trade pagination: initial fetch pulls a wide batch
  // (TRADES_INITIAL_LIMIT, matching the backend's per-call max) so the
  // chart can anchor B/S bubbles to every fill in the visible window,
  // not just the most-recent 16. Subsequent navigation past that batch
  // falls back to ``TRADES_PAGE_SIZE``-sized chunks via ``loadMoreTrades``.
  // Keeping every loaded row in the store preserves cross-page做T binding
  // (selectedBuys/Sells reference IDs that remain in the store even after
  // page navigation).
  const TRADES_INITIAL_LIMIT = 500;
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
    api.executions(ticker, { offset: 0, limit: TRADES_INITIAL_LIMIT })
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
    // The overlay view drives its own per-day fetches inside
    // DetailChartOverlay; skip the single-bars-array pull so we don't
    // race or churn DetailPane's gate state.
    if (view === "overlay") return;
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

  // Pan-back history extension. Only meaningful for K-line views — the
  // today period returns a single trading day so panning further back
  // would need a different data contract; the backend rejects `before`
  // for today. ``loadingRef`` dedupes concurrent fetches; ``exhaustedRef``
  // freezes after the server returns zero new bars so we don't poll the
  // same prefix forever.
  const loadOlderRef = useRef<{ inFlight: boolean; exhaustedKey: string | null }>({
    inFlight: false,
    exhaustedKey: null,
  });
  const handleNeedOlder = useCallback(() => {
    if (viewCfg.period === "today") return;
    const state = loadOlderRef.current;
    if (state.inFlight) return;
    if (state.exhaustedKey === barsKey) return;
    const current = useCandlesticksStore.getState().byKey[barsKey];
    const oldestTs = current?.bars[0]?.timestamp;
    if (!oldestTs) return;
    state.inFlight = true;
    api.candlesticks(symbol, viewCfg.period, { before: oldestTs })
      .then((r) => {
        if (r.bars.length === 0) {
          state.exhaustedKey = barsKey;
          return;
        }
        prependBars(barsKey, r);
      })
      .catch((e) => console.warn("candlesticks pan-back fetch failed", e))
      .finally(() => {
        state.inFlight = false;
      });
  }, [symbol, viewCfg.period, barsKey, prependBars]);

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

  // Trading-panel modals hosted here (NOT inside TradingPanel itself)
  // so they render at the .detail-pane level and escape the swipe-track
  // transform that would otherwise mis-position absolute/fixed children.
  const [tradingCancel, setTradingCancel] = useState<OrderOut | null>(null);
  const [tradingMoreFor, setTradingMoreFor] = useState<{
    symbol: string; ticker: string; lastDone: number | null;
  } | null>(null);

  const onTradingCancelConfirm = useCallback(async () => {
    if (!tradingCancel) return;
    try {
      await cancelOrder(tradingCancel.order_id);
      useOrdersStore.getState().removeOrder(tradingCancel.ticker, tradingCancel.order_id);
      notice.success("已撤单", "detail");
    } catch (e) {
      console.error("cancel failed", e);
      notice.error(`撤单失败：${e instanceof Error ? e.message : String(e)}`, "detail");
    } finally {
      setTradingCancel(null);
    }
  }, [tradingCancel]);

  const onTradingMoreSubmit = useCallback(async (req: SubmitOrderRequest) => {
    try {
      const o = await submitOrder(req);
      useOrdersStore.getState().upsertOrder(o.ticker, o);
      notice.success(`已提交 ${req.side} ${req.qty} ${req.symbol}`, "detail");
    } catch (e) {
      console.error("submit failed", e);
      notice.error(`下单失败：${e instanceof Error ? e.message : String(e)}`, "detail");
    } finally {
      setTradingMoreFor(null);
    }
  }, []);

  // Alerts-panel modals hosted at detail-pane level (same reason as
  // trading modals above — avoids the swipe-track transform).
  // ``alertModalFor`` is "new" for a fresh alert, an AlertOut for edit,
  // and null when closed.
  const [alertModalFor, setAlertModalFor] = useState<"new" | AlertOut | null>(null);
  const [alertDeleteConfirm, setAlertDeleteConfirm] = useState<AlertOut | null>(null);

  const onAlertCreateOrUpdate = useCallback(async (req: AlertCreate) => {
    try {
      const a = await alertsApi.create(req);
      useAlertsStore.getState().upsertAlert(a);
      notice.success("告警已保存", "detail");
    } catch (e) {
      console.error("create alert failed", e);
      notice.error(`告警保存失败：${e instanceof Error ? e.message : String(e)}`, "detail");
    } finally {
      setAlertModalFor(null);
    }
  }, []);

  const onAlertDeleteConfirm = useCallback(async () => {
    if (!alertDeleteConfirm) return;
    try {
      await alertsApi.remove(alertDeleteConfirm.id);
      useAlertsStore.getState().removeAlert(alertDeleteConfirm.id);
      notice.success("告警已删除", "detail");
    } catch (e) {
      console.error("delete alert failed", e);
      notice.error(`告警删除失败：${e instanceof Error ? e.message : String(e)}`, "detail");
    } finally {
      setAlertDeleteConfirm(null);
    }
  }, [alertDeleteConfirm]);

  const fmtAlertCond = (a: AlertOut): string => {
    const op = a.operator === ">=" ? "≥" : "≤";
    if (a.condition_type === "price") return `价格 ${op} $${a.threshold.toFixed(2)}`;
    if (a.condition_type === "pct_change") {
      const base = a.pct_change_baseline === "today_open" ? "今开" : "昨收";
      return `${a.threshold > 0 ? "涨幅" : "跌幅"} ${op} ${Math.abs(a.threshold).toFixed(2)}% vs ${base}`;
    }
    return `${a.volume_window ?? "1min"} 成交量 ${op} ${a.threshold.toLocaleString("en-US")} 股`;
  };

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

  const onUnbindPair = useCallback(async (pairId: number) => {
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
  }, [ticker, setPairs, appendTrades, setActivePair]);

  const onSyncRecentTrades = useCallback(async () => {
    try {
      setTradesInitialized(false);
      await api.syncExecutions(ticker, 7);
      const r = await api.executions(ticker, {
        offset: 0,
        limit: TRADES_INITIAL_LIMIT,
      });
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
        t_pair_tags:
          (e as { t_pair_tags?: [number, number][] }).t_pair_tags ?? [],
      }));
      setTrades(ticker, trades);
      setTradesTotal(r.total_count);
      setLastSyncedAt(r.last_synced_at ?? null);
    } catch (e) {
      console.error("syncRecentTrades failed", e);
    } finally {
      setTradesInitialized(true);
    }
  }, [ticker, setTrades]);

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
          const r = await api.executions(ticker, { offset: 0, limit: TRADES_INITIAL_LIMIT });
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

  const hoverInfo: HoverInfo = useMemo(() => {
    if (hoverBarIndex == null) return null;
    if (!bars || bars.bars.length === 0) return null;
    const bar = bars.bars[hoverBarIndex];
    if (!bar) return null;

    // Mirror the marker-anchoring logic so the hover row only lights up
    // on the same bar a trade's bubble was drawn (including pre-/post-
    // market snaps to the same ET calendar day's open or close).
    const isLineView =
      view === "intraday" || view === "minute" || view === "multiday";
    const periodMs = (viewCfg.liveCfg?.periodMinutes ?? 0) * 60 * 1000;
    const barTsAll = bars.bars.map((b) => b.timestamp ? Date.parse(b.timestamp) : 0);
    const dayBoundaries = isLineView ? buildDayBoundaries(barTsAll) : undefined;
    let buyQty = 0, buyValue = 0, sellQty = 0, sellValue = 0;
    for (const t of trades) {
      const tts = Date.parse(t.ts);
      const idx = findBarForTrade(barTsAll, tts, periodMs, isLineView, dayBoundaries);
      if (idx !== hoverBarIndex) continue;
      if (t.side === "BUY") { buyQty += t.qty; buyValue += t.qty * t.price; }
      else { sellQty += t.qty; sellValue += t.qty * t.price; }
    }
    const totalQty = buyQty + sellQty;
    let agg: AggMarker | null = null;
    if (totalQty > 0) {
      const type = buyQty > 0 && sellQty > 0 ? "T" : buyQty > 0 ? "B" : "S";
      agg = {
        type, qty: totalQty,
        price: (buyValue + sellValue) / totalQty,
      };
    }
    // Hover time field mirrors the chart's x-axis label for that view:
    // intraday/minute = "HH:MM" (single trading day), multiday =
    // "MM/DD HH:MM" (5-min bars across days), K-line views = "MM/DD".
    const ts = bar.timestamp ?? "";
    const timeFormatted =
      view === "intraday" || view === "minute"
        ? fmtBjHM(ts)
        : view === "multiday"
          ? `${fmtBjDate(ts)} ${fmtBjHM(ts)}`
          : fmtBjDate(ts);
    if (viewCfg.datasetType === "candlestick") {
      return {
        kind: "candle",
        time: timeFormatted,
        open: bar.open, close: bar.close, high: bar.high, low: bar.low,
        agg,
      };
    }
    return {
      kind: "line",
      time: timeFormatted,
      close: bar.close,
      agg,
    };
  }, [hoverBarIndex, bars, trades, viewCfg.datasetType, viewCfg.period]);

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
          dayKGranularity={dayKGranularity}
          setDayKGranularity={setDayKGranularity}
          overlayDates={overlayDates}
          toggleOverlayDate={toggleOverlayDate}
          overlayCloseByDate={overlayCloseByDate}
          hoverInfo={hoverInfo}
        />
        <div className="detail-chart-wrap" data-view={view}>
          {view === "overlay" ? (
            <DetailChartOverlay
              symbol={symbol}
              dates={overlayDates}
              barsByDate={overlayBars.barsByDate}
              loadingDates={overlayBars.loadingDates}
              errorDates={overlayBars.errorDates}
              onHoverSlot={setOverlayHoverSlot}
            />
          ) : bars && bars.bars.length > 0 && tradesInitialized && pairsInitialized && barsInitialized ? (
            <DetailChart
              symbol={symbol}
              bars={bars.bars}
              view={view}
              viewCfg={viewCfg}
              trades={trades}
              onHoverBar={setHoverBarIndex}
              onNeedOlder={handleNeedOlder}
            />
          ) : (
            <div className="empty-pat" style={{ height: "100%", display: "flex", alignItems: "center", justifyContent: "center" }}>
              {barsInitialized && bars && bars.bars.length === 0 ? "暂无 K 线数据" : "加载中..."}
            </div>
          )}
        </div>
      </div>

      <DetailTabSwipe
        tabs={[
          {
            id: "records",
            label: "交易记录",
            content: (
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
                onSyncRecentTrades={onSyncRecentTrades}
                onRefetchTrades={onRefetchTrades}
                onClearAllTrades={onClearAllTrades}
              />
            ),
          },
          {
            id: "trading",
            label: "交易面板",
            content: (
              <TradingPanel
                ticker={ticker}
                symbol={symbol}
                onRequestCancel={setTradingCancel}
                onRequestMore={setTradingMoreFor}
              />
            ),
          },
          {
            id: "alerts",
            label: "告警",
            content: (
              <AlertsPanel
                ticker={ticker}
                symbol={symbol}
                onRequestAddOrEdit={(initial) => setAlertModalFor(initial ?? "new")}
                onRequestDelete={setAlertDeleteConfirm}
              />
            ),
          },
        ] satisfies TabDef[]}
        index={tabIndex}
        onIndexChange={(i) => setTabIndex(i as 0 | 1 | 2)}
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

      {/* Trading-panel modals hosted at detail-pane level so they
         render at the right place regardless of swipe transform. */}
      {tradingCancel && (
        <ConfirmModal
          title="撤销订单"
          description={`确认撤销 ${tradingCancel.side} ${tradingCancel.qty} ${tradingCancel.ticker} @ ${tradingCancel.price == null ? "市价" : `$${tradingCancel.price.toFixed(2)}`}？`}
          confirmLabel="确认撤单"
          danger
          placement="bottom"
          onCancel={() => setTradingCancel(null)}
          onConfirm={onTradingCancelConfirm}
        />
      )}
      {tradingMoreFor && (
        <FullOrderModal
          symbol={tradingMoreFor.symbol}
          ticker={tradingMoreFor.ticker}
          lastDone={tradingMoreFor.lastDone}
          placement="bottom"
          onSubmit={onTradingMoreSubmit}
          onClose={() => setTradingMoreFor(null)}
        />
      )}
      {alertModalFor && (
        <AlertModal
          ticker={ticker}
          symbol={symbol}
          initial={alertModalFor === "new" ? undefined : alertModalFor}
          placement="bottom"
          onSubmit={onAlertCreateOrUpdate}
          onClose={() => setAlertModalFor(null)}
        />
      )}
      {alertDeleteConfirm && (
        <ConfirmModal
          title="确认删除告警？"
          description={`${fmtAlertCond(alertDeleteConfirm)} — 删除后无法恢复。`}
          confirmLabel="删除"
          danger
          placement="bottom"
          onCancel={() => setAlertDeleteConfirm(null)}
          onConfirm={onAlertDeleteConfirm}
        />
      )}

      {/* Detail-scoped notice stack — feedback for trading / alert
         actions appears centered over the detail-pane working area. */}
      <NoticeStack anchor="detail" />
    </div>
  );
}
