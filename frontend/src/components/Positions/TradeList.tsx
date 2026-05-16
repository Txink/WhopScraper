import { useEffect, useMemo, useState } from "react";
import type { TPair, Trade } from "../../api/domain-types";
import { useDetailViewStore } from "../../stores/detailView";
import { pairColor } from "./pairMath";
import { fmtBjRel } from "./timeFmt";

// Local pagination size. The whole ticker's trades (up to 500) live in
// the store from the moment the pane opens, so cross-page做T binding is
// safe — selectedBuys/selectedSells reference IDs that remain resolvable
// regardless of which page is currently in view.
const PAGE_SIZE = 8;

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
   *  local pagination: switching to a different ticker rewinds to page 1,
   *  while appending more rows for the SAME ticker preserves the page
   *  index. (Earlier impl reset on every ``trades`` array identity
   *  change and clobbered the user's page jump when ``onRequestMore``
   *  loaded more rows.) */
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
   *  Drives the pagination control's totalPages — local ``trades.length``
   *  reflects only the rows currently loaded into the store. */
  totalCount?: number;
  /** ``true`` while an outstanding ``onRequestMore`` fetch is in flight. */
  loading?: boolean;
  /** Called when the user navigates to a page whose rows aren't yet in
   *  the store. Caller fetches the next chunk and appends it. */
  onRequestMore?(): void | Promise<void>;
  onConfirmBind(): Promise<void> | void;
  onExtendPair(pairId: number): Promise<void> | void;
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
}: Props) {
  const sorted = useMemo(() => [...trades].sort((a, b) => Date.parse(b.ts) - Date.parse(a.ts)), [trades]);

  // Local pagination. Reset to page 1 only when the *ticker* changes —
  // appending more rows for the same ticker (via onRequestMore) must
  // preserve the user's page index. ``trades`` array identity is NOT a
  // safe dep here: it changes on every append.
  const [page, setPage] = useState(1);
  useEffect(() => { setPage(1); }, [ticker]);
  // Pagination is server-driven: ``totalCount`` is the full ticker's
  // trade count, while ``trades`` holds only the rows already fetched.
  // When the user jumps to a page whose first row isn't loaded yet,
  // ``onRequestMore`` fetches more and the store grows in place.
  const serverTotal = typeof totalCount === "number" && totalCount > 0
    ? totalCount
    : sorted.length;
  const totalPages = Math.max(1, Math.ceil(serverTotal / PAGE_SIZE));
  const safePage = Math.min(page, totalPages);

  // Fire ``onRequestMore`` whenever the current page's first row isn't
  // yet in the in-memory list.
  useEffect(() => {
    const firstRowIdx = (safePage - 1) * PAGE_SIZE;
    if (firstRowIdx >= sorted.length && firstRowIdx < serverTotal && !loading) {
      void onRequestMore?.();
    }
  }, [safePage, sorted.length, serverTotal, loading, onRequestMore]);

  const pageRows = useMemo(
    () => sorted.slice((safePage - 1) * PAGE_SIZE, safePage * PAGE_SIZE),
    [sorted, safePage],
  );

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
      <div className="trade-tbl-wrap">
        <table className="trade-tbl">
          <thead>
            <tr>
              <th className="compact"></th>
              <th>时间</th>
              <th>方向</th>
              <th style={{ textAlign: "right" }}>数量</th>
              <th style={{ textAlign: "right" }}>成交价</th>
              <th style={{ textAlign: "right" }}>金额</th>
              <th>做T</th>
            </tr>
          </thead>
          <tbody>
            {pageRows.map((t) => {
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
                  <td>
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
            {/* Pad the last page with blank rows so the pagination control
               doesn't shift up when fewer than PAGE_SIZE real trades land
               on the current page. 7 columns matches the thead. */}
            {Array.from({ length: Math.max(0, PAGE_SIZE - pageRows.length) }).map(
              (_, i) => (
                <tr key={`pad-${i}`} className="t-row t-row-empty" aria-hidden>
                  <td className="compact" />
                  <td className="tic">&nbsp;</td>
                  <td />
                  <td />
                  <td />
                  <td />
                  <td />
                </tr>
              ),
            )}
          </tbody>
        </table>
      </div>
      {/* Footer strip: 3-column grid. Left = section identity (买卖记录 ·
       *  N 笔), center = pagination, right = supplementary meta (做T 配对
       *  count + 上次更新). Replaces the standalone ``.panel-head`` above
       *  the table — saves ~36px of vertical real estate while keeping
       *  the pagination buttons visually centered. */}
      <div className="trade-foot">
        <span className="trade-foot-meta trade-foot-left">
          <span className="trade-foot-label">买卖记录</span>
          {serverTotal} 笔
        </span>
        <span className="trade-foot-center">
          {totalPages > 1 && (
            <Pagination
              page={safePage}
              totalPages={totalPages}
              onChange={setPage}
            />
          )}
        </span>
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

/**
 * Numbered pagination control. Shows ‹ 1 … N-1 N N+1 … last › with the
 * current page highlighted. Adjacent pages around the cursor + first /
 * last are always rendered so the user can jump-cursor without scrolling
 * through a long row of buttons when there are many pages.
 */
function Pagination({
  page,
  totalPages,
  onChange,
}: {
  page: number;
  totalPages: number;
  onChange(p: number): void;
}) {
  const pages = useMemo(() => {
    // Window of 1 page either side of cursor, plus first/last.
    const set = new Set<number>([1, totalPages, page - 1, page, page + 1]);
    return [...set]
      .filter((p) => p >= 1 && p <= totalPages)
      .sort((a, b) => a - b);
  }, [page, totalPages]);

  const items: (number | "…")[] = [];
  for (let i = 0; i < pages.length; i++) {
    items.push(pages[i]!);
    const next = pages[i + 1];
    if (next != null && next - pages[i]! > 1) items.push("…");
  }

  return (
    <div className="trade-pagination">
      <button
        className="page-btn"
        onClick={() => onChange(page - 1)}
        disabled={page <= 1}
        aria-label="上一页"
      >‹</button>
      {items.map((it, idx) =>
        it === "…" ? (
          <span key={`gap-${idx}`} className="page-gap">…</span>
        ) : (
          <button
            key={it}
            className={`page-btn ${it === page ? "active" : ""}`}
            onClick={() => onChange(it)}
          >{it}</button>
        ),
      )}
      <button
        className="page-btn"
        onClick={() => onChange(page + 1)}
        disabled={page >= totalPages}
        aria-label="下一页"
      >›</button>
    </div>
  );
}
