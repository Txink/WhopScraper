"""WhopRegistry tests — JSON persistence + listener lifecycle (with monkey-patched WhopBrowser).

Note: as of the explicit-on/off refactor, ``load_entries`` and ``add_page`` no
longer spin up listeners. Tests that need a running listener must call
``start_page(entry.id)`` explicitly.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.core.config import Settings
from app.core.event_bus import Event, EventBus
from app.whop.page_settings import PageSettings, TickerConfig  # noqa: F401  (used in new tests)
from app.whop.registry import WhopRegistry

# ---------------------------------------------------------------------------
# Fake browser (mirrors the one in test_listener.py)
# ---------------------------------------------------------------------------


class _FakeBrowser:
    def __init__(self, htmls: list[str] | None = None) -> None:
        self._htmls = list(htmls or ["<html></html>"])
        self._idx = 0
        self.closed = False

    async def start(self) -> None:
        return None

    async def navigate(self, url: str) -> bool:  # noqa: ARG002
        return True

    async def scrape_html(self) -> str:
        h = self._htmls[min(self._idx, len(self._htmls) - 1)]
        self._idx += 1
        return h

    async def close(self) -> None:
        self.closed = True


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def patch_browser(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.whop.listener.WhopBrowser", lambda *a, **kw: _FakeBrowser())


@pytest.fixture
def settings_test() -> Settings:
    return Settings(
        app_token="test",
        database_url="sqlite+aiosqlite:///:memory:",
        whop_poll_interval=0.05,
        whop_headless=True,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_add_persists_entry_only(
    patch_browser: None, settings_test: Settings, tmp_path: Path
) -> None:
    """add_page persists entry to JSON but does NOT start a listener.

    Listener startup is now an explicit user action via start_page().
    """
    bus = EventBus()
    pages_file = tmp_path / "pages.json"
    reg = WhopRegistry(bus=bus, settings=settings_test, pages_file=pages_file)
    await reg.load_entries()

    entry = await reg.add_page(
        url="https://whop.com/joined/abc/app/", source="stock", name="My Stock"
    )
    assert entry.id
    assert entry.source == "stock"

    # Persisted?
    saved = json.loads(pages_file.read_text())
    assert len(saved) == 1
    assert saved[0]["url"] == entry.url

    # Listener NOT started — that's the new default
    pages = reg.list_pages()
    assert len(pages) == 1
    _, ll = pages[0]
    assert ll is None

    await reg.shutdown_all()


@pytest.mark.asyncio
async def test_remove_stops_listener_and_persists(
    patch_browser: None, settings_test: Settings, tmp_path: Path
) -> None:
    """remove_page: stops listener (if any) and clears entry from JSON."""
    bus = EventBus()
    pages_file = tmp_path / "pages.json"
    reg = WhopRegistry(bus=bus, settings=settings_test, pages_file=pages_file)
    await reg.load_entries()

    entry = await reg.add_page(url="https://whop.com/joined/abc/app/", source="stock")
    await reg.start_page(entry.id)
    assert await reg.remove_page(entry.id)

    # File reflects removal
    saved = json.loads(pages_file.read_text())
    assert saved == []

    # No active listeners
    assert reg.list_pages() == []


@pytest.mark.asyncio
async def test_remove_unknown_returns_false(
    patch_browser: None, settings_test: Settings, tmp_path: Path
) -> None:
    """remove_page with unknown id returns False."""
    bus = EventBus()
    reg = WhopRegistry(bus=bus, settings=settings_test, pages_file=tmp_path / "p.json")
    await reg.load_entries()
    assert (await reg.remove_page("does-not-exist")) is False


@pytest.mark.asyncio
async def test_add_rejects_duplicate_url(
    patch_browser: None, settings_test: Settings, tmp_path: Path
) -> None:
    """add_page raises ValueError when URL already monitored."""
    bus = EventBus()
    reg = WhopRegistry(bus=bus, settings=settings_test, pages_file=tmp_path / "p.json")
    await reg.load_entries()
    await reg.add_page(url="https://whop.com/joined/abc/app/", source="stock")
    with pytest.raises(ValueError, match="already monitored"):
        await reg.add_page(url="https://whop.com/joined/abc/app/", source="option")
    await reg.shutdown_all()


@pytest.mark.asyncio
async def test_add_rejects_placeholder_url(
    patch_browser: None, settings_test: Settings, tmp_path: Path
) -> None:
    """add_page raises ValueError for placeholder URLs."""
    bus = EventBus()
    reg = WhopRegistry(bus=bus, settings=settings_test, pages_file=tmp_path / "p.json")
    await reg.load_entries()
    with pytest.raises(ValueError, match="placeholder"):
        await reg.add_page(url="https://whop.com/joined/xxx/app/", source="stock")


@pytest.mark.asyncio
async def test_add_rejects_invalid_source(
    patch_browser: None, settings_test: Settings, tmp_path: Path
) -> None:
    """add_page raises ValueError for invalid source values."""
    bus = EventBus()
    reg = WhopRegistry(bus=bus, settings=settings_test, pages_file=tmp_path / "p.json")
    await reg.load_entries()
    with pytest.raises(ValueError, match="source must be"):
        await reg.add_page(url="https://whop.com/joined/abc/app/", source="invalid")


@pytest.mark.asyncio
async def test_load_entries_does_not_start_listeners(
    patch_browser: None, settings_test: Settings, tmp_path: Path
) -> None:
    """load_entries reads JSON entries but listeners stay offline.

    Replaces the old test_load_existing_file_starts_listeners — load no
    longer auto-starts.
    """
    pages_file = tmp_path / "pages.json"
    pages_file.parent.mkdir(parents=True, exist_ok=True)
    pages_file.write_text(
        json.dumps(
            [
                {
                    "id": "p1",
                    "url": "https://whop.com/p1/app/",
                    "source": "stock",
                    "name": "P1",
                    "added_at": "2026-04-25T00:00:00+00:00",
                }
            ]
        )
    )

    bus = EventBus()
    reg = WhopRegistry(bus=bus, settings=settings_test, pages_file=pages_file)
    await reg.load_entries()

    pages = reg.list_pages()
    assert len(pages) == 1
    entry, listener = pages[0]
    assert entry.id == "p1"
    assert listener is None  # NOT started by load_entries


@pytest.mark.asyncio
async def test_add_page_does_not_auto_start(
    patch_browser: None, settings_test: Settings, tmp_path: Path
) -> None:
    """add_page leaves the listener None until start_page is called."""
    bus = EventBus()
    reg = WhopRegistry(bus=bus, settings=settings_test, pages_file=tmp_path / "pages.json")
    await reg.load_entries()
    await reg.add_page(url="https://whop.com/x/app/", source="stock", name="x")
    pages = reg.list_pages()
    assert len(pages) == 1
    assert pages[0][1] is None  # listener is None


@pytest.mark.asyncio
async def test_start_page_starts_listener(
    patch_browser: None, settings_test: Settings, tmp_path: Path
) -> None:
    bus = EventBus()
    reg = WhopRegistry(bus=bus, settings=settings_test, pages_file=tmp_path / "pages.json")
    await reg.load_entries()
    entry = await reg.add_page(url="https://whop.com/x/app/", source="stock", name="x")
    ok = await reg.start_page(entry.id)
    assert ok is True
    pages = reg.list_pages()
    assert pages[0][1] is not None  # listener now exists
    assert pages[0][1].running is True
    await reg.shutdown_all()


@pytest.mark.asyncio
async def test_start_page_is_idempotent_restart(
    patch_browser: None, settings_test: Settings, tmp_path: Path
) -> None:
    """Calling start_page twice replaces the listener (restart semantics)."""
    bus = EventBus()
    reg = WhopRegistry(bus=bus, settings=settings_test, pages_file=tmp_path / "pages.json")
    await reg.load_entries()
    entry = await reg.add_page(url="https://whop.com/x/app/", source="stock", name="x")

    await reg.start_page(entry.id)
    first = reg.list_pages()[0][1]
    assert first is not None

    await reg.start_page(entry.id)
    second = reg.list_pages()[0][1]
    assert second is not None
    assert second is not first  # fresh listener
    await reg.shutdown_all()


@pytest.mark.asyncio
async def test_stop_page_stops_listener_keeps_entry(
    patch_browser: None, settings_test: Settings, tmp_path: Path
) -> None:
    bus = EventBus()
    reg = WhopRegistry(bus=bus, settings=settings_test, pages_file=tmp_path / "pages.json")
    await reg.load_entries()
    entry = await reg.add_page(url="https://whop.com/x/app/", source="stock", name="x")
    await reg.start_page(entry.id)
    ok = await reg.stop_page(entry.id)
    assert ok is True
    pages = reg.list_pages()
    assert len(pages) == 1
    assert pages[0][1] is None  # listener gone, entry kept


@pytest.mark.asyncio
async def test_stop_page_idempotent_when_not_running(
    patch_browser: None, settings_test: Settings, tmp_path: Path
) -> None:
    """stop_page returns True even when the listener wasn't running."""
    bus = EventBus()
    reg = WhopRegistry(bus=bus, settings=settings_test, pages_file=tmp_path / "pages.json")
    await reg.load_entries()
    entry = await reg.add_page(url="https://whop.com/x/app/", source="stock", name="x")
    # Never started
    assert await reg.stop_page(entry.id) is True


