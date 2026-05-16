import { useEffect, useMemo, useRef, useState } from "react";
import type { TPair, Trade } from "../../api/domain-types";
import { useDetailViewStore } from "../../stores/detailView";
import { pairColor } from "./pairMath";
import { fmtBjRel } from "./timeFmt";

/** Tri-state filter on the trade table. ``"untagged"`` keeps rows whose
 *  ``t_pair_tags`` is empty (no做T binding at all); ``"tagged"`` keeps
 *  rows with at least one做T entry (partial counts as tagged too). */
export type TradeListFilter = "all" | "untagged" | "tagged";

/** Settings-gear icon for the trade-list menu trigger. Inline SVG +
 *  ``currentColor`` so it picks up the button's CSS color (project
 *  convention — see Dashboard/icons.tsx). */
function GearIcon({ size = 14 }: { size?: number }) {
  return (
    <svg
      viewBox="0 0 16 16"
      width={size}
      height={size}
      fill="none"
      stroke="currentColor"
      strokeWidth="1.4"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <circle cx="8" cy="8" r="2.4" />
      <path d="M8 1.5v1.6 M8 12.9v1.6 M1.5 8h1.6 M12.9 8h1.6 M3.4 3.4l1.1 1.1 M11.5 11.5l1.1 1.1 M3.4 12.6l1.1-1.1 M11.5 4.5l1.1-1.1" />
    </svg>
  );
}

// Default 3 — only ``fmt(t.price)`` uses the default; qty / 金额 /
// 已实现 / pct all pass d=0 or d=2 explicitly.
function fmt(n: number, d = 3): string {
  return n.toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d });
}

/** Compact "<n> 秒前 / 分钟前 / 小时前 / 今天 hh:mm / yyyy-mm-dd hh:mm". */
function fmtLastSynced(iso: string): string {
  const t = new Date(iso).getTime();
  if (!Number.isFinite(t)) return iso;
  const diff = Date.now() - t;
  if (diff < 60_000) return "刚刚";
  if (diff < 3600_000) return `${Math.floor(diff / 60_000)} 分钟前`;
  if (diff < 24 * 3600_000) return `${Math.floor(diff / 3600_000)} 小时前`;
  return fmtBjRel(iso);
}

interface Props {
  trades: Trade[];
  pairs: TPair[];
  /** Ticker the table is currently rendering. Used as the reset key for
   *  scroll position — switching ticker rewinds the table to the top. */
  ticker?: string;
  /** Wall-clock moment of the most recent broker→DB sync. Rendered as a
   *  small "上次更新：xxx" caption above the table. ``null`` when no
   *  sync has happened yet (first-ever open) — caption is omitted. */
  lastSyncedAt?: string | null;
  /** When true, hide the做T binding builder + per-row pair chips
   *  entirely. Used by the option detail pane — pair binding is a
   *  stock-only concept. */
  disableBinding?: boolean;
  /** Total trade count reported by the server (for the current ticker).
   *  Used to know whether the bottom sentinel should still trigger
   *  ``onRequestMore`` — local ``trades.length`` reflects only the rows
   *  currently loaded into the store. */
  totalCount?: number;
  /** ``true`` while an outstanding ``onRequestMore`` fetch is in flight.
   *  Drives the inline "加载中…" indicator at the bottom of the scroll
   *  area AND throttles the IntersectionObserver so a sentinel that
   *  stays in view doesn't fire repeatedly during a single fetch. */
  loading?: boolean;
  /** Called when the bottom sentinel scrolls into view and there are
   *  still un-fetched server rows. Caller fetches the next chunk and
   *  appends it to the store. */
  onRequestMore?(): void | Promise<void>;
  onConfirmBind(): Promise<void> | void;
  onExtendPair(pairId: number): Promise<void> | void;
  /** Tri-state filter on the table rows; "all" shows everything,
   *  "untagged" shows only trades with no做T binding (including those
   *  with leftover available qty on partial pairs), "tagged" shows only
   *  trades that have at least one做T entry. Filter is applied client-
   *  side over the already-loaded rows; switch back to "all" to keep
   *  scrolling for more. */
  filter?: TradeListFilter;
  onFilterChange?(f: TradeListFilter): void;
  /** Settings-menu actions. Each is fired with no args; the caller
   *  knows the active ticker. */
  onClearAllPairs?(): Promise<void> | void;
  onRefetchTrades?(): Promise<void> | void;
  onClearAllTrades?(): Promise<void> | void;
}

