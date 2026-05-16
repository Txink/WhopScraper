/**
 * Global SVG <defs> for IntradaySpark gradients. Mounted once by
 * PositionsPanel so every spark instance references the same gradient
 * ids — avoids id collisions + DOM bloat that per-instance defs would
 * cause.
 *
 * Colors track ``--up-color`` / ``--down-color`` CSS vars, so the color
 * mode preference (US green-up vs CN red-up) flows through without JS.
 */
export function SparkDefs() {
  return (
    <svg
      width="0"
      height="0"
      style={{ position: "absolute", pointerEvents: "none" }}
      aria-hidden
    >
      <defs>
        <linearGradient id="ispark-fill-up" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="var(--up-color)" stopOpacity="0.22" />
          <stop offset="100%" stopColor="var(--up-color)" stopOpacity="0" />
        </linearGradient>
        <linearGradient id="ispark-fill-down" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="var(--down-color)" stopOpacity="0.22" />
          <stop offset="100%" stopColor="var(--down-color)" stopOpacity="0" />
        </linearGradient>
      </defs>
    </svg>
  );
}
