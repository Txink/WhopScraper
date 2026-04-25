"""WhopBrowser — Playwright wrapper for Whop session management."""
from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Literal

from playwright.async_api import Browser, BrowserContext, Page, Playwright, async_playwright

from app.whop.login import load_cookie_state, save_cookie_state

logger = logging.getLogger(__name__)

_WaitUntil = Literal["commit", "domcontentloaded", "load", "networkidle"]


class WhopBrowser:
    """Async Playwright wrapper. Single-page scope; load cookie at start, save on close."""

    def __init__(
        self,
        *,
        headless: bool = False,
        slow_mo: float = 0.0,
        viewport: tuple[int, int] = (1280, 800),
        cookie_path: str | None = None,
    ) -> None:
        self._headless = headless
        self._slow_mo = slow_mo
        self._viewport = viewport
        self._cookie_path = cookie_path

        self._pw: Playwright | None = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None

    async def start(self) -> Page:
        """Launch Chromium, create context with saved cookies if any, return a Page."""
        self._pw = await async_playwright().start()
        self._browser = await self._pw.chromium.launch(
            headless=self._headless, slow_mo=int(self._slow_mo * 1000)
        )

        cookie = load_cookie_state(Path(self._cookie_path) if self._cookie_path else None)

        ctx_kwargs: dict[str, Any] = {
            "viewport": {"width": self._viewport[0], "height": self._viewport[1]}
        }
        if cookie is not None:
            ctx_kwargs["storage_state"] = cookie
        self._context = await self._browser.new_context(**ctx_kwargs)

        self._page = await self._context.new_page()
        return self._page

    async def navigate(
        self,
        url: str,
        *,
        wait_until: _WaitUntil = "networkidle",
        timeout_ms: int = 30000,
    ) -> bool:
        """Navigate to URL. Returns True if no exception."""
        if self._page is None:
            raise RuntimeError("WhopBrowser not started")
        try:
            await self._page.goto(url, wait_until=wait_until, timeout=timeout_ms)
            return True
        except Exception as e:
            logger.warning("navigate failed: %s", e)
            return False

    async def is_logged_in(self, url: str) -> bool:
        """Heuristic: navigate, check current URL doesn't contain '/login'."""
        if self._page is None:
            raise RuntimeError("WhopBrowser not started")
        ok = await self.navigate(url)
        if not ok:
            return False
        cur = self._page.url
        return "/login" not in cur

    async def scrape_html(self) -> str:
        """Return current page DOM HTML (the inner of <html>)."""
        if self._page is None:
            raise RuntimeError("WhopBrowser not started")
        return await self._page.content()

    async def scroll_load_history(self, *, factor: float = 5.0, pause_ms: int = 400) -> None:
        """Scroll the page upward to trigger lazy-loading of older messages."""
        if self._page is None:
            raise RuntimeError("WhopBrowser not started")
        # Whop loads on scroll-up: simulate by scrolling to top, then back down to current
        for _ in range(int(factor)):
            await self._page.evaluate("window.scrollTo(0, 0)")
            await asyncio.sleep(pause_ms / 1000)

    async def save_cookie_state(self) -> None:
        """Save current context's cookies to disk for next start()."""
        if self._context is None:
            return
        state = await self._context.storage_state()
        # storage_state() returns a TypedDict that is dict-compatible
        save_cookie_state(state, Path(self._cookie_path) if self._cookie_path else None)  # type: ignore[arg-type]

    async def close(self) -> None:
        """Tear down resources. Idempotent."""
        try:
            if self._context is not None:
                # Save before close — best-effort
                try:
                    await self.save_cookie_state()
                except Exception as e:
                    logger.warning("save_cookie_state on close failed: %s", e)
                await self._context.close()
        finally:
            self._context = None
            self._page = None
            try:
                if self._browser is not None:
                    await self._browser.close()
            finally:
                self._browser = None
                if self._pw is not None:
                    await self._pw.stop()
                    self._pw = None


@asynccontextmanager
async def whop_session(
    *,
    headless: bool = False,
    cookie_path: str | None = None,
) -> AsyncIterator[WhopBrowser]:
    """Convenience context manager: start + yield + close."""
    browser = WhopBrowser(headless=headless, cookie_path=cookie_path)
    await browser.start()
    try:
        yield browser
    finally:
        await browser.close()