/** Trade table + sticky bind-builder. Trades with avail > 0 show a colored
 *  checkbox; clicking the row toggles selection. Already-bound trades show
 *  pair chips that link the row to its做T allocation(s); clicking a chip
 *  highlights that pair on the chart. */
export function TradeList({
  trades,
  pairs,
  ticker,
  lastSyncedAt,
  disableBinding = false,
  totalCount,
  loading = false,
  onRequestMore,
  onConfirmBind,
  onExtendPair,
  filter = "all",
  onFilterChange,
  onClearAllPairs,
  onRefetchTrades,
  onClearAllTrades,
}: Props) {
  const sorted = useMemo(() => [...trades].sort((a, b) => Date.parse(b.ts) - Date.parse(a.ts)), [trades]);

  // Filter is purely client-side — the server still returns the
  // unfiltered slice, and the user keeps scrolling in "all" mode to
  // pull more rows for the filter to consume. Avoids a new server-side
  // "where t_pair_tags is empty" query path.
  const filteredSorted = useMemo(() => {
    if (filter === "all") return sorted;
    return sorted.filter((t) => {
      const hasTag = (t.t_pair_tags ?? []).length > 0;
      return filter === "tagged" ? hasTag : !hasTag;
    });
  }, [sorted, filter]);

  const serverTotal = typeof totalCount === "number" && totalCount > 0
    ? totalCount
    : sorted.length;
  const displayedTotal = filter === "all" ? serverTotal : filteredSorted.length;
  // In "all" mode there may still be unfetched server rows behind the
  // bottom sentinel; in filtered mode the view is purely local so no
  // further fetch is meaningful.
  const hasMoreToFetch = filter === "all" && sorted.length < serverTotal;

  // Reset the scroll position to the top whenever the ticker or filter
  // changes — both reframe what the user is looking at, and keeping the
  // old offset would land them in the middle of a different list.
  const scrollRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    scrollRef.current?.scrollTo({ top: 0 });
  }, [ticker, filter]);

  // IntersectionObserver-driven infinite scroll. The sentinel sits just
  // below the last row; when it enters the scroll container's viewport
  // we fire ``onRequestMore`` (unless one is already in flight). The
  // ``loading`` guard matters because the sentinel can remain in view
  // across renders while the new chunk is being fetched.
  const sentinelRef = useRef<HTMLTableRowElement | null>(null);
  useEffect(() => {
    const sentinel = sentinelRef.current;
    const root = scrollRef.current;
    if (!sentinel || !root || !hasMoreToFetch) return;
    const obs = new IntersectionObserver(
      (entries) => {
        const entry = entries[0];
        if (entry?.isIntersecting && !loading) {
          void onRequestMore?.();
        }
      },
      { root, rootMargin: "120px 0px" },
    );
    obs.observe(sentinel);
    return () => obs.disconnect();
  }, [hasMoreToFetch, loading, onRequestMore]);

  // Settings menu open/close state + click-outside dismiss.
  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    if (!menuOpen) return;
    function onDocClick(e: MouseEvent) {
      if (!menuRef.current) return;
      if (!menuRef.current.contains(e.target as Node)) setMenuOpen(false);
    }
    document.addEventListener("mousedown", onDocClick);
    return () => document.removeEventListener("mousedown", onDocClick);
  }, [menuOpen]);

  const selectedBuys = useDetailViewStore((s) => s.selectedBuys);
  const selectedSells = useDetailViewStore((s) => s.selectedSells);
  const activePairId = useDetailViewStore((s) => s.activePairId);
  const setActivePair = useDetailViewStore((s) => s.setActivePair);
  const toggleTrade = useDetailViewStore((s) => s.toggleTrade);
  const clearSelection = useDetailViewStore((s) => s.clearSelection);

  // Aggregate stats for the bind builder. Uses AVAILABLE qty per trade,
  // so a trade with partial allocation contributes only its leftover.
  const stats = useMemo(() => {
    let buyQty = 0, sellQty = 0, buyCost = 0, sellRev = 0;
    // Available qty per trade comes from the denormalized t_pair_tags
    // column on each trade (sum allocations and subtract from qty) rather
    // than scanning all pairs. Same answer, no list traversal.
    const availOf = (t: Trade): number => {
      const used = (t.t_pair_tags ?? []).reduce((s, [, q]) => s + q, 0);
      return Math.max(0, t.qty - used);
    };
    for (const id of selectedBuys) {
      const t = trades.find((tr) => tr.id === id);
      if (!t) continue;
      const a = availOf(t);
      buyQty += a;
      buyCost += a * t.price;
    }
    for (const id of selectedSells) {
      const t = trades.find((tr) => tr.id === id);
      if (!t) continue;
      const a = availOf(t);
      sellQty += a;
      sellRev += a * t.price;
    }
    const matched = Math.min(buyQty, sellQty);
    const avgBuy = buyQty > 0 ? buyCost / buyQty : 0;
    const avgSell = sellQty > 0 ? sellRev / sellQty : 0;
    const realized = matched > 0 ? matched * (avgSell - avgBuy) : 0;
    const realizedPct = matched > 0 && avgBuy > 0 ? ((avgSell - avgBuy) / avgBuy) * 100 : 0;
    return {
      buyQty, sellQty, matched, realized, realizedPct,
      canBind: buyQty > 0 || sellQty > 0,
      leftoverBuy: Math.max(0, buyQty - matched),
      leftoverSell: Math.max(0, sellQty - matched),
    };
  }, [selectedBuys, selectedSells, trades, pairs]);

  const hasSelection = selectedBuys.size + selectedSells.size > 0;

  return (
    <div className="panel trade-panel">
      <div className="trade-tbl-wrap" ref={scrollRef}>
        <table className="trade-tbl">
          <thead>
            <tr>
              <th className="compact"></th>
              <th>时间</th>
              <th style={{ textAlign: "center" }}>方向</th>
              <th style={{ textAlign: "right" }}>数量</th>
              <th style={{ textAlign: "right" }}>成交价</th>
              <th style={{ textAlign: "right" }}>金额</th>
              <th>做T</th>
            </tr>
          </thead>
          <tbody>
            {filteredSorted.map((t) => {
              // Server denormalizes ``[[pair_id, qty], ...]`` into each
              // trade row so the chip column can render without scanning
              // every pair (and so pending-做T SQL is just a column read).
              const tags: [number, number][] = t.t_pair_tags ?? [];
              const allocated = tags.reduce((s, [, q]) => s + q, 0);
              const avail = Math.max(0, t.qty - allocated);
              const isSel = t.side === "BUY"
                ? selectedBuys.has(t.id)
                : selectedSells.has(t.id);
              // Row color: highlight the active pair's color when this row
              // is part of it; otherwise first allocation. No allocation →
              // no row color.
              const activeTag = tags.find(([pid]) => pid === activePairId);
              const colorPid = activeTag?.[0] ?? tags[0]?.[0] ?? null;
              const rowColor = colorPid != null ? pairColor(colorPid, pairs) : null;

              return (
                <tr
                  key={t.id}
                  className={`t-row ${isSel ? "selected" : ""}`}
                  style={rowColor ? { ["--pair-color" as never]: rowColor } : undefined}
                  onClick={
                    disableBinding
                      ? undefined
                      : () => {
                          if (avail > 0) toggleTrade(t.id, t.side as "BUY" | "SELL");
                          else if (colorPid != null) {
                            setActivePair(colorPid === activePairId ? null : colorPid);
                          }
                        }
                  }
                >
                  <td className="compact" onClick={(e) => e.stopPropagation()}>
                    {!disableBinding && avail > 0 && (
                      <input
                        type="checkbox"
                        className={t.side === "BUY" ? "sel-buy" : "sel-sell"}
                        checked={isSel}
                        onChange={() => toggleTrade(t.id, t.side as "BUY" | "SELL")}
                        title={`将剩余 ${avail} 股加入做T 绑定`}
                      />
                    )}
                  </td>
                  <td className="tic">{fmtBjRel(t.ts)}</td>
                  <td style={{ textAlign: "center" }}>
                    <span className={`cell-side ${t.side.toLowerCase()}`}>{t.side}</span>
                  </td>
                  <td style={{ textAlign: "right" }}>
                    {fmt(t.qty, 0)}
                    {allocated > 0 && allocated < t.qty && (
                      <span className="qty-avail" title={`已绑 ${allocated} / 剩 ${avail}`}>
                        ({fmt(avail, 0)} 剩)
                      </span>
                    )}
                  </td>
                  <td style={{ textAlign: "right" }}>{fmt(t.price)}</td>
                  <td style={{ textAlign: "right", color: "var(--fg-2)" }}>
                    {fmt(t.qty * t.price, 0)}
                  </td>
                  <td>
                    {tags.length === 0 ? (
                      <span style={{ color: "var(--fg-3)", fontSize: 10 }}>—</span>
                    ) : (
                      <span className="pair-chip-row">
                        {tags.map(([pid, qty]) => {
                          const c = pairColor(pid, pairs);
                          const isAct = pid === activePairId;
                          return (
                            <span
                              key={pid}
                              className={`pair-chip ${isAct ? "active" : ""}`}
                              style={{ ["--pair-color" as never]: c }}
                              onClick={(e) => {
                                e.stopPropagation();
                                setActivePair(pid === activePairId ? null : pid);
                              }}
                            >
                              <span className="dotty" />T-{pid}
                              {qty !== t.qty && <span className="qty-suffix">·{fmt(qty, 0)}</span>}
                            </span>
                          );
                        })}
                      </span>
                    )}
                  </td>
                </tr>
              );
            })}
            {/* Bottom sentinel — when it scrolls into the container's
               viewport (rootMargin 120px) the effect above fires
               ``onRequestMore``. Inline 加载中 / 已全部加载 caption sits
               in the same row so the layout doesn't jump as more rows
               stream in. Hidden entirely in filtered modes since the
               visible set is already bounded by what's loaded. */}
            {filter === "all" && (
              <tr ref={sentinelRef} className="t-row-sentinel" aria-hidden>
                <td colSpan={7}>
                  {loading
                    ? "加载中…"
                    : hasMoreToFetch
                      ? ""
                      : sorted.length > 0 ? "已全部加载" : ""}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      {/* Footer strip: settings menu + section identity (交易记录 · N
       *  笔) on the left, supplementary meta (做T 配对 count + 上次更新)
       *  on the right. The center slot used to host pagination buttons;
       *  with infinite scroll it collapses (auto-width when empty). */}
      <div className="trade-foot">
        <span className="trade-foot-meta trade-foot-left">
          {!disableBinding && (
            <div className="trade-menu-wrap" ref={menuRef}>
              <button
                type="button"
                className="trade-menu-btn"
                onClick={() => setMenuOpen((v) => !v)}
                aria-label="交易记录设置"
                title="交易记录设置"
              >
                <GearIcon size={14} />
              </button>
              {menuOpen && (
                <div className="trade-menu" role="menu">
                  <button
                    className="trade-menu-item"
                    onClick={() => {
                      setMenuOpen(false);
                      void onClearAllPairs?.();
                    }}
                  >
                    清理所有做T 绑定
                  </button>
                  <div className="trade-menu-sep" />
                  <button
                    className={`trade-menu-item ${filter === "untagged" ? "active" : ""}`}
                    onClick={() => {
                      onFilterChange?.(filter === "untagged" ? "all" : "untagged");
                      setMenuOpen(false);
                    }}
                  >
                    {filter === "untagged" ? "✓ " : ""}只看未做T （含部分）
                  </button>
                  <button
                    className={`trade-menu-item ${filter === "tagged" ? "active" : ""}`}
                    onClick={() => {
                      onFilterChange?.(filter === "tagged" ? "all" : "tagged");
                      setMenuOpen(false);
                    }}
                  >
                    {filter === "tagged" ? "✓ " : ""}只看已做T （含部分）
                  </button>
                  <div className="trade-menu-sep" />
                  <button
                    className="trade-menu-item"
                    onClick={() => {
                      setMenuOpen(false);
                      void onRefetchTrades?.();
                    }}
                  >
                    重新拉取（近 2 年）
                  </button>
                  <button
                    className="trade-menu-item danger"
                    onClick={() => {
                      setMenuOpen(false);
                      void onClearAllTrades?.();
                    }}
                  >
                    清空交易记录
                  </button>
                </div>
              )}
            </div>
          )}
          <span className="trade-foot-label">交易记录</span>
          {displayedTotal} 笔
        </span>
        <span className="trade-foot-center" />
        <span className="trade-foot-meta trade-foot-right">
          {!disableBinding && <>{pairs.length} 个做T 配对</>}
          {lastSyncedAt && (
            <span className="last-synced">
              {!disableBinding && " · "}上次更新 {fmtLastSynced(lastSyncedAt)}
            </span>
          )}
        </span>
      </div>

      {hasSelection && !disableBinding && (
        <div className="bind-builder">
          <div className="group">
            <span className="gk">可绑 BUY</span>
            <span className="gv buy">{fmt(stats.buyQty, 0)}</span>
            <span className="gsub">({selectedBuys.size} 笔)</span>
          </div>
          <span className="sep">↔</span>
          <div className="group">
            <span className="gk">可绑 SELL</span>
            <span className="gv sell">{fmt(stats.sellQty, 0)}</span>
            <span className="gsub">({selectedSells.size} 笔)</span>
          </div>
          <span className={`diff ${stats.matched > 0 ? "match" : "mismatch"}`}>
            {stats.matched > 0
              ? `✓ 匹配 ${fmt(stats.matched, 0)} 股`
              : stats.canBind ? "仅一侧 · 部分做T" : "请勾选可用交易"}
          </span>
          {(stats.leftoverBuy > 0 || stats.leftoverSell > 0) && (
            <span
              className="diff mismatch"
              title="未匹配部分保留在原交易上，可继续与其他交易绑定"
            >
              留{" "}
              {stats.leftoverBuy > 0 && <>{fmt(stats.leftoverBuy, 0)} BUY</>}
              {stats.leftoverBuy > 0 && stats.leftoverSell > 0 && " · "}
              {stats.leftoverSell > 0 && <>{fmt(stats.leftoverSell, 0)} SELL</>}
            </span>
          )}
          {stats.matched > 0 && (
            <span className="preview">
              已实现收益{" "}
              <span className={`v ${stats.realized >= 0 ? "pos" : "neg"}`}>
                {stats.realized >= 0 ? "+" : ""}${fmt(stats.realized, 0)}
              </span>
              <span style={{ marginLeft: 6, color: "var(--fg-3)" }}>
                ({stats.realizedPct >= 0 ? "+" : ""}{fmt(stats.realizedPct, 2)}%)
              </span>
            </span>
          )}
          <div className="acts">
            <button className="btn ghost" onClick={clearSelection}>清除</button>
            <button
              className="btn primary"
              onClick={onConfirmBind}
              disabled={!stats.canBind}
              title="按 min(BUY,SELL) 自动匹配；剩余数量留在原交易上备用"
            >
              新建做T 配对
            </button>
          </div>
          {(() => {
            // Only surface pairs that still have unmatched qty on one
            // side — adding to a balanced pair would just push it into
            // partial state, which is rarely what the user intends.
            const extendable = pairs.filter((p) => {
              const buyQty = p.buys.reduce((s, b) => s + b.qty, 0);
              const sellQty = p.sells.reduce((s, b) => s + b.qty, 0);
              return buyQty !== sellQty;
            });
            if (extendable.length === 0) return null;
            return (
              <div className="extend-row">
                <span className="extend-label">或加入已有配对:</span>
                {extendable.map((p) => (
                  <button
                    key={p.id}
                    className="extend-chip"
                    style={{ ["--pair-color" as never]: pairColor(p.id, pairs) }}
                    onClick={() => onExtendPair(p.id)}
                    title={`追加到 T-${p.id}`}
                  >
                    <span className="plus">+</span> T-{p.id}
                  </button>
                ))}
              </div>
            );
          })()}
        </div>
      )}
    </div>
  );
}

