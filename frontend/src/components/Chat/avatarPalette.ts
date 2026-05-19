/** 8-color palette covering the saturated end of the project's accent
 *  tokens (brand cyan, ok green, info blue, warn amber, plus purple /
 *  red / orange / teal) so each watched sender gets a distinct avatar
 *  background in 关注模式 + 过滤模式. Color choice is a deterministic
 *  hash of the author's name — same name always gets the same color
 *  across renders, sessions, and the two view modes. */
const AVATAR_PALETTE = [
  "#3fb5c5", // brand cyan
  "#3dd68c", // ok green
  "#5aa0ff", // info blue
  "#e7a73d", // warn amber
  "#c688ff", // purple (option-type accent)
  "#ef5b5b", // err red
  "#ff8c52", // orange
  "#5fd1c1", // teal
];

export function paletteColorFor(name: string): string {
  let h = 0;
  for (let i = 0; i < name.length; i++) h = (h * 31 + name.charCodeAt(i)) >>> 0;
  return AVATAR_PALETTE[h % AVATAR_PALETTE.length];
}
