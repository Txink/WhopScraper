import { useMemo, useLayoutEffect, useRef, useState } from "react";
import type { Candlestick } from "../../api/domain-types";
import {
  resolveSessionWindow,
  type Market,
  type SessionLabel,
} from "./sessionWindow";

interface Props {
  symbol: string;
  market: Market;
  bars: Candlestick[] | undefined;
  session: SessionLabel;
  lastDone: number | null;
  openPrice: number | null;
}

// ViewBox is stretched via preserveAspectRatio="none" to fit the
// container. The line's vectorEffect="non-scaling-stroke" presentation
// attribute (applied on the <path> below) keeps the stroke at 1.4
// logical px regardless of the stretch.
const VB_W = 100;
const VB_H = 100;

/** Parse a naive LongPort timestamp ("YYYY-MM-DDTHH:mm:ss") as BJ
 *  wall-clock → UTC ms. Matches the convention in sessionSlots.ts. */
function parseAsBJ(iso: string | null | undefined): number {
  if (!iso) return Number.NaN;
  if (iso.endsWith("Z") || /[+-]\d{2}:?\d{2}$/.test(iso)) return Date.parse(iso);
  return Date.parse(iso + "+08:00");
}

/** Format a UTC ms as a naive BJ ISO string ("YYYY-MM-DDTHH:mm:ss"). */
const _BJ_ISO_FMT = new Intl.DateTimeFormat("sv-SE", {
  timeZone: "Asia/Shanghai",
  year: "numeric", month: "2-digit", day: "2-digit",
  hour: "2-digit", minute: "2-digit", second: "2-digit",
  hour12: false,
});
function bjIsoFromMs(ms: number): string {
  return _BJ_ISO_FMT.format(new Date(ms)).replace(" ", "T");
}

