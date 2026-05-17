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

export interface ViewSubState {
  intradaySessions: IntradaySession;
  minuteGranularity: MinuteGranularity;
  multidayWindow: MultidayWindow;
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
      };
    case "minute":
      return {
        period: "today",
        granularity: sub.minuteGranularity,
        sessions: "regular",
        datasetType: "line",
        initialVisibleCount: Number.POSITIVE_INFINITY,
        liveCfg: { periodMinutes: _MINUTE_LIVE[sub.minuteGranularity], allowAppend: true },
        sessionBgEnabled: false,
        dayMarkersEnabled: false,
      };
    case "multiday":
      return {
        period: sub.multidayWindow === 7 ? "7" : "5",
        datasetType: "line",
        initialVisibleCount: Number.POSITIVE_INFINITY,
        liveCfg: { periodMinutes: 5, allowAppend: false },
        sessionBgEnabled: false,
        dayMarkersEnabled: true,
      };
    case "day":
      return _candleConfig("day" as Period, 60); // Cast until B4 reshapes Period to include day/week/month/year.
    case "week":
      return _candleConfig("week" as Period, 52); // Cast until B4 reshapes Period to include day/week/month/year.
    case "month":
      return _candleConfig("month" as Period, 36); // Cast until B4 reshapes Period to include day/week/month/year.
    case "year":
      return _candleConfig("year" as Period, 20); // Cast until B4 reshapes Period to include day/week/month/year.
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
  };
}
