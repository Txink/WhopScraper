"""Parser event-bus service — Task 20.

Subscribes to ``message.received`` and drives the full parse pipeline:

    MessagePayload (just msg)
        ↓ subscribe
    handler:
        1. Create Task from msg (Task.new_from_message)
        2. mark_parsing()
        3. Publish TASK_CREATED (status=PARSING) — so storage can save it
        4. Try single-message parser (stock or option based on msg.source)
        5. If None / no ticker → try context_resolver
        6. On instruction obtained → attach_instruction + record_parse_timing
           → publish TASK_INSTRUCTION_READY
        7. On still None → mark_parse_failed
           → publish TASK_PARSE_FAILED

Any unexpected exception in the handler body sets PARSE_ERROR and publishes
TASK_PARSE_FAILED so the Task is never left stuck in PARSING.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import TYPE_CHECKING, Protocol

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import app.parser_v2 as parser_v2
from app.core.event_bus import Event, EventBus
from app.core.events import MessagePayload, TaskPayload, Topics
from app.domain.instruction import Instruction
from app.domain.task import Task
from app.parser import option_parser, stock_parser
from app.parser.context_resolver import resolve_context

if TYPE_CHECKING:
    from app.whop.page_settings import PageSettings

logger = logging.getLogger(__name__)


class _RegistryLike(Protocol):
    """Minimal interface ParserService needs from WhopRegistry."""

    def get_settings_for_url(self, url: str | None) -> PageSettings | None: ...


def register_parser_service(
    bus: EventBus,
    session_factory: async_sessionmaker[AsyncSession],
    *,
    registry: _RegistryLike | None = None,
) -> Callable[[], None]:
    """Subscribe the parser handler to ``message.received``.

    ``registry`` (optional) provides per-page ticker lists used by the stock
    context resolver fallback. When ``None`` (or when the message is an orphan
    / option), the fallback receives an empty set and is therefore skipped.

    Returns an unsubscribe callable so the caller can tear down the listener
    (useful in tests and application lifecycle management).
    """

    async def _handle_message_received(event: Event) -> None:
        payload = event.payload
        if not isinstance(payload, MessagePayload):
            logger.warning("parser.service: unexpected payload type %s", type(payload))
            return

        msg = payload.message
        task = Task.new_from_message(msg, is_historical=payload.is_historical)
        task.mark_parsing()

        # Publish TASK_CREATED (status=PARSING) so storage has a record
        await bus.publish(Event(Topics.TASK_CREATED, TaskPayload(task)))

        # Per-page settings. Looked up here once (not inside the try block) so
        # both the watched-ticker fallback and the parser-version dispatch can
        # use it. orphan / option / no-registry → page_settings is None.
        page_settings: PageSettings | None = None
        watched: set[str] = set()
        if msg.source == "stock" and registry is not None:
            page_settings = registry.get_settings_for_url(msg.url)
            if page_settings is not None and page_settings.tickers:
                watched = set(page_settings.tickers.keys())

        started = time.perf_counter()
        parser_version_used: str | None = None

        try:
            # --- Single-message parse ---
            parsed: Instruction | None
            if msg.source == "stock":
                if page_settings is not None and page_settings.parser_version == "v2":
                    parser_version_used = "v2"
                    parsed = parser_v2.parse(msg.content, message_id=msg.id)
                else:
                    parser_version_used = "v1"
                    parsed = stock_parser.parse(msg.content, message_id=msg.id)
            else:
                parsed = option_parser.parse(
                    msg.content,
                    message_id=msg.id,
                    message_posted_at=msg.posted_at,
                )

            # --- Context resolution (when no result or ticker missing) ---
            if parsed is None or not getattr(parsed, "ticker", ""):
                resolved = await resolve_context(
                    session_factory=session_factory,
                    msg=msg,
                    parsed=parsed,
                    watched_tickers=watched,
                )
            else:
                resolved = parsed

        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "parser.service: exception while parsing message %s",
                msg.id,
                extra={"parser_version": parser_version_used},
            )
            elapsed_ms = (time.perf_counter() - started) * 1000
            task.record_parse_timing(elapsed_ms)
            task.mark_parse_failed(f"parser error: {exc}")
            await bus.publish(Event(Topics.TASK_PARSE_FAILED, TaskPayload(task)))
            return

        elapsed_ms = (time.perf_counter() - started) * 1000
        task.record_parse_timing(elapsed_ms)

        if resolved is not None:
            task.attach_instruction(resolved)
            logger.info(
                "parser.service: parsed message %s",
                msg.id,
                extra={
                    "parser_version": parser_version_used,
                    "elapsed_ms": elapsed_ms,
                },
            )
            await bus.publish(Event(Topics.TASK_INSTRUCTION_READY, TaskPayload(task)))
        else:
            task.mark_parse_failed("无法解析为交易指令")
            logger.info(
                "parser.service: parse failed for message %s",
                msg.id,
                extra={
                    "parser_version": parser_version_used,
                    "elapsed_ms": elapsed_ms,
                },
            )
            await bus.publish(Event(Topics.TASK_PARSE_FAILED, TaskPayload(task)))

    return bus.subscribe(Topics.MESSAGE_RECEIVED, _handle_message_received)
