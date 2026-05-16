import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../../api/http";
import type { Position } from "../../api/domain-types";
import { toUsd } from "../../utils/currency";
import { usePositionsStore } from "../../stores/positions";
import { useQuotesStore } from "../../stores/quotes";
import { useCandlesticksStore, candleCacheKey } from "../../stores/candlesticks";
import { useExecutionsStore } from "../../stores/executions";
import { useDetailViewStore } from "../../stores/detailView";
import { PositionCard } from "./PositionCard";
import { OptionCard } from "./OptionCard";
import { DetailPane } from "./DetailPane";
import { PortfolioSummary } from "./PortfolioSummary";
import { SparkDefs } from "./SparkDefs";
import { resolveSessionParam } from "./resolveSessionParam";
import { marketOf } from "../Card/cardHelpers";
import "./Positions.css";
import "./Detail.css";

type PanelView = "stocks" | "options";

/** Hook: bootstrap quotes / intraday bars / executions for every
 *  position, and keep the backend's quote-push watch set in sync with
 *  the current symbol list. Quotes + fills now arrive via WebSocket push
 *  (``quote.snapshot`` and ``execution.update``); the panel only does
 *  one-shot HTTP pulls on mount + when positions change.
 *  Options use the same quote endpoint — the backend dispatches to
 *  ``option_quote`` based on symbol shape — but do not fetch
 *  candlesticks/pairs (those are stock-only concepts). */
function usePositionsData(stocks: Position[], options: Position[]): void {
  const setQuotes = useQuotesStore((s) => s.setQuotes);
  const setBars = useCandlesticksStore((s) => s.setBars);
  const setExecutions = useExecutionsStore((s) => s.setExecutions);

  useEffect(() => {
    const allSymbols = [...stocks.map((p) => p.symbol), ...options.map((p) => p.symbol)];
    if (allSymbols.length === 0) return;
    let cancelled = false;

    // One-shot initial quote pull so cards have prev_close / change /
    // change_pct before the first push lands. Subsequent updates arrive
    // via WebSocket (``quote.snapshot``), so there is no polling interval.
    const fetchQuotes = async () => {
      try {
        const r = await api.quotes(allSymbols);
        if (!cancelled) setQuotes(r.quotes);
      } catch (e) {
        console.warn("quote fetch failed", e);
      }
    };

    // One-shot candlestick pull on mount — gives the sparkline its bar
    // skeleton. The last bar's close is overwritten in PositionCard from
    // the live ``quote.last_done`` so the chart head follows price ticks
    // without re-fetching. (If the user keeps the dashboard open across a
    // 5-min bar boundary the line just extends the last bar visually;
    // a full refresh on account switch + dashboard re-open catches up.)
    const fetchCandles = async () => {
      for (const p of stocks) {
        if (cancelled) return;
        const sess =
          useQuotesStore.getState().quotesBySymbol[p.symbol]?.trade_session ??
          "regular";
        const sessionParam = resolveSessionParam(marketOf(p.symbol), sess);
        try {
          const c = await api.candlesticks(p.symbol, "today", {
            granularity: "分时",
            sessions: sessionParam,
          });
          if (!cancelled) {
            setBars(candleCacheKey(p.symbol, "today", "分时", sessionParam), c);
          }
        } catch (e) {
          console.warn("candlesticks fetch failed", p.symbol, e);
        }
      }
      for (const p of options) {
        if (cancelled) return;
        try {
          const c = await api.candlesticks(p.symbol, "30");
          if (!cancelled) setBars(candleCacheKey(p.symbol, "30"), c);
        } catch (e) {
          console.warn("option candlesticks fetch failed", p.symbol, e);
        }
      }
    };

    // 做T pairs are no longer shown on the positions panel — the
    // DetailPane fetches its own pair list when opened. Keeping this
    // function out of the bulk-load shaves one request per dashboard
    // mount (and avoids leaking a stale pairs store across account
    // switches).

    const fetchExecutions = async () => {
      // Seed Day P/L with today's fills before the first
      // ``execution.update`` push lands. Subsequent fills arrive via WS;
      // no polling interval — the SubscriptionManager + per-card upsert
      // keeps the chip live without re-hitting the broker.
      try {
        const r = await api.todayExecutions();
        if (!cancelled) setExecutions(r.executions);
      } catch (e) {
        console.warn("today_executions fetch failed", e);
      }
    };

    // Sync the backend's quote-push watch set to the current positions.
    // Retried twice on 503 (broker init race after account switch).
    const watchQuotes = async () => {
      for (let attempt = 0; attempt < 3; attempt++) {
        try {
          await api.watchQuotes(allSymbols);
          return;
        } catch (e) {
          // 503 = quote hub not yet built; broker reload in progress.
          if (attempt === 2) console.warn("watchQuotes failed", e);
          await new Promise((r) => setTimeout(r, 500));
        }
      }
    };

    fetchQuotes();
    fetchCandles();
    fetchExecutions();
    void watchQuotes();

    // All live data now arrives via WebSocket push — no polling timer.
    // Cleanup just drops the quote-watch set so the backend stops
    // pushing symbols we no longer care about.
    return () => {
      cancelled = true;
      void api.watchQuotes([]).catch(() => undefined);
    };
  // Positions list is shallow-compared via length-stringified symbols.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    stocks.map((p) => p.symbol).join(","),
    options.map((p) => p.symbol).join(","),
  ]);
}

/** Refetch a single stock's intraday bars when its trade_session changes.
 *  We diff per-symbol via useRef so the effect doesn't fire on every push
 *  (quotesBySymbol reference identity changes on every WS update). */
