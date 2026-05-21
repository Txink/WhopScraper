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
  if (input.limits.maxRange !== undefined && newWidth > input.limits.maxRange) {
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

export interface WheelInput {
  deltaX: number;
  deltaY: number;
}

/** Map a wheel event's delta to a horizontal pan pixel amount that gets
 *  fed to `chart.pan({x: ...})`. Trackpad horizontal scroll (deltaX) wins
 *  when present; otherwise vertical wheel/scroll falls back to deltaY.
 *
 *  Sign convention: positive return value pans the view toward older
 *  bars (left) — chartjs-plugin-zoom's `chart.pan({x: +n})` shifts the
 *  data right relative to the chart area, which presents as the view
 *  moving left. */
export function computeWheelPan(input: WheelInput): number {
  if (input.deltaX !== 0) return input.deltaX;
  return input.deltaY;
}

/** Subset of the Chart.js + chartjs-plugin-zoom surface we depend on.
 *  Defined as an interface so unit tests can pass a fake. */
export interface GestureChart {
  scales: {
    x: {
      min: number;
      max: number;
      getValueForPixel: (px: number) => number | undefined;
    };
  };
  zoomScale: (
    scaleId: string,
    range: { min: number; max: number },
    transition?: string,
  ) => void;
  pan: (
    amount: { x?: number; y?: number },
    scales?: unknown,
    mode?: string,
  ) => void;
}

export interface AttachOpts {
  /** When false, attach a no-op (no listeners). Per-view gate. */
  enabled: boolean;
  /** Current loaded-bar count. Used to clamp drag-zoom against dataMax. */
  dataLen: number;
  /** Min/max range limits passed through to `computeDragZoom`. */
  limits: { minRange: number; maxRange?: number };
  /** Bar-index threshold near 0 below which `onNeedOlder` fires. */
  panBackThreshold: number;
  /** Fired after any pan/zoom action — parent uses this to set its
   *  isZoomed flag (drives the reset-button visibility). */
  onAction?: () => void;
  /** Fired when pan/zoom-out brings the visible window's min within
   *  `panBackThreshold` of bar 0. Parent fetches older bars. */
  onNeedOlder?: () => void;
}

/** Attach gesture handlers to `canvas` that drive `chart` per the new
 *  mapping (drag=zoom, wheel/multi-pointer=pan). Returns a teardown
 *  function that removes every listener it installed. Calling with
 *  `enabled: false` returns a no-op teardown. */
export function attachChartGestures(
  canvas: HTMLCanvasElement,
  chart: GestureChart,
  opts: AttachOpts,
): () => void {
  if (!opts.enabled) return () => {};

  // Active pointers — used to switch between drag-zoom (1 pointer) and
  // pan (2 pointers). Map pointerId → last clientX.
  const pointers = new Map<number, number>();

  // Drag-zoom state — captured on the first pointerdown.
  let dragState: {
    startPx: number;
    startMin: number;
    startMax: number;
    startIdx: number;
  } | null = null;

  // Pan state — center X across active pointers, captured when we enter
  // multi-pointer mode.
  let panCenterX: number | null = null;

  // jsdom doesn't compute offsetX (no layout), and even in real browsers
  // a canvas offset only matches clientX if it's at the viewport origin.
  // Always derive the canvas-local X via getBoundingClientRect.
  const getCanvasX = (clientX: number): number => {
    const rect = canvas.getBoundingClientRect();
    return clientX - rect.left;
  };

  const checkNeedOlder = () => {
    if (chart.scales.x.min <= opts.panBackThreshold) {
      opts.onNeedOlder?.();
    }
  };

  const onPointerDown = (e: PointerEvent) => {
    canvas.setPointerCapture?.(e.pointerId);
    pointers.set(e.pointerId, e.clientX);
    if (pointers.size === 1) {
      const startPx = getCanvasX(e.clientX);
      const startIdx = chart.scales.x.getValueForPixel(startPx);
      if (startIdx == null || !Number.isFinite(startIdx)) {
        dragState = null;
        return;
      }
      dragState = {
        startPx,
        startMin: chart.scales.x.min,
        startMax: chart.scales.x.max,
        startIdx,
      };
    } else if (pointers.size === 2) {
      // Switching from drag-zoom to pan — abandon any in-progress drag.
      dragState = null;
      const xs = Array.from(pointers.values());
      panCenterX = (xs[0]! + xs[1]!) / 2;
    }
  };

  const onPointerMove = (e: PointerEvent) => {
    if (!pointers.has(e.pointerId)) return;
    pointers.set(e.pointerId, e.clientX);

    if (pointers.size === 1 && dragState) {
      const out = computeDragZoom({
        startPx: dragState.startPx,
        currentPx: getCanvasX(e.clientX),
        startMin: dragState.startMin,
        startMax: dragState.startMax,
        startIdx: dragState.startIdx,
        limits: {
          dataLen: opts.dataLen,
          minRange: opts.limits.minRange,
          maxRange: opts.limits.maxRange,
        },
      });
      if (out) {
        chart.zoomScale("x", { min: out.newMin, max: out.newMax }, "none");
        opts.onAction?.();
        checkNeedOlder();
      }
    } else if (pointers.size >= 2 && panCenterX != null) {
      const xs = Array.from(pointers.values());
      const newCenter = (xs[0]! + xs[1]!) / 2;
      const dx = newCenter - panCenterX;
      panCenterX = newCenter;
      if (Math.abs(dx) > 0) {
        chart.pan({ x: dx }, undefined, "none");
        opts.onAction?.();
        checkNeedOlder();
      }
    }
  };

  const endPointer = (e: PointerEvent) => {
    canvas.releasePointerCapture?.(e.pointerId);
    pointers.delete(e.pointerId);
    if (pointers.size === 0) {
      dragState = null;
      panCenterX = null;
    } else if (pointers.size === 1) {
      // Returning to single-pointer — abandon pan mode but don't auto-start
      // a new drag-zoom from mid-gesture. The user has to release and re-press.
      panCenterX = null;
      dragState = null;
    }
  };

  const onWheel = (e: WheelEvent) => {
    e.preventDefault();
    const panAmount = computeWheelPan({ deltaX: e.deltaX, deltaY: e.deltaY });
    if (panAmount === 0) return;
    chart.pan({ x: panAmount }, undefined, "none");
    opts.onAction?.();
    checkNeedOlder();
  };

  canvas.addEventListener("pointerdown", onPointerDown);
  canvas.addEventListener("pointermove", onPointerMove);
  canvas.addEventListener("pointerup", endPointer);
  canvas.addEventListener("pointercancel", endPointer);
  // passive: false so preventDefault works (otherwise the page scrolls).
  canvas.addEventListener("wheel", onWheel, { passive: false });

  return () => {
    canvas.removeEventListener("pointerdown", onPointerDown);
    canvas.removeEventListener("pointermove", onPointerMove);
    canvas.removeEventListener("pointerup", endPointer);
    canvas.removeEventListener("pointercancel", endPointer);
    canvas.removeEventListener("wheel", onWheel);
    pointers.clear();
    dragState = null;
    panCenterX = null;
  };
}
