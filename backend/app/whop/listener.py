"""WhopListener — periodic polling loop for a single Whop page.

Scrapes HTML via WhopBrowser, extracts messages via extract_messages,
and publishes ``message.received`` events to the EventBus for each new message.
Tracks seen message IDs in-process (no DB; restart = empty cache).
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
from datetime import UTC, datetime

from app.core.config import Settings
from app.core.event_bus import Event, EventBus
from app.core.events import MessagePayload, Topics
from app.whop.browser import WhopBrowser
from app.whop.extractor import extract_messages

logger = logging.getLogger(__name__)


def _is_placeholder_url(url: str | None) -> bool:
    """Detect known placeholder URLs that should be treated as 'no URL set'."""
    if not url:
        return True
    bad_tokens = ("/xxx/", "/yyy/", "example.com", "your-page-here")
    low = url.lower()
    return any(t in low for t in bad_tokens)


class WhopListener:
    """Polls a single Whop page URL, publishes new messages to bus."""

    def __init__(
        self,
        *,
        bus: EventBus,
        url: str,
        source: str,            # "stock" | "option"
        poll_interval: float = 2.0,
        headless: bool = False,
        cookie_path: str | None = None,
        skip_initial: bool = True,
    ) -> None:
        self._bus = bus
        self._url = url
        self._source = source
        self._poll_interval = poll_interval
        self._headless = headless
        self._cookie_path = cookie_path
        self._skip_initial = skip_initial

        self._browser: WhopBrowser | None = None
        self._task: asyncio.Task[None] | None = None
        self._seen: set[str] = set()
        self._stop_event = asyncio.Event()

        # Status fields (read via properties)
        self._messages_published: int = 0
        self._last_poll_at: datetime | None = None
        self._last_error: str | None = None
        self._started_at: datetime | None = None

    # ------------------------------------------------------------------ #
    # Read-only status properties                                          #
    # ------------------------------------------------------------------ #

    @property
    def messages_published(self) -> int:
        return self._messages_published

    @property
    def last_poll_at(self) -> datetime | None:
        return self._last_poll_at

    @property
    def last_error(self) -> str | None:
        return self._last_error

    @property
    def started_at(self) -> datetime | None:
        return self._started_at

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    @property
    def url(self) -> str:
        return self._url

    @property
    def source(self) -> str:
        return self._source

    async def start(self) -> None:
        """Launch browser, navigate, prime seen set (skip_initial=True), start polling task."""
        self._browser = WhopBrowser(headless=self._headless, cookie_path=self._cookie_path)
        await self._browser.start()

        ok = await self._browser.navigate(self._url)
        if not ok:
            await self._browser.close()
            self._browser = None
            raise RuntimeError(f"failed to navigate to {self._url}")

        if self._skip_initial:
            html = await self._browser.scrape_html()
            initial = extract_messages(html, source=self._source)  # type: ignore[arg-type]
            self._seen.update(m.id for m in initial)
            logger.info(
                "WhopListener[%s]: skipped %d initial messages",
                self._source,
                len(initial),
            )

        self._started_at = datetime.now(UTC)
        self._task = asyncio.create_task(self._loop())
        logger.info(
            "WhopListener[%s] started polling %s every %.1fs",
            self._source,
            self._url,
            self._poll_interval,
        )

    async def stop(self) -> None:
        """Signal stop, cancel task, close browser. Idempotent."""
        self._stop_event.set()
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._task
            self._task = None
        if self._browser is not None:
            try:
                await self._browser.close()
            except Exception as e:
                logger.warning("WhopListener[%s] close error: %s", self._source, e)
            self._browser = None

    async def _loop(self) -> None:
        """Main polling loop. Backoff on errors."""
        backoff = 1.0
        max_backoff = 30.0
        while not self._stop_event.is_set():
            try:
                await self._scan_once()
                backoff = 1.0
                # Sleep until next poll, or until stop_event fires
                try:
                    await asyncio.wait_for(self._stop_event.wait(), timeout=self._poll_interval)
                    return  # stop_event set during sleep
                except TimeoutError:
                    pass
            except asyncio.CancelledError:
                raise
            except Exception as e:
                self._last_error = str(e)
                logger.exception("WhopListener[%s] scan error: %s", self._source, e)
                # Exponential backoff
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, max_backoff)

    async def _scan_once(self) -> None:
        """One pass: scrape HTML, extract messages, publish new ones."""
        if self._browser is None:
            raise RuntimeError("browser not initialized")
        html = await self._browser.scrape_html()
        now = datetime.now(UTC)
        messages = extract_messages(html, source=self._source, received_at=now)  # type: ignore[arg-type]

        new_count = 0
        for msg in messages:
            if msg.id in self._seen:
                continue
            self._seen.add(msg.id)
            await self._bus.publish(Event(Topics.MESSAGE_RECEIVED, MessagePayload(message=msg)))
            new_count += 1

        self._last_poll_at = datetime.now(UTC)
        self._last_error = None

        if new_count > 0:
            self._messages_published += new_count
            logger.debug(
                "WhopListener[%s] published %d new (total seen %d)",
                self._source,
                new_count,
                len(self._seen),
            )


def register_whop_listeners(
    bus: EventBus,
    settings: Settings,
) -> list[WhopListener]:
    """Construct listener(s) based on settings.

    Returns a list of (unstarted) WhopListeners — one per configured URL.
    Caller is responsible for awaiting start() and storing references for stop().

    Returns empty list if no whop URLs are configured (graceful no-op for dev).
    """
    listeners: list[WhopListener] = []
    if not _is_placeholder_url(settings.whop_stock_url):
        listeners.append(
            WhopListener(
                bus=bus,
                url=settings.whop_stock_url,
                source="stock",
                poll_interval=settings.whop_poll_interval,
                headless=settings.whop_headless,
            )
        )
    else:
        logger.info("WHOP_STOCK_URL not configured (or placeholder) — skipping stock listener")
    if not _is_placeholder_url(settings.whop_option_url):
        listeners.append(
            WhopListener(
                bus=bus,
                url=settings.whop_option_url,
                source="option",
                poll_interval=settings.whop_poll_interval,
                headless=settings.whop_headless,
            )
        )
    else:
        logger.info("WHOP_OPTION_URL not configured (or placeholder) — skipping option listener")
    return listeners