function useSessionTransitionRefetch(stocks: Position[]): void {
  const setBars = useCandlesticksStore((s) => s.setBars);
  const quotesBySymbol = useQuotesStore((s) => s.quotesBySymbol);
  const lastSessionRef = useRef<Record<string, string>>({});

  useEffect(() => {
    for (const p of stocks) {
      const cur = quotesBySymbol[p.symbol]?.trade_session;
      if (!cur) continue;
      const prev = lastSessionRef.current[p.symbol];
      if (prev !== cur) {
        lastSessionRef.current[p.symbol] = cur;
        if (prev !== undefined) {
          // True transition — refetch with the new session.
          const sessionParam = resolveSessionParam(marketOf(p.symbol), cur);
          void api.candlesticks(p.symbol, "today", {
            granularity: "分时",
            sessions: sessionParam,
          }).then((c) => {
            setBars(candleCacheKey(p.symbol, "today", "分时", sessionParam), c);
          }).catch((e) => {
            console.warn("session-transition refetch failed", p.symbol, e);
          });
        }
      }
    }
  }, [quotesBySymbol, stocks, setBars]);
}

export function PositionsPanel() {
  const stocks = usePositionsStore((s) => s.stocks);
  const options = usePositionsStore((s) => s.options);
  usePositionsData(stocks, options);
  useSessionTransitionRefetch(stocks);

  const quotesBySymbol = useQuotesStore((s) => s.quotesBySymbol);
  const candleByKey = useCandlesticksStore((s) => s.byKey);
  const executions = useExecutionsStore((s) => s.executions);
  const selectedSymbol = useDetailViewStore((s) => s.selectedSymbol);
  const selectSymbol = useDetailViewStore((s) => s.selectSymbol);

  // Sort cards by USD-normalized market value (last_done × qty) descending
  // so the biggest holdings sit at the top. Missing quote → market value 0,
  // sinks to the bottom but still renders so the user sees the position
  // exists. Sort is non-mutating (slice + sort copy).
  const sortedStocks = useMemo(() => {
    return stocks.slice().sort((a, b) => {
      const va = (toUsd(a.symbol, quotesBySymbol[a.symbol]?.last_done) ?? 0) * a.quantity;
      const vb = (toUsd(b.symbol, quotesBySymbol[b.symbol]?.last_done) ?? 0) * b.quantity;
      return vb - va;
    });
  }, [stocks, quotesBySymbol]);
  const sortedOptions = useMemo(() => {
    return options.slice().sort((a, b) => {
      const va = (toUsd(a.symbol, quotesBySymbol[a.symbol]?.last_done) ?? 0) * a.quantity;
      const vb = (toUsd(b.symbol, quotesBySymbol[b.symbol]?.last_done) ?? 0) * b.quantity;
      return vb - va;
    });
  }, [options, quotesBySymbol]);

  const [view, setView] = useState<PanelView>("stocks");

  // Drill-down detail view: when a symbol is selected (stock OR option
  // contract), replace the grid with the DetailPane. Symbol — not ticker
  // — disambiguates a stock card from any of its option contract cards.
  if (selectedSymbol) {
    const pos =
      stocks.find((p) => p.symbol === selectedSymbol) ??
      options.find((p) => p.symbol === selectedSymbol);
    if (pos) {
      return (
        <aside className="positions-panel">
          <SparkDefs />
          <DetailPane position={pos} onBack={() => selectSymbol(null)} />
        </aside>
      );
    }
  }

  const tabs = (
    <div className="positions-tabs" role="tablist" aria-label="持仓分类">
      <button
        role="tab"
        aria-selected={view === "stocks"}
        className={view === "stocks" ? "active" : ""}
        onClick={() => setView("stocks")}
        type="button"
      >
        正股 <span className="count">{stocks.length}</span>
      </button>
      <button
        role="tab"
        aria-selected={view === "options"}
        className={view === "options" ? "active" : ""}
        onClick={() => setView("options")}
        type="button"
      >
        期权 <span className="count">{options.length}</span>
      </button>
    </div>
  );

  // Pull the per-view summary out so the header + summary form one
  // sticky block that stays pinned at the top of the panel while only
  // the card grid scrolls underneath.
  const summary =
    view === "stocks"
      ? stocks.length > 0 && <PortfolioSummary stocks={stocks} />
      : options.length > 0 && <PortfolioSummary stocks={[]} options={options} />;

  return (
    <aside className="positions-panel">
      <SparkDefs />
      <div className="positions-panel-top">
        <header className="positions-panel-head">{tabs}</header>
        {summary}
      </div>
      {view === "stocks" ? (
        sortedStocks.length === 0 ? (
          <div className="positions-empty">暂无正股持仓</div>
        ) : (
          <div className="positions-grid">
            {sortedStocks.map((p) => (
              <PositionCard
                key={p.symbol}
                position={p}
                quote={quotesBySymbol[p.symbol]}
                intraday={(() => {
                  const sess = quotesBySymbol[p.symbol]?.trade_session ?? "regular";
                  const sessionParam = resolveSessionParam(marketOf(p.symbol), sess);
                  return candleByKey[candleCacheKey(p.symbol, "today", "分时", sessionParam)];
                })()}
                executions={executions}
                onClick={() => selectSymbol(p.symbol)}
              />
            ))}
          </div>
        )
      ) : sortedOptions.length === 0 ? (
        <div className="positions-empty">暂无期权持仓</div>
      ) : (
        <div className="positions-grid">
          {sortedOptions.map((p) => (
            <OptionCard
              key={p.symbol}
              position={p}
              quote={quotesBySymbol[p.symbol]}
              history={candleByKey[candleCacheKey(p.symbol, "30")]}
              executions={executions}
              onClick={() => selectSymbol(p.symbol)}
            />
          ))}
        </div>
      )}
    </aside>
  );
}
