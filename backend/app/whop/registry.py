"""WhopRegistry —— runtime registry of Whop page monitors.

Persists page entries to data/whop_pages.json so restarts preserve them.
The active WhopListener instances are NOT persisted — they're rebuilt
from the JSON on startup.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, cast
from urllib.parse import urlsplit, urlunsplit

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.event_bus import Event, EventBus
from app.core.events import Topics, WhopPagePayload
from app.whop.listener import WhopListener, _is_placeholder_url
from app.whop.page_settings import (
    PageSettings,
    default_settings_for,
    page_settings_from_dict,
    page_settings_to_dict,
)

logger = logging.getLogger(__name__)

# Source literal alias used by the cast() calls below; matches the type signature
# of default_settings_for / page_settings_from_dict in app.whop.page_settings.
_SourceLiteral = Literal["stock", "option", "chat"]

# Project root (backend/app/whop/registry.py → parents[3] = project root)
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_PAGES_FILE = _PROJECT_ROOT / "data" / "whop_pages.json"


def _canonicalize_url(url: str | None) -> str | None:
    """Normalize a Whop URL for case + trailing-slash insensitive lookup.

    Whop routes are case-insensitive (``/joined/X`` ≡ ``/Joined/X``) and
    the user-supplied URL may or may not carry a trailing slash. Folding
    both the host and the path to lowercase, plus stripping a trailing
    ``/``, makes ``get_settings_for_url`` (and downstream listener lookups
    that use the same canonicalization in storage/repo) match regardless
    of how the URL was originally typed in.
    """
    if url is None:
        return None
    s = str(url).strip()
    if not s:
        return None
    p = urlsplit(s)
    path = (p.path or "").lower().rstrip("/") or "/"
    return urlunsplit((p.scheme.lower(), p.netloc.lower(), path, "", ""))


@dataclass
class WhopPageEntry:
    id: str
    url: str
    source: str  # "stock" | "option" | "chat"
    name: str
    added_at: datetime
    # Per-page listener/parser settings. Default factory yields a "stock" preset
    # because that matches the `source` default; callers MUST pass an explicit
    # `default_settings_for(source)` when constructing for option pages.
    settings: PageSettings = field(default_factory=lambda: default_settings_for("stock"))
    # Optional reference to the parent chat page that "owns" this stock/option
    # sub-monitor. None means this is a top-level page (no parent).
    # Validation (parent must be a chat page, no nesting) is enforced elsewhere.
    parent_chat_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "url": self.url,
            "source": self.source,
            "name": self.name,
            "added_at": self.added_at.isoformat(),
            "settings": page_settings_to_dict(self.settings),
            "parent_chat_id": self.parent_chat_id,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> WhopPageEntry:
        # JSON loaded from disk — d["source"] is a free-form str from the file.
        # Cast to Literal so downstream typing stays exact; malformed values are
        # still rejected by default_settings_for / page_settings_from_dict.
        source = cast(_SourceLiteral, d["source"])
        settings_raw = d.get("settings")
        if settings_raw is None:
            # Legacy entry written before per-page settings existed.
            settings = default_settings_for(source)
        else:
            settings = page_settings_from_dict(settings_raw, source=source)
        return cls(
            id=d["id"],
            url=d["url"],
            source=source,
            name=d.get("name") or d["url"],
            added_at=datetime.fromisoformat(d["added_at"]),
            settings=settings,
            parent_chat_id=d.get("parent_chat_id"),
        )


class WhopRegistry:
    """Async registry of Whop listeners.

    All mutations acquire an internal lock to serialize start/stop with
    file persistence. JSON file is the source of truth for entries; live
    listeners hang off them.
    """

    def __init__(
        self,
        *,
        bus: EventBus,
        settings: Settings,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
        pages_file: Path | None = None,
    ) -> None:
        self._bus = bus
        self._settings = settings
        self._session_factory = session_factory
        self._pages_file = pages_file or _DEFAULT_PAGES_FILE
        self._lock = asyncio.Lock()
        self._entries: dict[str, WhopPageEntry] = {}
        self._listeners: dict[str, WhopListener] = {}
        # url -> entry_id; rebuilt after every entries-dict mutation. O(1) lookup
        # for the trader's "which page should this message use?" query.
        self._url_index: dict[str, str] = {}

    async def load_entries(self) -> None:
        """At app startup: load JSON file (entries only — does NOT start listeners).

        Listeners are explicitly started via ``start_page()`` so monitoring
        defaults OFF after restart. The user toggles each page on from the
        dashboard. This sidesteps any "did the auto-restart pick up my new
        config" confusion and avoids spinning up Playwright for pages the
        user hasn't reactivated.
        """
        async with self._lock:
            self._entries = self._load_entries()
            self._rebuild_url_index()

    async def shutdown_all(self) -> None:
        async with self._lock:
            for listener in list(self._listeners.values()):
                try:
                    await listener.stop()
                except Exception as e:  # noqa: BLE001
                    logger.warning("error stopping listener: %s", e)
            self._listeners.clear()

    # ---- mutating ops ----

    def register_virtual_page(
        self,
        *,
        url: str,
        source: str,
        name: str,
        settings: "PageSettings",
    ) -> WhopPageEntry:
        """Inject a non-Whop page entry without URL validation or disk persist.

        Used by ``app.sim`` to register the ``sim://scenarios`` virtual page
        on startup so the trader's whitelist + qty resolution gates work for
        simulated tasks. The entry is NOT written to ``pages.json`` (sim is
        ephemeral; restart re-registers) and no listener is started.
        """
        entry = WhopPageEntry(
            id=f"virtual-{uuid.uuid4().hex[:8]}",
            url=url,
            source=source,  # type: ignore[arg-type]
            name=name,
            added_at=datetime.now(UTC),
            settings=settings,
        )
        # Take the lock synchronously via the same internal dict mutation
        # path; this runs at startup before any concurrent callers exist.
        self._entries[entry.id] = entry
        self._rebuild_url_index()
        return entry

    async def add_page(
        self,
        *,
        url: str,
        source: str,
        name: str | None = None,
        parent_chat_id: str | None = None,
    ) -> WhopPageEntry:
        """Add a new page entry + persist (does NOT start listener).

        New behaviour: user must explicitly start the listener via
        ``start_page()`` (or POST /api/whop/pages/{id}/start). This keeps the
        "default OFF" semantics consistent — adding a page is just registry
        bookkeeping, not Playwright startup.

        Raises ValueError on validation issues.
        """
        if source not in ("stock", "option", "chat"):
            raise ValueError(f"source must be stock|option|chat, got {source!r}")
        if not url or _is_placeholder_url(url):
            raise ValueError(f"invalid or placeholder URL: {url!r}")

        if parent_chat_id is not None:
            parent = self._entries.get(parent_chat_id)
            if parent is None:
                raise ValueError(f"parent_chat_id {parent_chat_id!r} not found")
            if parent.parent_chat_id is not None:
                raise ValueError("cannot nest sub-monitors (parent is itself a sub)")
            if parent.source != "chat":
                raise ValueError("parent must be source=chat")
            if source == "chat":
                raise ValueError("sub-monitor source must be stock or option")

        async with self._lock:
            # Authoritative duplicate-URL guard (only check; runs under lock to
            # avoid TOCTOU between two concurrent add_page calls).
            new_canon = _canonicalize_url(url)
            for existing in self._entries.values():
                if _canonicalize_url(existing.url) == new_canon:
                    raise ValueError(f"URL already monitored (id={existing.id})")

            entry = WhopPageEntry(
                id=uuid.uuid4().hex[:12],
                url=url,
                source=source,
                name=(name or url),
                added_at=datetime.now(UTC),
                # source was validated against ("stock", "option", "chat") above; cast for mypy.
                settings=default_settings_for(cast(_SourceLiteral, source)),
                parent_chat_id=parent_chat_id,
            )
            self._entries[entry.id] = entry
            self._save_entries()
            self._rebuild_url_index()
            page_dict = self._build_page_dict(entry)
        await self._publish_page_event("added", page_dict)
        return entry

    async def remove_page(self, page_id: str) -> bool:
        """Stop listener + remove entry + persist. Returns False if not found."""
        async with self._lock:
            entry = self._entries.pop(page_id, None)
            if entry is None:
                return False
            listener = self._listeners.pop(page_id, None)
            if listener is not None:
                try:
                    await listener.stop()
                except Exception as e:  # noqa: BLE001
                    logger.warning("error stopping removed listener: %s", e)
            self._save_entries()
            self._rebuild_url_index()
            page_dict = self._build_page_dict(entry)
        await self._publish_page_event("removed", page_dict)
        return True

    async def start_page(self, page_id: str) -> bool:
        """Start (or restart) the listener for an entry.

        Same semantics as ``restart_page``: stops any existing listener first,
        then starts a fresh one with ``skip_initial=False`` so the listener
        re-scans the visible DOM. Storage UPSERT (by domID) dedupes against
        previously seen messages, so this is safe to call repeatedly.

        Returns False if the entry id is unknown OR if launching Playwright
        fails (errors are logged).
        """
        async with self._lock:
            entry = self._entries.get(page_id)
            if entry is None:
                return False
            # Stop existing listener if any (idempotent restart). pop() so the
            # dict stays consistent even if _start_listener below raises.
            listener = self._listeners.pop(page_id, None)
            if listener is not None:
                try:
                    await listener.stop()
                except Exception as e:  # noqa: BLE001
                    logger.warning("start: stop existing failed: %s", e)
            try:
                await self._start_listener(entry, skip_initial=False)
            except Exception as e:  # noqa: BLE001
                logger.warning("start: launch failed: %s", e)
                return False
            page_dict = self._build_page_dict(entry)
        await self._publish_page_event("started", page_dict)
        return True

    async def stop_page(self, page_id: str) -> bool:
        """Stop the listener for an entry but keep the entry in the registry.

        Returns False if the entry id is unknown. Returns True even if no
        listener was running (idempotent — "stop something that isn't running"
        is treated as success so the UI can issue stop without checking state).
        """
        async with self._lock:
            entry = self._entries.get(page_id)
            if entry is None:
                return False
            listener = self._listeners.pop(page_id, None)
            if listener is not None:
                try:
                    await listener.stop()
                except Exception as e:  # noqa: BLE001
                    logger.warning("stop: failed: %s", e)
            page_dict = self._build_page_dict(entry)
        await self._publish_page_event("stopped", page_dict)
        return True

    async def restart_page(self, page_id: str) -> bool:
        """Stop + restart listener for an entry, replaying all currently-visible
        DOM messages.

        Restart semantics: skip_initial=False so the listener publishes every
        message present in the DOM right after start. This is the user-facing
        "重启" intent: re-process visible messages (e.g., after fixing a parser
        bug, after clearing the DB, etc.). Storage UPSERT dedupes by domID, so
        existing tasks are updated in place rather than duplicated.

        Returns False if not found or start fails.
        """
        async with self._lock:
            entry = self._entries.get(page_id)
            if entry is None:
                return False
            listener = self._listeners.pop(page_id, None)
            if listener is not None:
                try:
                    await listener.stop()
                except Exception as e:  # noqa: BLE001
                    logger.warning("restart: stop failed: %s", e)
            try:
                await self._start_listener(entry, skip_initial=False)
            except Exception as e:  # noqa: BLE001
                logger.warning("restart: start failed: %s", e)
                return False
            page_dict = self._build_page_dict(entry)
        await self._publish_page_event("restarted", page_dict)
        return True

    async def update_settings(self, page_id: str, patch: dict[str, Any]) -> WhopPageEntry:
        """Local update — merges patch into existing settings, persists, publishes event.

        Merge semantics: shallow at top level only.
        - ``dedupe_processed_messages`` / ``price_deviation_tolerance``: replaced if
          present in patch.
        - ``tickers``: ENTIRE dict replaced if present (not per-ticker merge). To add
          one ticker without affecting others, the caller must read existing settings +
          send the merged dict.

        Raises:
            KeyError: page_id not found
            ValueError: option page received ``tickers`` in patch
        """
        async with self._lock:
            entry = self._entries.get(page_id)
            if entry is None:
                raise KeyError(f"page not found: {page_id}")
            if entry.source == "option" and "tickers" in patch:
                raise ValueError("option page does not accept 'tickers'")
            current_dict = page_settings_to_dict(entry.settings)
            current_dict.update(patch)
            # entry.source was validated as "stock"|"option"|"chat" at construction
            # (add_page guards + WhopPageEntry.from_dict cast) but the dataclass
            # field is typed `str`, so cast back to Literal for the call site.
            new_settings = page_settings_from_dict(
                current_dict, source=cast(_SourceLiteral, entry.source)
            )
            entry.settings = new_settings
            self._save_entries()
            page_dict = self._build_page_dict(entry)
        await self._publish_page_event("settings_updated", page_dict)
        return entry

    # ---- read ops ----

    def list_pages(self) -> list[tuple[WhopPageEntry, WhopListener | None]]:
        """Return entries + their (optional) live listener. No lock — caller is read-only."""
        return [(e, self._listeners.get(e.id)) for e in self._entries.values()]

    def get_settings_for_url(self, url: str | None) -> PageSettings | None:
        """O(1) reverse lookup: url → PageSettings. Returns None for unknown/None url.

        Used by the trader/parser pipeline to pick up per-page tolerances and
        ticker whitelists when handed a Message that knows only its source url.
        """
        canon = _canonicalize_url(url)
        if canon is None:
            return None
        eid = self._url_index.get(canon)
        if eid is None:
            return None
        return self._entries[eid].settings

    async def clear_seen_for_url(self, url: str | None) -> int:
        """Clear in-memory dedupe cache for listeners matching the url."""
        canon = _canonicalize_url(url)
        if canon is None:
            return 0
        cleared = 0
        async with self._lock:
            for listener in self._listeners.values():
                if listener is None:
                    continue
                if _canonicalize_url(listener.url) == canon:
                    listener.reset_seen_cache()
                    cleared += 1
        return cleared

    # ---- internal ----

    def _rebuild_url_index(self) -> None:
        """Recompute url → entry_id mapping from current entries dict."""
        self._url_index = {}
        for entry in self._entries.values():
            canon = _canonicalize_url(entry.url)
            if canon is not None:
                self._url_index[canon] = entry.id

    def _build_page_dict(self, entry: WhopPageEntry) -> dict[str, Any]:
        """Build serialized page dict. MUST be called while holding self._lock.

        Snapshots both the entry state and the current listener so the resulting
        dict is consistent with the moment of mutation, even if another task
        removes/restarts the same entry before the event is published.

        ``whop_page_to_out`` is imported lazily to avoid an app.api → app.whop
        import-cycle (schemas itself only references WhopPageEntry under
        TYPE_CHECKING, so the runtime import here is one-way).
        """
        from app.api.schemas import whop_page_to_out

        listener = self._listeners.get(entry.id)
        return whop_page_to_out(entry, listener).model_dump(mode="json")

    async def _publish_page_event(self, action: str, page_dict: dict[str, Any]) -> None:
        """Publish a whop.page_changed event. Safe to call without holding the lock."""
        await self._bus.publish(
            Event(
                Topics.WHOP_PAGE_CHANGED,
                WhopPagePayload(action=action, page_dict=page_dict),
            )
        )

    def _make_status_callback(self, page_id: str) -> Callable[[str], Awaitable[None]]:
        """Build the on_status_change callback that a listener invokes when its
        scan loop transitions between healthy and errored.

        The closure looks up the entry under the registry lock, snapshots its
        current page dict, then publishes a whop.page_changed event with the
        given action ("errored" or "recovered"). If the entry has already been
        removed by the time the callback fires, it returns silently — the
        listener is in the process of being torn down, so there's nothing to
        report.
        """
        async def _on_status(action: str) -> None:
            async with self._lock:
                entry = self._entries.get(page_id)
                if entry is None:
                    return
                page_dict = self._build_page_dict(entry)
            await self._publish_page_event(action, page_dict)

        return _on_status

    async def _start_listener(self, entry: WhopPageEntry, *, skip_initial: bool = True) -> None:
        """Build + start a listener for an entry. Lock must be held by caller.

        skip_initial=True (default for boot + add_page): prime the seen set
        from the current DOM so we only publish messages that arrive AFTER
        startup. Avoids flooding when adding a brand-new channel that has
        years of history visible.

        skip_initial=False (used by restart_page): _seen starts empty so the
        listener publishes every message currently in the DOM. Combined with
        storage UPSERT this lets users re-process existing tasks (e.g., after
        a parser fix) without duplicating rows.
        """
        listener = WhopListener(
            bus=self._bus,
            url=entry.url,
            source=entry.source,
            page_id=entry.id,
            poll_interval=self._settings.whop_poll_interval,
            headless=entry.settings.launch_headless,
            skip_initial=skip_initial,
            dedupe_processed_messages=entry.settings.dedupe_processed_messages,
            session_factory=self._session_factory,
            on_status_change=self._make_status_callback(entry.id),
        )
        await listener.start()
        self._listeners[entry.id] = listener

    def _load_entries(self) -> dict[str, WhopPageEntry]:
        if not self._pages_file.is_file():
            return {}
        try:
            raw = json.loads(self._pages_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            logger.warning("failed to read %s: %s", self._pages_file, e)
            return {}
        out: dict[str, WhopPageEntry] = {}
        for d in raw:
            try:
                entry = WhopPageEntry.from_dict(d)
                out[entry.id] = entry
            except Exception as exc:  # noqa: BLE001
                logger.warning("skipping malformed entry %s: %s", d, exc)
        return out

    def _save_entries(self) -> None:
        self._pages_file.parent.mkdir(parents=True, exist_ok=True)
        # Skip ``sim://`` virtual entries — the simulator re-registers them
        # from code on every startup; persisting them risks stale config
        # silently overriding the canonical in-code definition.
        data = [
            e.to_dict() for e in self._entries.values()
            if not e.url.startswith("sim://")
        ]
        self._pages_file.write_text(
            json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
        )
