import { useEffect } from "react";

/** Sets --rail-top CSS var to FULL when topbar visible, MIN once scrolled past. */
export function useStickyTop({ topbarHeight = 48, pad = 16 }: { topbarHeight?: number; pad?: number } = {}) {
  useEffect(() => {
    const full = topbarHeight + pad;
    const min = pad;
    const update = () => {
      const y = window.scrollY || 0;
      const top = Math.max(min, full - y);
      document.documentElement.style.setProperty("--rail-top", `${top}px`);
    };
    update();
    window.addEventListener("scroll", update, { passive: true });
    window.addEventListener("resize", update);
    return () => {
      window.removeEventListener("scroll", update);
      window.removeEventListener("resize", update);
    };
  }, [topbarHeight, pad]);
}