@pytest.mark.asyncio
async def test_start_stop_unknown_id_returns_false(
    patch_browser: None, settings_test: Settings, tmp_path: Path
) -> None:
    bus = EventBus()
    reg = WhopRegistry(bus=bus, settings=settings_test, pages_file=tmp_path / "pages.json")
    await reg.load_entries()
    assert await reg.start_page("nope") is False
    assert await reg.stop_page("nope") is False


@pytest.mark.asyncio
async def test_restart_page(
    patch_browser: None, settings_test: Settings, tmp_path: Path
) -> None:
    """restart_page stops old listener and starts a new one."""
    bus = EventBus()
    pages_file = tmp_path / "pages.json"
    reg = WhopRegistry(bus=bus, settings=settings_test, pages_file=pages_file)
    await reg.load_entries()

    entry = await reg.add_page(url="https://whop.com/joined/abc/app/", source="stock")
    await reg.start_page(entry.id)

    pages_before = reg.list_pages()
    assert len(pages_before) == 1
    original_listener = pages_before[0][1]
    assert original_listener is not None

    ok = await reg.restart_page(entry.id)
    assert ok is True

    pages_after = reg.list_pages()
    assert len(pages_after) == 1
    new_listener = pages_after[0][1]
    assert new_listener is not None
    # A new listener object should have been created
    assert new_listener is not original_listener

    await reg.shutdown_all()


