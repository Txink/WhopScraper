import { describe, it, expect } from "vitest";
import { computeDragZoom, computeWheelPan } from "./chartGestures";

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
