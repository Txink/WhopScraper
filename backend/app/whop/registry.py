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
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

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

# Project root (backend/app/whop/registry.py → parents[3] = project root)
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_PAGES_FILE = _PROJECT_ROOT / "data" / "whop_pages.json"


@dataclass
class WhopPageEntry:
    id: str
    url: str
    source: str  # "stock" | "option"
    name: str
    added_at: datetime
    # Per-page listener/parser settings. Default factory yields a "stock" preset
    # because that matches the `source` default; callers MUST pass an explicit
    # `default_settings_for(source)` when constructing for option pages.
    settings: PageSettings = field(default_factory=lambda: default_settings_for("stock"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "url": self.url,
            "source": self.source,
            "name": self.name,
            "added_at": self.added_at.isoformat(),
            "settings": page_settings_to_dict(self.settings),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> WhopPageEntry:
        source = d["source"]
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
        pages_file: Path | None = None,
    ) -> None:
        self._bus = bus
        self._settings = settings
        self._pages_file = pages_file or _DEFAULT_PAGES_FILE
        self._lock = asyncio.Lock()
        self._entries: dict[str, WhopPageEntry] = {}
        self._listeners: dict[str, WhopListener] = {}
        # url -> entry_id; rebuilt after every entries-dict mutation. O(1) lookup
        # for the trader's "which page should this message use?" query.
        self._url_index: dict[str, str] = {}

    async def load_and_start_all(self) -> None:
        """At app startup: load JSON file + start a listener per entry.

        Skips placeholder URLs (logs info). Errors on individual listeners
        don't abort the load — they're logged and the entry stays in the
        registry but with a None listener (running=False).
        """
        async with self._lock:
            self._entries = self._load_entries()
            for entry in self._entries.values():
                if _is_placeholder_url(entry.url):
                    logger.info("whop registry: skipping placeholder %s", entry.url)
                    continue
                try:
                    await self._start_listener(entry)
                except Exception as e:  # noqa: BLE001
                    logger.warning(
                        "whop registry: listener for %s failed to start: %s", entry.id, e
                    )
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

    async def add_page(
        self, *, url: str, source: str, name: str | None = None
    ) -> WhopPageEntry:
        """Add a new page entry, persist, start its listener.

        Raises ValueError on validation issues.
        """
        if source not in ("stock", "option"):
            raise ValueError(f"source must be stock|option, got {source!r}")
        if not url or _is_placeholder_url(url):
            raise ValueError(f"invalid or placeholder URL: {url!r}")

        async with self._lock:
            # Authoritative duplicate-URL guard (only check; runs under lock to
            # avoid TOCTOU between two concurrent add_page calls).
            for existing in self._entries.values():
                if existing.url == url:
                    raise ValueError(f"URL already monitored (id={existing.id})")

            entry = WhopPageEntry(
                id=uuid.uuid4().hex[:12],
                url=url,
                source=source,
                name=(name or url),
                added_at=datetime.now(UTC),
                settings=default_settings_for(source),
            )
            self._entries[entry.id] = entry
            self._save_entries()
            try:
                await self._start_listener(entry)
            except Exception as e:  # noqa: BLE001
                logger.warning(
                    "listener for new page %s failed to start: %s", entry.id, e
                )
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

    async def update_settings(
        self, page_id: str, patch: dict[str, Any]
    ) -> WhopPageEntry:
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
            new_settings = page_settings_from_dict(current_dict, source=entry.source)
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
        if not url:
            return None
        eid = self._url_index.get(url)
        if eid is None:
            return None
        return self._entries[eid].settings

    # ---- internal ----

    def _rebuild_url_index(self) -> None:
        """Recompute url → entry_id mapping from current entries dict."""
        self._url_index = {e.url: e.id for e in self._entries.values()}

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

    async def _start_listener(
        self, entry: WhopPageEntry, *, skip_initial: bool = True
    ) -> None:
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
            poll_interval=self._settings.whop_poll_interval,
            headless=self._settings.whop_headless,
            skip_initial=skip_initial,
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
        data = [e.to_dict() for e in self._entries.values()]
        self._pages_file.write_text(
            json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
        )