@pytest.mark.asyncio
async def test_restart_unknown_page_returns_false(
    patch_browser: None, settings_test: Settings, tmp_path: Path
) -> None:
    """restart_page with unknown id returns False."""
    bus = EventBus()
    reg = WhopRegistry(bus=bus, settings=settings_test, pages_file=tmp_path / "p.json")
    await reg.load_entries()
    assert (await reg.restart_page("no-such-id")) is False


@pytest.mark.asyncio
async def test_shutdown_all_stops_all_listeners(
    patch_browser: None, settings_test: Settings, tmp_path: Path
) -> None:
    """shutdown_all stops all active listeners."""
    bus = EventBus()
    pages_file = tmp_path / "pages.json"
    reg = WhopRegistry(bus=bus, settings=settings_test, pages_file=pages_file)
    await reg.load_entries()

    e1 = await reg.add_page(url="https://whop.com/joined/abc/app/", source="stock")
    e2 = await reg.add_page(url="https://whop.com/joined/def/app/", source="option")
    await reg.start_page(e1.id)
    await reg.start_page(e2.id)

    pages = reg.list_pages()
    assert len(pages) == 2
    assert all(ll is not None and ll.running for _, ll in pages)

    await reg.shutdown_all()

    # After shutdown, listeners dict is cleared
    assert reg._listeners == {}


@pytest.mark.asyncio
async def test_load_skips_malformed_entries(
    patch_browser: None, settings_test: Settings, tmp_path: Path
) -> None:
    """load_entries skips malformed entries without raising."""
    pages_file = tmp_path / "pages.json"
    pages_file.write_text(
        json.dumps(
            [
                # malformed: missing required fields
                {"id": "bad1"},
                # valid
                {
                    "id": "good1",
                    "url": "https://whop.com/joined/real/app/",
                    "source": "stock",
                    "name": "Good",
                    "added_at": "2026-04-25T00:00:00+00:00",
                },
            ]
        )
    )

    bus = EventBus()
    reg = WhopRegistry(bus=bus, settings=settings_test, pages_file=pages_file)
    await reg.load_entries()

    pages = reg.list_pages()
    assert len(pages) == 1
    assert pages[0][0].id == "good1"

    await reg.shutdown_all()


