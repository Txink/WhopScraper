"""Asyncio in-process pub/sub event bus with fan-out and failure isolation."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

Handler = Callable[["Event"], Awaitable[None]]


@dataclass(frozen=True)
class Event:
    """Immutable event payload container."""

    topic: str
    payload: Any  # handler interprets based on topic; typed per-subscription is caller's concern


class EventBus:
    """In-process async pub/sub.

    Design principles:
    - publish() is non-blocking and fire-and-forget: it schedules handlers
      via asyncio.create_task, returning immediately.
    - Handlers run concurrently on the event loop; no per-subscriber queue.
    - Failure isolation: if a handler raises, the exception is logged and
      does NOT propagate to the publisher or affect other handlers.
    - Back-pressure: none by default. If a subscriber is slow, background
      tasks accumulate (bounded only by process memory). A subscriber that
      needs back-pressure should implement its own queue+worker pattern.
    """

    def __init__(self) -> None:
        self._subscribers: dict[str, list[Handler]] = {}
        self._in_flight: set[asyncio.Task[None]] = set()

    def subscribe(self, topic: str, handler: Handler) -> Callable[[], None]:
        """Register handler for *topic*. Returns an unsubscribe callable."""
        self._subscribers.setdefault(topic, []).append(handler)

        def _unsubscribe() -> None:
            handlers = self._subscribers.get(topic)
            if handlers is None:
                return
            # Remove first occurrence; ignore if already removed (idempotent)
            with contextlib.suppress(ValueError):
                handlers.remove(handler)

        return _unsubscribe

    async def publish(self, event: Event) -> None:
        """Schedule all subscribers of *event.topic* to handle this event.

        Returns immediately after scheduling (does not await handlers).
        """
        handlers = list(self._subscribers.get(event.topic, []))
        for handler in handlers:
            task: asyncio.Task[None] = asyncio.create_task(
                self._invoke(handler, event), name=f"EventBus:{event.topic}:{handler.__name__}"
            )
            self._in_flight.add(task)
            task.add_done_callback(self._in_flight.discard)

    async def _invoke(self, handler: Handler, event: Event) -> None:
        """Call *handler* with *event*, isolating any exception from propagating."""
        try:
            await handler(event)
        except asyncio.CancelledError:
            raise  # propagate cancellation so aclose() works correctly
        except Exception:
            logger.exception(
                "EventBus handler %r raised on topic %r",
                getattr(handler, "__name__", repr(handler)),
                event.topic,
            )

    async def wait_idle(self, timeout: float | None = None) -> None:
        """Wait until all scheduled handler tasks complete.

        Useful for tests. Raises TimeoutError if *timeout* expires.
        """
        if not self._in_flight:
            return
        tasks = list(self._in_flight)
        try:
            await asyncio.wait_for(
                asyncio.gather(*tasks, return_exceptions=True),
                timeout=timeout,
            )
        except TimeoutError:
            raise

    async def aclose(self) -> None:
        """Cancel any in-flight tasks. Safe to call multiple times."""
        tasks = list(self._in_flight)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
