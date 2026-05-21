import { describe, it, expect, vi } from "vitest";
import { computeDragZoom, computeWheelPan, attachChartGestures, type GestureChart } from "./chartGestures";

describe("computeDragZoom", () => {
  const baseLimits = { dataLen: 1000, minRange: 5, maxRange: 250 };

  it("returns null when |Δx| < 4 (threshold)", () => {
    const out = computeDragZoom({
      startPx: 100, currentPx: 102,
      startMin: 100, startMax: 200, startIdx: 150,
      limits: baseLimits,
    });
    expect(out).toBeNull();
  });

  it("drag right by 140px ≈ 2× zoom-in (window halves)", () => {
    const out = computeDragZoom({
      startPx: 100, currentPx: 240,
      startMin: 100, startMax: 200, startIdx: 150,
      limits: baseLimits,
    });
    expect(out).not.toBeNull();
    const width = out!.newMax - out!.newMin;
    // exp(140/200) ≈ 2.0138 → width ≈ 100/2.0138 ≈ 49.66
    expect(width).toBeGreaterThan(48);
    expect(width).toBeLessThan(52);
  });

  it("drag left by 140px ≈ 0.5× zoom-out (window doubles)", () => {
    const out = computeDragZoom({
      startPx: 100, currentPx: -40,
      startMin: 100, startMax: 200, startIdx: 150,
      limits: baseLimits,
    });
    expect(out).not.toBeNull();
    const width = out!.newMax - out!.newMin;
    // exp(-140/200) ≈ 0.4966 → width ≈ 100/0.4966 ≈ 201.4
    expect(width).toBeGreaterThan(195);
    expect(width).toBeLessThan(210);
  });

  it("pivot invariant: startIdx stays at its starting fraction across the new range", () => {
    // startIdx is exactly in the middle of [100, 200]
    const out = computeDragZoom({
      startPx: 100, currentPx: 240,
      startMin: 100, startMax: 200, startIdx: 150,
      limits: baseLimits,
    })!;
    // After zoom, startIdx (150) should still be at fraction 0.5 of the new range
    const frac = (150 - out.newMin) / (out.newMax - out.newMin);
    expect(frac).toBeCloseTo(0.5, 5);
  });

  it("pivot invariant: off-center pivot stays at same fraction", () => {
    // startIdx at 80% of the original range
    const out = computeDragZoom({
      startPx: 100, currentPx: 240,
      startMin: 100, startMax: 200, startIdx: 180,
      limits: baseLimits,
    })!;
    const frac = (180 - out.newMin) / (out.newMax - out.newMin);
    expect(frac).toBeCloseTo(0.8, 5);
  });

  it("clamps to minRange when zooming in past the limit", () => {
    const out = computeDragZoom({
      startPx: 0, currentPx: 1000,  // huge factor
      startMin: 100, startMax: 200, startIdx: 150,
      limits: baseLimits,
    })!;
    expect(out.newMax - out.newMin).toBeCloseTo(5, 5);
  });

  it("clamps to maxRange when zooming out past the limit", () => {
    const out = computeDragZoom({
      startPx: 0, currentPx: -1000,
      startMin: 100, startMax: 200, startIdx: 150,
      limits: baseLimits,
    })!;
    expect(out.newMax - out.newMin).toBeCloseTo(250, 5);
  });

  it("clamps to dataLen-1 when zooming out near the right edge", () => {
    const out = computeDragZoom({
      startPx: 0, currentPx: -200,
      startMin: 900, startMax: 999, startIdx: 990,
      limits: { dataLen: 1000, minRange: 5 },  // no maxRange
    })!;
    // startWidth=99, startFrac=(990-900)/99≈0.909, factor=exp(-1)≈0.368,
    // newWidth≈269 → newMax≈1014.5 → right-clamp: newMax=999, newMin≈730
    expect(out.newMax).toBe(999);
    expect(out.newMin).toBeCloseTo(730, 0);
  });

  it("clamps to 0 when zooming out near the left edge", () => {
    const out = computeDragZoom({
      startPx: 0, currentPx: -200,
      startMin: 0, startMax: 100, startIdx: 10,
      limits: { dataLen: 1000, minRange: 5 },
    })!;
    // startWidth=100, startFrac=0.1, factor=exp(-1)≈0.368,
    // newWidth≈272 → newMin≈-17.2 → left-clamp: newMin=0, newMax≈272
    expect(out.newMin).toBe(0);
    expect(out.newMax).toBeCloseTo(272, 0);
  });
});

