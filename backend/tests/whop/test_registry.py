"""WhopRegistry tests — JSON persistence + listener lifecycle (with monkey-patched WhopBrowser)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.core.config import Settings
from app.core.event_bus import EventBus
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
async def test_add_persists_and_starts(
    patch_browser: None, settings_test: Settings, tmp_path: Path
) -> None:
    """add_page: persists entry to JSON and starts a listener."""
    bus = EventBus()
    pages_file = tmp_path / "pages.json"
    reg = WhopRegistry(bus=bus, settings=settings_test, pages_file=pages_file)
    await reg.load_and_start_all()

    entry = await reg.add_page(
        url="https://whop.com/joined/abc/app/", source="stock", name="My Stock"
    )
    assert entry.id
    assert entry.source == "stock"

    # Persisted?
    saved = json.loads(pages_file.read_text())
    assert len(saved) == 1
    assert saved[0]["url"] == entry.url

    # Listener started?
    pages = reg.list_pages()
    assert len(pages) == 1
    e, ll = pages[0]
    assert ll is not None
    assert ll.running

    await reg.shutdown_all()


@pytest.mark.asyncio
async def test_remove_stops_listener_and_persists(
    patch_browser: None, settings_test: Settings, tmp_path: Path
) -> None:
    """remove_page: stops listener, clears entry from JSON."""
    bus = EventBus()
    pages_file = tmp_path / "pages.json"
    reg = WhopRegistry(bus=bus, settings=settings_test, pages_file=pages_file)
    await reg.load_and_start_all()

    entry = await reg.add_page(url="https://whop.com/joined/abc/app/", source="stock")
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
    await reg.load_and_start_all()
    assert (await reg.remove_page("does-not-exist")) is False


@pytest.mark.asyncio
async def test_add_rejects_duplicate_url(
    patch_browser: None, settings_test: Settings, tmp_path: Path
) -> None:
    """add_page raises ValueError when URL already monitored."""
    bus = EventBus()
    reg = WhopRegistry(bus=bus, settings=settings_test, pages_file=tmp_path / "p.json")
    await reg.load_and_start_all()
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
    await reg.load_and_start_all()
    with pytest.raises(ValueError, match="placeholder"):
        await reg.add_page(url="https://whop.com/joined/xxx/app/", source="stock")


@pytest.mark.asyncio
async def test_add_rejects_invalid_source(
    patch_browser: None, settings_test: Settings, tmp_path: Path
) -> None:
    """add_page raises ValueError for invalid source values."""
    bus = EventBus()
    reg = WhopRegistry(bus=bus, settings=settings_test, pages_file=tmp_path / "p.json")
    await reg.load_and_start_all()
    with pytest.raises(ValueError, match="source must be"):
        await reg.add_page(url="https://whop.com/joined/abc/app/", source="invalid")


@pytest.mark.asyncio
async def test_load_existing_file_starts_listeners(
    patch_browser: None, settings_test: Settings, tmp_path: Path
) -> None:
    """load_and_start_all: reads pre-existing JSON and starts listeners."""
    pages_file = tmp_path / "pages.json"
    pages_file.parent.mkdir(parents=True, exist_ok=True)
    pages_file.write_text(
        json.dumps([
            {
                "id": "abc123",
                "url": "https://whop.com/joined/real/app/",
                "source": "stock",
                "name": "Saved",
                "added_at": "2026-04-25T00:00:00+00:00",
            }
        ])
    )

    bus = EventBus()
    reg = WhopRegistry(bus=bus, settings=settings_test, pages_file=pages_file)
    await reg.load_and_start_all()

    pages = reg.list_pages()
    assert len(pages) == 1
    assert pages[0][1] is not None  # listener exists
    await reg.shutdown_all()


@pytest.mark.asyncio
async def test_restart_page(
    patch_browser: None, settings_test: Settings, tmp_path: Path
) -> None:
    """restart_page stops old listener and starts a new one."""
    bus = EventBus()
    pages_file = tmp_path / "pages.json"
    reg = WhopRegistry(bus=bus, settings=settings_test, pages_file=pages_file)
    await reg.load_and_start_all()

    entry = await reg.add_page(url="https://whop.com/joined/abc/app/", source="stock")

    # Get the original listener
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
    await reg.load_and_start_all()
    assert (await reg.restart_page("no-such-id")) is False


@pytest.mark.asyncio
async def test_shutdown_all_stops_all_listeners(
    patch_browser: None, settings_test: Settings, tmp_path: Path
) -> None:
    """shutdown_all stops all active listeners."""
    bus = EventBus()
    pages_file = tmp_path / "pages.json"
    reg = WhopRegistry(bus=bus, settings=settings_test, pages_file=pages_file)
    await reg.load_and_start_all()

    await reg.add_page(url="https://whop.com/joined/abc/app/", source="stock")
    await reg.add_page(url="https://whop.com/joined/def/app/", source="option")

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
    """load_and_start_all skips malformed entries without raising."""
    pages_file = tmp_path / "pages.json"
    pages_file.write_text(
        json.dumps([
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
        ])
    )

    bus = EventBus()
    reg = WhopRegistry(bus=bus, settings=settings_test, pages_file=pages_file)
    await reg.load_and_start_all()

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
    await reg.load_and_start_all()
    entry = await reg.add_page(url="https://whop.com/x/app/", source="stock", name="X")
    assert entry.settings.dedupe_processed_messages is True
    assert entry.settings.price_deviation_tolerance == 1.0
    assert entry.settings.tickers == {}


@pytest.mark.asyncio
async def test_add_page_option_default_settings(patch_browser, settings_test, tmp_path):
    bus = EventBus()
    reg = WhopRegistry(bus=bus, settings=settings_test, pages_file=tmp_path / "pages.json")
    await reg.load_and_start_all()
    entry = await reg.add_page(url="https://whop.com/o/app/", source="option", name="O")
    assert entry.settings.tickers is None
    assert entry.settings.price_deviation_tolerance == 5.0


@pytest.mark.asyncio
async def test_settings_persisted_in_json(patch_browser, settings_test, tmp_path):
    bus = EventBus()
    pages_file = tmp_path / "pages.json"
    reg = WhopRegistry(bus=bus, settings=settings_test, pages_file=pages_file)
    await reg.load_and_start_all()
    await reg.add_page(url="https://whop.com/p/app/", source="stock", name="P")

    raw = json.loads(pages_file.read_text())
    assert "settings" in raw[0]
    assert raw[0]["settings"]["price_deviation_tolerance"] == 1.0


@pytest.mark.asyncio
async def test_update_settings_persists_and_returns_entry(
    patch_browser, settings_test, tmp_path
):
    bus = EventBus()
    pages_file = tmp_path / "pages.json"
    reg = WhopRegistry(bus=bus, settings=settings_test, pages_file=pages_file)
    await reg.load_and_start_all()
    entry = await reg.add_page(url="https://whop.com/upd/app/", source="stock", name="upd")

    updated = await reg.update_settings(entry.id, {
        "tickers": {"NVDA": {"trade_quantity": 500}},
        "price_deviation_tolerance": 0.7,
    })
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
    await reg.load_and_start_all()
    with pytest.raises(KeyError):
        await reg.update_settings("does-not-exist", {})


@pytest.mark.asyncio
async def test_update_settings_option_rejects_tickers(patch_browser, settings_test, tmp_path):
    bus = EventBus()
    reg = WhopRegistry(bus=bus, settings=settings_test, pages_file=tmp_path / "pages.json")
    await reg.load_and_start_all()
    entry = await reg.add_page(url="https://whop.com/optx/app/", source="option", name="optx")
    with pytest.raises(ValueError, match="tickers"):
        await reg.update_settings(entry.id, {"tickers": {"AAPL": {"trade_quantity": 1}}})


@pytest.mark.asyncio
async def test_get_settings_for_url_match(patch_browser, settings_test, tmp_path):
    bus = EventBus()
    reg = WhopRegistry(bus=bus, settings=settings_test, pages_file=tmp_path / "pages.json")
    await reg.load_and_start_all()
    entry = await reg.add_page(url="https://whop.com/lookup/app/", source="stock", name="lk")
    s = reg.get_settings_for_url(entry.url)
    assert s is not None
    assert s.dedupe_processed_messages is True


@pytest.mark.asyncio
async def test_get_settings_for_url_orphan(patch_browser, settings_test, tmp_path):
    bus = EventBus()
    reg = WhopRegistry(bus=bus, settings=settings_test, pages_file=tmp_path / "pages.json")
    await reg.load_and_start_all()
    assert reg.get_settings_for_url("https://whop.com/never/app/") is None
    assert reg.get_settings_for_url(None) is None


@pytest.mark.asyncio
async def test_legacy_entry_without_settings_loads_default(
    patch_browser, settings_test, tmp_path
):
    """A pages.json file written before settings existed should load with default settings."""
    pages_file = tmp_path / "pages.json"
    pages_file.write_text(json.dumps([
        {"id": "legacy1", "url": "https://whop.com/legacy/app/", "source": "stock",
         "name": "Legacy", "added_at": "2026-04-01T00:00:00+00:00"}
    ]))
    bus = EventBus()
    reg = WhopRegistry(bus=bus, settings=settings_test, pages_file=pages_file)
    await reg.load_and_start_all()
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
    await reg.load_and_start_all()
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
    await reg.load_and_start_all()
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
    await reg.load_and_start_all()
    entry = await reg.add_page(url="https://whop.com/del/app/", source="stock", name="del")
    await bus.wait_idle()
    received.clear()
    await reg.remove_page(entry.id)
    await bus.wait_idle()
    assert len(received) == 1
    assert received[0].action == "removed"
