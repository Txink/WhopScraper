/**
 * Detail-chart gesture handler. Disables chartjs-plugin-zoom's built-in
 * drag-pan + wheel/pinch zoom and replaces them with:
 *   - single-pointer horizontal drag → zoom (pivot at drag start)
 *   - wheel / two-pointer drag → horizontal pan of timeline
 *
 * Pure math (`computeDragZoom`, `computeWheelPan`) is extracted so the
 * gesture logic can be tested without a real Chart instance; the DOM glue
 * (`attachChartGestures`) is the thin wrapper that wires events to a chart.
 */

/** Pixels of horizontal movement before drag-zoom kicks in. Matches the
 *  threshold the old plugin-pan used so clicks/taps don't trigger. */
export const DRAG_THRESHOLD_PX = 4;

/** Pixels of horizontal drag for an e-fold (≈ 2.718×) zoom. ~140px → 2×,
 *  ~280px → 4×. Picked by feel — small enough that fine adjustments work,
 *  large enough that an accidental flick doesn't blast the range. */
export const DRAG_SENSITIVITY_PX = 200;

export interface DragZoomInput {
  /** Pixel X of the pointerdown that started this drag. */
  startPx: number;
  /** Current pixel X of the pointer. */
  currentPx: number;
  /** x-scale's `.min` at pointerdown time (data-index units). */
  startMin: number;
  /** x-scale's `.max` at pointerdown time (data-index units). */
  startMax: number;
  /** Data index under `startPx` at pointerdown time. Used as the pivot —
   *  it stays under `startPx` as the zoom factor changes. */
  startIdx: number;
  /** Range / data-length limits to clamp against. */
  limits: { dataLen: number; minRange: number; maxRange?: number };
}

export interface DragZoomResult {
  newMin: number;
  newMax: number;
}

/** Compute the new x-scale range for a drag-zoom in progress. Returns null
 *  if the gesture hasn't moved past the threshold yet. */
export function computeDragZoom(input: DragZoomInput): DragZoomResult | null {
  const dx = input.currentPx - input.startPx;
  if (Math.abs(dx) < DRAG_THRESHOLD_PX) return null;

  const factor = Math.exp(dx / DRAG_SENSITIVITY_PX);
  const startWidth = input.startMax - input.startMin;
  let newWidth = startWidth / factor;

  // Width clamps (per-view minRange + optional maxRange from viewCfg limits).
  if (newWidth < input.limits.minRange) newWidth = input.limits.minRange;
  if (input.limits.maxRange != null && newWidth > input.limits.maxRange) {
    newWidth = input.limits.maxRange;
  }

  // Anchor the data index under startPx to its starting fraction of the
  // visible range — that index should map back to startPx after the zoom.
  const startFrac = (input.startIdx - input.startMin) / startWidth;
  let newMin = input.startIdx - startFrac * newWidth;
  let newMax = newMin + newWidth;

  // Bound to loaded data range. If we hit the right edge, slide the window
  // left; if we then underflow on the left, clamp to 0.
  const dataMax = input.limits.dataLen - 1;
  if (newMax > dataMax) {
    newMax = dataMax;
    newMin = newMax - newWidth;
  }
  if (newMin < 0) {
    newMin = 0;
    newMax = Math.min(dataMax, newMin + newWidth);
  }

  return { newMin, newMax };
}
