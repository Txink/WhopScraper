/**
 * Single source of truth mapping each chart `view` to its data-fetch
 * parameters and render shape. Consumed by:
 *   - DetailPane (fetch effect: derives api.candlesticks args)
 *   - DetailChart (dataset type, plugin gating, initial scale window, live tick)
 *
 * Adding a new view = adding a row here + a tab button + (maybe) a sub-config
 * field on the detailView store. The chart component does NOT branch on view
 * name directly; it reads off ViewConfig.
 */

import type { Period } from "../../stores/candlesticks";

export type ViewType =
  | "intraday" | "minute" | "multiday"
  | "day" | "week" | "month" | "year";

export type IntradaySession = "regular" | "pre" | "post" | "overnight" | "all";
export type MinuteGranularity = "1min" | "2min" | "3min" | "5min";
export type MultidayWindow = 5 | 7;
/** Which K-line granularity the日K tab popover is set to. The four
 *  ``ViewType``s (day/week/month/year) share a single UI tab; this
 *  remembers which one is selected so navigating away and back
 *  restores the user's choice. */
export type DayKGranularity = "day" | "week" | "month" | "year";

export interface ViewSubState {
  intradaySessions: IntradaySession;
  minuteGranularity: MinuteGranularity;
  multidayWindow: MultidayWindow;
  dayKGranularity: DayKGranularity;
}

export interface LiveCfg {
  periodMinutes: number;
  /** today/today-like views can grow new bars at boundaries; 5/7-day
   *  stitched line never does (the backend ships a fresh window when the
   *  user re-opens the view). */
  allowAppend: boolean;
}

export interface ViewConfig {
  /** Maps to the backend `period` query param. */
  period: Period;
  /** Only sent to the backend when `period === "today"`. */
  granularity?: "分时" | "1min" | "2min" | "3min" | "5min";
  /** Only sent to the backend when `period === "today"`. */
  sessions?: IntradaySession;
  /** Drives Chart.js dataset `type` and tooltip / scale shape. */
  datasetType: "line" | "candlestick";
  /** Default visible-x window when the chart first mounts. User can pinch/pan
   *  beyond this within the loaded `bars.length`. For line views = full data. */
  initialVisibleCount: number;
  /** `null` ⇒ no live updates (K-line views). */
  liveCfg: LiveCfg | null;
  /** Enable the dim "盘前/盘中/盘后" wash + dividers — intraday only. */
  sessionBgEnabled: boolean;
  /** Enable vertical day-separator guides — multiday line only. */
  dayMarkersEnabled: boolean;
  /** Render the blinking dot at the latest price. Only the intraday line
   *  view shows it; minute/multiday still drive live ticks but suppress
   *  the visual since their bars carry the same "most recent" cue. */
  livePulseEnabled: boolean;
}

const _MINUTE_LIVE: Record<MinuteGranularity, number> = {
  "1min": 1, "2min": 2, "3min": 3, "5min": 5,
};

export function resolveViewConfig(view: ViewType, sub: ViewSubState): ViewConfig {
  switch (view) {
    case "intraday":
      return {
        period: "today",
        granularity: "分时",
        sessions: sub.intradaySessions,
        datasetType: "line",
        initialVisibleCount: Number.POSITIVE_INFINITY,
        liveCfg: { periodMinutes: 1, allowAppend: true },
        sessionBgEnabled: true,
        dayMarkersEnabled: false,
        livePulseEnabled: true,
      };
    case "minute":
      return {
        period: "today",
        granularity: sub.minuteGranularity,
        // Always fetch the full session range — pre + regular + post +
        // overnight — so the minute candle view shows the whole trading
        // day without a session-picker. (Intraday still exposes the
        // picker for the line view, where switching sessions is the way
        // to zoom into a single period.)
        sessions: "all",
        datasetType: "candlestick",
        initialVisibleCount: 80,
        liveCfg: { periodMinutes: _MINUTE_LIVE[sub.minuteGranularity], allowAppend: true },
        sessionBgEnabled: false,
        dayMarkersEnabled: false,
        livePulseEnabled: false,
      };
    case "multiday":
      return {
        period: sub.multidayWindow === 7 ? "7" : "5",
        datasetType: "line",
        initialVisibleCount: Number.POSITIVE_INFINITY,
        liveCfg: { periodMinutes: 5, allowAppend: false },
        sessionBgEnabled: false,
        dayMarkersEnabled: true,
        livePulseEnabled: false,
      };
    case "day":
      return _candleConfig("day", 80);
    case "week":
      return _candleConfig("week", 52);
    case "month":
      return _candleConfig("month", 36);
    case "year":
      return _candleConfig("year", 20);
  }
}

function _candleConfig(period: Period, initialVisibleCount: number): ViewConfig {
  return {
    period,
    datasetType: "candlestick",
    initialVisibleCount,
    liveCfg: null,
    sessionBgEnabled: false,
    dayMarkersEnabled: false,
    livePulseEnabled: false,
  };
}