# ---------------------------------------------------------------------------
# Settings + URL lookup + page_changed event tests (Task D)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_add_page_uses_default_settings(patch_browser, settings_test, tmp_path):
    """add_page without settings → entry.settings = source default."""
    bus = EventBus()
    reg = WhopRegistry(bus=bus, settings=settings_test, pages_file=tmp_path / "pages.json")
    await reg.load_entries()
    entry = await reg.add_page(url="https://whop.com/x/app/", source="stock", name="X")
    assert entry.settings.dedupe_processed_messages is True
    assert entry.settings.price_deviation_tolerance == 1.0
    assert entry.settings.tickers == {}


@pytest.mark.asyncio
async def test_add_page_option_default_settings(patch_browser, settings_test, tmp_path):
    bus = EventBus()
    reg = WhopRegistry(bus=bus, settings=settings_test, pages_file=tmp_path / "pages.json")
    await reg.load_entries()
    entry = await reg.add_page(url="https://whop.com/o/app/", source="option", name="O")
    assert entry.settings.tickers is None
    assert entry.settings.price_deviation_tolerance == 5.0


@pytest.mark.asyncio
async def test_settings_persisted_in_json(patch_browser, settings_test, tmp_path):
    bus = EventBus()
    pages_file = tmp_path / "pages.json"
    reg = WhopRegistry(bus=bus, settings=settings_test, pages_file=pages_file)
    await reg.load_entries()
    await reg.add_page(url="https://whop.com/p/app/", source="stock", name="P")

    raw = json.loads(pages_file.read_text())
    assert "settings" in raw[0]
    assert raw[0]["settings"]["price_deviation_tolerance"] == 1.0


@pytest.mark.asyncio
async def test_update_settings_persists_and_returns_entry(patch_browser, settings_test, tmp_path):
    bus = EventBus()
    pages_file = tmp_path / "pages.json"
    reg = WhopRegistry(bus=bus, settings=settings_test, pages_file=pages_file)
    await reg.load_entries()
    entry = await reg.add_page(url="https://whop.com/upd/app/", source="stock", name="upd")

    updated = await reg.update_settings(
        entry.id,
        {
            "tickers": {"NVDA": {"trade_quantity": 500}},
            "price_deviation_tolerance": 0.7,
        },
    )
    assert updated.settings.tickers == {"NVDA": TickerConfig(trade_quantity=500)}
    assert updated.settings.price_deviation_tolerance == 0.7
    # dedupe was not in patch → preserved
    assert updated.settings.dedupe_processed_messages is True

    # Persisted?
    raw = json.loads(pages_file.read_text())
    s = next(p["settings"] for p in raw if p["id"] == entry.id)
    assert s["tickers"] == {"NVDA": {"trade_quantity": 500}}
    assert s["price_deviation_tolerance"] == 0.7


@pytest.mark.asyncio
async def test_update_settings_unknown_id_raises(patch_browser, settings_test, tmp_path):
    bus = EventBus()
    reg = WhopRegistry(bus=bus, settings=settings_test, pages_file=tmp_path / "pages.json")
    await reg.load_entries()
    with pytest.raises(KeyError):
        await reg.update_settings("does-not-exist", {})


@pytest.mark.asyncio
async def test_update_settings_option_rejects_tickers(patch_browser, settings_test, tmp_path):
    bus = EventBus()
    reg = WhopRegistry(bus=bus, settings=settings_test, pages_file=tmp_path / "pages.json")
    await reg.load_entries()
    entry = await reg.add_page(url="https://whop.com/optx/app/", source="option", name="optx")
    with pytest.raises(ValueError, match="tickers"):
        await reg.update_settings(entry.id, {"tickers": {"AAPL": {"trade_quantity": 1}}})


@pytest.mark.asyncio
async def test_get_settings_for_url_match(patch_browser, settings_test, tmp_path):
    bus = EventBus()
    reg = WhopRegistry(bus=bus, settings=settings_test, pages_file=tmp_path / "pages.json")
    await reg.load_entries()
    entry = await reg.add_page(url="https://whop.com/lookup/app/", source="stock", name="lk")
    s = reg.get_settings_for_url(entry.url)
    assert s is not None
    assert s.dedupe_processed_messages is True