export function IntradaySpark({
  // symbol prop is intentionally unused inside the component — it's
  // accepted so callers can group by ticker. Renamed to _symbol to
  // signal that.
  symbol: _symbol, market, bars, session, lastDone, openPrice,
}: Props) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const [containerSize, setContainerSize] = useState<{ w: number; h: number }>({ w: 0, h: 0 });

  // Track container pixel size for pulse-dot positioning. ResizeObserver
  // keeps it accurate across grid relayout (option tab → stocks tab).
  useLayoutEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const measure = () => {
      const rect = el.getBoundingClientRect();
      setContainerSize({ w: rect.width, h: rect.height });
    };
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const win = useMemo(
    () => resolveSessionWindow(market, session, Date.now()),
    // session string OR market change → re-resolve.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [market, session],
  );

  /** Bars enriched with the live tip (last close overwritten by
   *  lastDone, or a new bar appended at the current minute). Skipped
   *  outside the active window — closed (weekend / holiday) and
   *  overnight (chart excludes overnight; the frozen pre+regular+post
   *  snapshot shouldn't be perturbed by overnight quote pushes), or
   *  whenever nowMs is past the window's end. */
  const renderedBars = useMemo(() => {
    if (!bars || bars.length === 0) return bars ?? [];
    if (session === "closed" || session === "overnight" || lastDone == null) {
      return bars;
    }
    const nowMs = Date.now();
    const lastBar = bars[bars.length - 1];
    const lastBarMs = parseAsBJ(lastBar.timestamp);
    const lastBarSlot = win.msToSlot(lastBarMs);
    const nowSlot = win.msToSlot(nowMs);

    if (nowSlot < 0) {
      // Outside the window (past end, or in a gap like HK lunch). Keep
      // bars as-is — overwriting the last bar's close with a stale or
      // out-of-window quote would corrupt the historical snapshot.
      return bars;
    }
    if (nowSlot < lastBarSlot) {
      // Clock jumped backwards (rare — system clock change?). Treat as
      // "in-place update" to be defensive without losing a real bar.
      return [...bars.slice(0, -1), { ...lastBar, close: lastDone }];
    }
    if (nowSlot === lastBarSlot) {
      return [...bars.slice(0, -1), {
        ...lastBar,
        close: lastDone,
        high: Math.max(lastBar.high ?? lastDone, lastDone),
        low: Math.min(lastBar.low ?? lastDone, lastDone),
      }];
    }
    return [...bars, {
      timestamp: bjIsoFromMs(win.slotToMs(nowSlot)),
      open: lastDone, high: lastDone, low: lastDone, close: lastDone,
      volume: 0, turnover: 0,
    }];
  }, [bars, lastDone, win, session]);

  // ``isClosed`` gates the "static snapshot" styling (dimmed line, no
  // pulse, no active-region highlight). Overnight is treated the same
  // visually because the chart doesn't include the 夜盘 region; the
  // pulse and live-region highlight have no slot to land in.
  const isClosed = session === "closed" || session === "overnight";

  // Project bars → (x, close) pairs. Drop:
  //   • bars outside the window (HK lunch; stale data from sessions=all)
  //   • bars with close ≤ 0 — the backend emits close=0 for empty
  //     minutes (where the broker had no tape), and including those in
  //     the y-range collapses real prices into the top of the chart and
  //     paints a phantom line plunging to baseline.
  const points = useMemo(() => {
    if (!renderedBars || renderedBars.length === 0) return [];
    const out: { x: number; close: number }[] = [];
    for (const b of renderedBars) {
      const slot = win.msToSlot(parseAsBJ(b.timestamp));
      if (slot < 0) continue;
      const close = b.close;
      if (close == null || close <= 0) continue;
      out.push({ x: (slot / win.slotCount) * VB_W, close });
    }
    return out;
  }, [renderedBars, win]);

  // Y-axis bounds (pad ±20% so the line never touches the top/bottom edge).
  const { yLo, yHi } = useMemo(() => {
    if (points.length === 0) return { yLo: 0, yHi: 1 };
    const closes = points.map((p) => p.close);
    const lo = Math.min(...closes);
    const hi = Math.max(...closes);
    const pad = (hi - lo) * 0.2 || Math.abs(lo) * 0.005 || 0.5;
    return { yLo: lo - pad, yHi: hi + pad };
  }, [points]);

  const yFor = (close: number): number =>
    yHi === yLo ? VB_H / 2 : ((yHi - close) / (yHi - yLo)) * VB_H;

  // Build line + area path strings. Points are filtered to a contiguous
  // valid-close sequence already, so a single subpath spans them all:
  //   line:  M x0,y0 L x1,y1 ... L xN,yN
  //   area:  M x0,VB_H L x0,y0 L x1,y1 ... L xN,yN L xN,VB_H Z
  const { linePath, areaPath } = useMemo(() => {
    if (points.length === 0) return { linePath: "", areaPath: "" };
    const first = points[0];
    const last = points[points.length - 1];
    let line = `M${first.x.toFixed(2)},${yFor(first.close).toFixed(2)} `;
    let area = `M${first.x.toFixed(2)},${VB_H} L${first.x.toFixed(2)},${yFor(first.close).toFixed(2)} `;
    for (let i = 1; i < points.length; i++) {
      const p = points[i];
      const seg = `L${p.x.toFixed(2)},${yFor(p.close).toFixed(2)} `;
      line += seg;
      area += seg;
    }
    area += `L${last.x.toFixed(2)},${VB_H} Z`;
    return { linePath: line.trim(), areaPath: area.trim() };
    // Deps list the scalars that drive yFor rather than yFor itself,
    // because yFor is a fresh function reference each render. With yFor
    // in the deps the memo would invalidate every render and the memo
    // would be moot.
  }, [points, yLo, yHi]);

  // Color decision: pos when last >= open, else neg.
  const lastClose = points.length > 0 ? points[points.length - 1].close : null;
  const refOpen = openPrice ?? (points.length > 0 ? points[0].close : null);
  const isPos = lastClose != null && refOpen != null
    ? lastClose >= refOpen
    : true;

  // Pulse dot pixel coords. Re-computed every render — quote pushes
  // trigger re-render via lastDone prop change, refreshing nowMs.
  const pulse = useMemo(() => {
    if (isClosed || lastDone == null || containerSize.w === 0) return null;
    const x = win.progress(Date.now()) * containerSize.w;
    const yVb = yFor(lastDone);
    const y = (yVb / VB_H) * containerSize.h;
    return { x, y };
    // Deps: yLo/yHi feed yFor; yFor itself is a fresh ref each render
    // so excluded. `win` is stable across same-session renders.
  }, [isClosed, lastDone, containerSize.w, containerSize.h, win, yLo, yHi]);

  if (!bars) {
    return (
      <div ref={containerRef} className="ispark">
        <div className="ispark-skeleton" aria-label="加载分时线…" />
      </div>
    );
  }

  const rootClass = [
    "ispark",
    isPos ? "pos" : "neg",
    isClosed ? "is-closed" : "",
  ].filter(Boolean).join(" ");

  const fillId = isPos ? "ispark-fill-up" : "ispark-fill-down";

  /** Region label → live SessionLabel — used to mark the active region's
   *  watermark with a brighter tint so the user knows where the pulse
   *  sits in the broader day. */
  const REGION_TO_SESSION: Record<string, SessionLabel> = {
    "盘前": "pre",
    "盘中": "regular",
    "盘后": "post",
    "夜盘": "overnight",
  };

  return (
    <div ref={containerRef} className={rootClass}>
      {/* Per-region watermark labels (HTML overlay — SVG <text> would get
        * squashed by preserveAspectRatio="none"). Each label sits at the
        * midpoint of its slot range. Vertical dashed dividers separate
        * consecutive regions so the user can read the day structure. */}
      {win.regions.map((region, i) => {
        const startPct = (region.startSlot / win.slotCount) * 100;
        const midPct = ((region.startSlot + region.endSlot) / 2 / win.slotCount) * 100;
        const isActiveRegion =
          !isClosed && REGION_TO_SESSION[region.label] === session;
        return (
          <span key={region.label}>
            {i > 0 && (
              <span
                className="ispark-divider"
                style={{ left: `${startPct}%` }}
                aria-hidden
              />
            )}
            <span
              className={`ispark-region-label ${isActiveRegion ? "active" : ""}`}
              style={{ left: `${midPct}%` }}
              aria-hidden
            >
              {region.label}
            </span>
          </span>
        );
      })}
      <svg className="ispark-svg" viewBox={`0 0 ${VB_W} ${VB_H}`} preserveAspectRatio="none">
        {areaPath && <path className="ispark-area" d={areaPath} fill={`url(#${fillId})`} />}
        {linePath && (
          <path
            className="ispark-line"
            d={linePath}
            vectorEffect="non-scaling-stroke"
          />
        )}
      </svg>
      {pulse && (
        <span
          className="ispark-pulse"
          style={{ left: `${pulse.x}px`, top: `${pulse.y}px` }}
          aria-hidden
        />
      )}
    </div>
  );
}
