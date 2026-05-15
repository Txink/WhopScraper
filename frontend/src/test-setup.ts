import "@testing-library/jest-dom/vitest";

// Mock HammerJS at the global level before any modules that use it are loaded.
// Chart.js plugin zoom requires HammerJS, which tries to attach event listeners
// during initialization. This fails in jsdom because the document/window object
// is incomplete. We stub the global Hammer Manager before modules load.
globalThis.Hammer = undefined as any;