@pytest.mark.asyncio
async def test_get_settings_for_url_orphan(patch_browser, settings_test, tmp_path):
    bus = EventBus()
    reg = WhopRegistry(bus=bus, settings=settings_test, pages_file=tmp_path / "pages.json")
    await reg.load_entries()
    assert reg.get_settings_for_url("https://whop.com/never/app/") is None
    assert reg.get_settings_for_url(None) is None


@pytest.mark.asyncio
async def test_get_settings_for_url_matches_canonical_equivalent(
    patch_browser, settings_test, tmp_path
):
    bus = EventBus()
    reg = WhopRegistry(bus=bus, settings=settings_test, pages_file=tmp_path / "pages.json")
    await reg.load_entries()
    entry = await reg.add_page(url="https://whop.com/Joined/stock-and-option/app", source="stock")
    s = reg.get_settings_for_url("https://WHOP.com/joined/stock-and-option/app/")
    assert s is not None
    assert s is entry.settings


@pytest.mark.asyncio
async def test_clear_seen_for_url_resets_listener_cache(
    patch_browser, settings_test, tmp_path
):
    bus = EventBus()
    reg = WhopRegistry(bus=bus, settings=settings_test, pages_file=tmp_path / "pages.json")
    await reg.load_entries()
    entry = await reg.add_page(url="https://whop.com/clear/app", source="stock")
    await reg.start_page(entry.id)
    listener = reg.list_pages()[0][1]
    assert listener is not None
    listener._seen.update({"a", "b"})  # test-only internal state injection

    cleared = await reg.clear_seen_for_url("https://WHOP.com/clear/app/")
    assert cleared == 1
    assert listener._seen == set()
    await reg.shutdown_all()


@pytest.mark.asyncio
async def test_legacy_entry_without_settings_loads_default(patch_browser, settings_test, tmp_path):
    """A pages.json file written before settings existed should load with default settings."""
    pages_file = tmp_path / "pages.json"
    pages_file.write_text(
        json.dumps(
            [
                {
                    "id": "legacy1",
                    "url": "https://whop.com/legacy/app/",
                    "source": "stock",
                    "name": "Legacy",
                    "added_at": "2026-04-01T00:00:00+00:00",
                }
            ]
        )
    )
    bus = EventBus()
    reg = WhopRegistry(bus=bus, settings=settings_test, pages_file=pages_file)
    await reg.load_entries()
    s = reg.get_settings_for_url("https://whop.com/legacy/app/")
    assert s is not None
    assert s.tickers == {}
    assert s.price_deviation_tolerance == 1.0


@pytest.mark.asyncio
async def test_page_change_event_published_on_add(patch_browser, settings_test, tmp_path):
    bus = EventBus()
    received: list = []
    from app.core.events import Topics

    async def _handler(evt):
        received.append(evt.payload)

    bus.subscribe(Topics.WHOP_PAGE_CHANGED, _handler)
    reg = WhopRegistry(bus=bus, settings=settings_test, pages_file=tmp_path / "pages.json")
    await reg.load_entries()
    entry = await reg.add_page(url="https://whop.com/evt/app/", source="stock", name="evt")
    await bus.wait_idle()
    assert len(received) == 1
    assert received[0].action == "added"
    assert received[0].page_dict["id"] == entry.id


@pytest.mark.asyncio
async def test_page_change_event_published_on_settings_update(
    patch_browser, settings_test, tmp_path
):
    bus = EventBus()
    received: list = []
    from app.core.events import Topics

    async def _handler(evt):
        received.append(evt.payload)

    bus.subscribe(Topics.WHOP_PAGE_CHANGED, _handler)
    reg = WhopRegistry(bus=bus, settings=settings_test, pages_file=tmp_path / "pages.json")
    await reg.load_entries()
    entry = await reg.add_page(url="https://whop.com/evt2/app/", source="stock", name="evt2")
    await bus.wait_idle()
    received.clear()
    await reg.update_settings(entry.id, {"price_deviation_tolerance": 0.3})
    await bus.wait_idle()
    assert len(received) == 1
    assert received[0].action == "settings_updated"


