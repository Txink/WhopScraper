"""WhopRegistry tests — JSON persistence + listener lifecycle (with monkey-patched WhopBrowser)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.core.config import Settings
from app.core.event_bus import EventBus
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
