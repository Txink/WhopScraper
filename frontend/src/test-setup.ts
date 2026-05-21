import "@testing-library/jest-dom/vitest";

// jsdom 25 does not implement PointerEvent. Polyfill it as a thin subclass of
// MouseEvent so pointer-event dispatching works in gesture smoke tests.
if (typeof globalThis.PointerEvent === "undefined") {
  class PointerEventPolyfill extends MouseEvent {
    readonly pointerId: number;
    readonly pointerType: string;
    readonly isPrimary: boolean;
    constructor(type: string, init: PointerEventInit = {}) {
      super(type, init);
      this.pointerId = init.pointerId ?? 0;
      this.pointerType = init.pointerType ?? "mouse";
      this.isPrimary = init.isPrimary ?? true;
    }
  }
  globalThis.PointerEvent = PointerEventPolyfill as unknown as typeof PointerEvent;
}

// Mock HammerJS at the global level before any modules that use it are loaded.
// Chart.js plugin zoom requires HammerJS, which tries to attach event listeners
// during initialization. This fails in jsdom because the document/window object
// is incomplete. We stub the global Hammer Manager before modules load.
globalThis.Hammer = undefined as any;

// Polyfill for jsdom — IntradaySpark uses ResizeObserver to measure
// its container for pulse-dot positioning.
if (typeof globalThis.ResizeObserver === "undefined") {
  globalThis.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver;
}

// jsdom returns 0×0 for getBoundingClientRect — mock to a sensible
// fixed size so components that gate render on `containerSize.w > 0`
// (e.g. IntradaySpark's pulse dot) still render in tests.
if (typeof globalThis.Element !== "undefined") {
  const original = Element.prototype.getBoundingClientRect;
  Element.prototype.getBoundingClientRect = function () {
    const r = original?.call(this);
    if (r && r.width === 0 && r.height === 0) {
      return {
        x: 0, y: 0, width: 200, height: 60,
        top: 0, right: 200, bottom: 60, left: 0,
        toJSON: () => ({}),
      } as DOMRect;
    }
    return r ?? new DOMRect();
  };
}