@pytest.mark.asyncio
async def test_page_change_event_published_on_remove(patch_browser, settings_test, tmp_path):
    bus = EventBus()
    received: list = []
    from app.core.events import Topics

    async def _handler(evt):
        received.append(evt.payload)

    bus.subscribe(Topics.WHOP_PAGE_CHANGED, _handler)
    reg = WhopRegistry(bus=bus, settings=settings_test, pages_file=tmp_path / "pages.json")
    await reg.load_entries()
    entry = await reg.add_page(url="https://whop.com/del/app/", source="stock", name="del")
    await bus.wait_idle()
    received.clear()
    await reg.remove_page(entry.id)
    await bus.wait_idle()
    assert len(received) == 1
    assert received[0].action == "removed"


@pytest.mark.asyncio
async def test_page_change_event_published_on_restart(patch_browser, settings_test, tmp_path):
    bus = EventBus()
    received: list = []
    from app.core.events import Topics

    async def _handler(evt):
        received.append(evt.payload)

    bus.subscribe(Topics.WHOP_PAGE_CHANGED, _handler)
    reg = WhopRegistry(bus=bus, settings=settings_test, pages_file=tmp_path / "pages.json")
    await reg.load_entries()
    entry = await reg.add_page(url="https://whop.com/rst/app/", source="stock", name="rst")
    await reg.start_page(entry.id)
    await bus.wait_idle()
    received.clear()
    ok = await reg.restart_page(entry.id)
    await bus.wait_idle()
    assert ok is True
    assert len(received) == 1
    assert received[0].action == "restarted"
    assert received[0].page_dict["id"] == entry.id

    await reg.shutdown_all()


@pytest.mark.asyncio
async def test_page_change_event_published_on_start_and_stop(
    patch_browser, settings_test, tmp_path
):
    """start_page / stop_page each publish a page_changed event with the right action."""
    bus = EventBus()
    received: list = []
    from app.core.events import Topics

    async def _h(evt):
        received.append(evt.payload)

    bus.subscribe(Topics.WHOP_PAGE_CHANGED, _h)
    reg = WhopRegistry(bus=bus, settings=settings_test, pages_file=tmp_path / "pages.json")
    await reg.load_entries()
    entry = await reg.add_page(url="https://whop.com/evt/app/", source="stock", name="evt")
    await bus.wait_idle()
    received.clear()

    await reg.start_page(entry.id)
    await bus.wait_idle()
    assert any(p.action == "started" for p in received)

    received.clear()
    await reg.stop_page(entry.id)
    await bus.wait_idle()
    assert any(p.action == "stopped" for p in received)


@pytest.mark.asyncio
async def test_status_callback_publishes_page_changed_event(
    patch_browser: None, settings_test: Settings, tmp_path: Path
) -> None:
    """Invoking the registry's status callback publishes a WHOP_PAGE_CHANGED event.

    No live listener required — the callback resolves the entry from the registry
    dict and uses _build_page_dict, which works off the entry alone.
    """
    from app.core.events import Topics, WhopPagePayload

    bus = EventBus()
    received: list[Event] = []

    async def capture(evt: Event) -> None:
        received.append(evt)

    pages_file = tmp_path / "pages.json"
    registry = WhopRegistry(
        bus=bus, settings=settings_test, pages_file=pages_file
    )
    entry = await registry.add_page(url="https://whop.com/statuscb/app/", source="stock", name="X")

    # Subscribe AFTER add_page so we don't catch the "added" event.
    bus.subscribe(Topics.WHOP_PAGE_CHANGED, capture)

    cb = registry._make_status_callback(entry.id)
    await cb("errored")
    await bus.wait_idle(timeout=1)

    assert len(received) == 1
    payload = received[0].payload
    assert isinstance(payload, WhopPagePayload)
    assert payload.action == "errored"
    assert payload.page_dict["id"] == entry.id


@pytest.mark.asyncio
async def test_status_callback_silent_when_entry_missing(
    patch_browser: None, settings_test: Settings, tmp_path: Path
) -> None:
    """If the entry was removed before the callback fires, no event is published and no exception bubbles up."""
    from app.core.events import Topics

    bus = EventBus()
    received: list[Event] = []

    async def capture(evt: Event) -> None:
        received.append(evt)

    pages_file = tmp_path / "pages.json"
    registry = WhopRegistry(
        bus=bus, settings=settings_test, pages_file=pages_file
    )

    bus.subscribe(Topics.WHOP_PAGE_CHANGED, capture)

    cb = registry._make_status_callback("nonexistent-id")
    await cb("errored")  # must not raise
    await bus.wait_idle(timeout=1)

    assert received == []