describe("computeWheelPan", () => {
  it("uses deltaX when non-zero (trackpad horizontal scroll)", () => {
    // deltaX > 0 = page scrolls right = chart view shifts right → positive pan x
    expect(computeWheelPan({ deltaX: 30, deltaY: 0 })).toBe(30);
    expect(computeWheelPan({ deltaX: -30, deltaY: 0 })).toBe(-30);
  });

  it("falls back to deltaY when deltaX is 0 (mouse wheel)", () => {
    // deltaY > 0 = wheel scrolled down → view moves toward older bars (left)
    // → chart.pan({x: +deltaY}) (positive pan x shifts data right under view = view shifts left)
    expect(computeWheelPan({ deltaX: 0, deltaY: 100 })).toBe(100);
    expect(computeWheelPan({ deltaX: 0, deltaY: -100 })).toBe(-100);
  });

  it("prefers deltaX over deltaY when both present", () => {
    expect(computeWheelPan({ deltaX: 10, deltaY: 100 })).toBe(10);
  });
});

function makeFakeChart(): {
  chart: GestureChart;
  zoomScale: ReturnType<typeof vi.fn>;
  pan: ReturnType<typeof vi.fn>;
} {
  const zoomScale = vi.fn();
  const pan = vi.fn();
  const chart: GestureChart = {
    scales: {
      x: {
        min: 100, max: 200,
        getValueForPixel: (px: number) => {
          // Linear: px 0→100, px 400→200
          return 100 + (px / 400) * 100;
        },
      },
    },
    zoomScale,
    pan,
  };
  return { chart, zoomScale, pan };
}

function pointer(type: string, x: number, opts: Partial<PointerEventInit> = {}): PointerEvent {
  return new PointerEvent(type, {
    pointerId: opts.pointerId ?? 1,
    clientX: x,
    clientY: 0,
    bubbles: true,
    cancelable: true,
    ...opts,
  });
}

