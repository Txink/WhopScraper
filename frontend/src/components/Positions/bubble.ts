/**
 * Trade-marker speech bubble. Shape mirrors prototypes/bubble.svg —
 * rounded body with a tail attached to the bottom-LEFT, tip extending
 * down-and-slightly-right. The tip is the anchor point.
 *
 * Coords:
 *   (tipX, tipY) is where the tail tip lands.
 *   Body sits up-and-slightly-right of the tip:
 *     body_left   = tipX - TIP_INSET_FROM_BODY_LEFT
 *     body_bottom = tipY - TIP_BELOW_BODY
 *     body_top    = body_bottom - BODY_H
 */

const BODY_W = 11;
const BODY_H = 9;
const CORNER_R = 1.5;
/** Tail tip is INSET this far right of the body's left edge. */
const TIP_INSET_FROM_BODY_LEFT = 0.5;
/** Tail tip is this far below the body's bottom edge. */
const TIP_BELOW_BODY = 3;
/** Where the tail rejoins the body's bottom edge (x distance from body's left). */
const TAIL_REJOIN_X = 3;

export function drawBubble(
  ctx: CanvasRenderingContext2D,
  tipX: number,
  tipY: number,
  letter: string,
  color: string,
): void {
  const left = tipX - TIP_INSET_FROM_BODY_LEFT;
  const top = tipY - TIP_BELOW_BODY - BODY_H;
  const right = left + BODY_W;
  const bottom = top + BODY_H;

  ctx.save();
  ctx.fillStyle = color;
  ctx.beginPath();
  // Start at top-right corner curve start.
  ctx.moveTo(right - CORNER_R, top);
  // Top edge → top-left corner.
  ctx.lineTo(left + CORNER_R, top);
  ctx.quadraticCurveTo(left, top, left, top + CORNER_R);
  // Left edge continues STRAIGHT past body bottom into the tail.
  ctx.lineTo(left, bottom + (TIP_BELOW_BODY - 2));
  // Tail tip (small arc / corner).
  ctx.quadraticCurveTo(left, tipY, tipX, tipY);
  // Line back up-right to where tail rejoins body's bottom edge.
  ctx.lineTo(left + TAIL_REJOIN_X, bottom);
  // Bottom edge → bottom-right corner.
  ctx.lineTo(right - CORNER_R, bottom);
  ctx.quadraticCurveTo(right, bottom, right, bottom - CORNER_R);
  // Right edge → top-right corner.
  ctx.lineTo(right, top + CORNER_R);
  ctx.quadraticCurveTo(right, top, right - CORNER_R, top);
  ctx.closePath();
  ctx.fill();

  // Letter inside, white, bold. Center on the BODY (not including tail).
  ctx.fillStyle = "#ffffff";
  ctx.font = "700 7px -apple-system, system-ui, sans-serif";
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ctx.fillText(letter, (left + right) / 2, (top + bottom) / 2 + 0.5);
  ctx.restore();
}