describe("attachChartGestures", () => {
  it("noop when enabled: false (no chart calls on pointer events)", () => {
    const canvas = document.createElement("canvas");
    document.body.appendChild(canvas);
    const { chart, zoomScale, pan } = makeFakeChart();
    const detach = attachChartGestures(canvas, chart, {
      enabled: false,
      dataLen: () => 1000,
      limits: { minRange: 5, maxRange: 250 },
      panBackThreshold: 20,
    });
    canvas.dispatchEvent(pointer("pointerdown", 100));
    canvas.dispatchEvent(pointer("pointermove", 240));
    canvas.dispatchEvent(pointer("pointerup", 240));
    expect(zoomScale).not.toHaveBeenCalled();
    expect(pan).not.toHaveBeenCalled();
    detach();
    canvas.remove();
  });

  it("single-pointer horizontal drag calls zoomScale on the x axis", () => {
    const canvas = document.createElement("canvas");
    document.body.appendChild(canvas);
    const { chart, zoomScale } = makeFakeChart();
    const onAction = vi.fn();
    const detach = attachChartGestures(canvas, chart, {
      enabled: true,
      dataLen: () => 1000,
      limits: { minRange: 5, maxRange: 250 },
      panBackThreshold: 20,
      onAction,
    });

    canvas.dispatchEvent(pointer("pointerdown", 100));
    canvas.dispatchEvent(pointer("pointermove", 240));  // +140px → ~2× zoom in
    expect(zoomScale).toHaveBeenCalled();
    const call = zoomScale.mock.calls[zoomScale.mock.calls.length - 1];
    expect(call[0]).toBe("x");
    const range = call[1] as { min: number; max: number };
    const width = range.max - range.min;
    expect(width).toBeGreaterThan(48);
    expect(width).toBeLessThan(52);

    canvas.dispatchEvent(pointer("pointerup", 240));
    expect(onAction).toHaveBeenCalled();
    detach();
    canvas.remove();
  });

  it("wheel event calls chart.pan({x: ...}) and preventDefaults", () => {
    const canvas = document.createElement("canvas");
    document.body.appendChild(canvas);
    const { chart, pan } = makeFakeChart();
    const onAction = vi.fn();
    const detach = attachChartGestures(canvas, chart, {
      enabled: true,
      dataLen: () => 1000,
      limits: { minRange: 5, maxRange: 250 },
      panBackThreshold: 20,
      onAction,
    });

    const wheel = new WheelEvent("wheel", {
      deltaX: 0, deltaY: 50,
      bubbles: true, cancelable: true,
    });
    canvas.dispatchEvent(wheel);
    expect(pan).toHaveBeenCalledWith({ x: 50 }, undefined, "none");
    expect(wheel.defaultPrevented).toBe(true);
    expect(onAction).toHaveBeenCalled();
    detach();
    canvas.remove();
  });

  it("two simultaneous pointers switch to pan mode (center delta per event)", () => {
    const canvas = document.createElement("canvas");
    document.body.appendChild(canvas);
    const { chart, zoomScale, pan } = makeFakeChart();
    const detach = attachChartGestures(canvas, chart, {
      enabled: true,
      dataLen: () => 1000,
      limits: { minRange: 5, maxRange: 250 },
      panBackThreshold: 20,
    });

    canvas.dispatchEvent(pointer("pointerdown", 100, { pointerId: 1 }));
    canvas.dispatchEvent(pointer("pointerdown", 200, { pointerId: 2 }));
    // After the 2nd pointerdown, the in-progress drag-zoom is abandoned.
    expect(zoomScale).not.toHaveBeenCalled();

    // Pointer 1 alone moves +20 → center moves +10 (other finger unchanged).
    canvas.dispatchEvent(pointer("pointermove", 120, { pointerId: 1 }));
    expect(pan).toHaveBeenCalledTimes(1);
    expect((pan.mock.calls[0]![0] as { x: number }).x).toBeCloseTo(10, 1);

    // Pointer 2 alone moves +20 → center moves another +10.
    canvas.dispatchEvent(pointer("pointermove", 220, { pointerId: 2 }));
    expect(pan).toHaveBeenCalledTimes(2);
    expect((pan.mock.calls[1]![0] as { x: number }).x).toBeCloseTo(10, 1);

    // Cumulative pan = 20px, matching "both fingers moved 20px right".
    canvas.dispatchEvent(pointer("pointerup", 120, { pointerId: 1 }));
    canvas.dispatchEvent(pointer("pointerup", 220, { pointerId: 2 }));
    detach();
    canvas.remove();
  });

  it("fires onNeedOlder when post-zoom min ≤ panBackThreshold", () => {
    const canvas = document.createElement("canvas");
    document.body.appendChild(canvas);
    const { chart, zoomScale } = makeFakeChart();
    // Chart starts already near the left edge so a zoom-out pushes min to 0.
    chart.scales.x.min = 20;
    chart.scales.x.max = 80;
    chart.scales.x.getValueForPixel = (px: number) => 20 + (px / 400) * 60;

    // Mirror zoomScale into the scale so the post-action check sees fresh min.
    let installedMin = chart.scales.x.min;
    zoomScale.mockImplementation((_id, range) => {
      installedMin = range.min;
      chart.scales.x.min = range.min;
      chart.scales.x.max = range.max;
    });
    const onNeedOlder = vi.fn();
    const detach = attachChartGestures(canvas, chart, {
      enabled: true,
      dataLen: () => 1000,
      limits: { minRange: 5, maxRange: 250 },
      panBackThreshold: 20,
      onNeedOlder,
    });

    // pointerdown at px 200 → startIdx = 50 (middle of [20,80])
    canvas.dispatchEvent(pointer("pointerdown", 200));
    // Drag far left → big zoom-out, window clamps to maxRange 250 and pivots
    // around startIdx 50 with fraction 0.5 → newMin = 50 - 125 = -75 → clamp 0.
    canvas.dispatchEvent(pointer("pointermove", -1000));
    expect(onNeedOlder).toHaveBeenCalled();
    expect(installedMin).toBeLessThanOrEqual(20);

    canvas.dispatchEvent(pointer("pointerup", -1000));
    detach();
    canvas.remove();
  });

  it("detach removes listeners (no chart calls after teardown)", () => {
    const canvas = document.createElement("canvas");
    document.body.appendChild(canvas);
    const { chart, zoomScale } = makeFakeChart();
    const detach = attachChartGestures(canvas, chart, {
      enabled: true,
      dataLen: () => 1000,
      limits: { minRange: 5, maxRange: 250 },
      panBackThreshold: 20,
    });
    detach();
    canvas.dispatchEvent(pointer("pointerdown", 100));
    canvas.dispatchEvent(pointer("pointermove", 240));
    expect(zoomScale).not.toHaveBeenCalled();
    canvas.remove();
  });

  it("reads dataLen via getter on each pointer event (lazy, not cached)", () => {
    const canvas = document.createElement("canvas");
    document.body.appendChild(canvas);
    const { chart, zoomScale } = makeFakeChart();
    let liveLen = 100;
    const detach = attachChartGestures(canvas, chart, {
      enabled: true,
      dataLen: () => liveLen,
      limits: { minRange: 5 },  // no maxRange so the data bound is what clamps
      panBackThreshold: 0,
    });

    // Start the drag with dataLen=100 — right-edge clamp would be index 99.
    canvas.dispatchEvent(pointer("pointerdown", 100));
    canvas.dispatchEvent(pointer("pointermove", -200));  // zoom out
    // Mutate len AFTER the first event. A cached attach-time read would
    // continue to clamp at 99; a lazy per-event read picks up the new bound.
    liveLen = 500;
    canvas.dispatchEvent(pointer("pointermove", -400));  // zoom out further

    // The last zoomScale call should reflect the updated dataLen by allowing
    // newMax to exceed 99. If dataLen were cached at attach time, newMax
    // would be clamped to 99.
    expect(zoomScale).toHaveBeenCalled();
    const lastCall = zoomScale.mock.calls[zoomScale.mock.calls.length - 1];
    const range = lastCall[1] as { min: number; max: number };
    expect(range.max).toBeGreaterThan(99);

    canvas.dispatchEvent(pointer("pointerup", -400));
    detach();
    canvas.remove();
  });
});
