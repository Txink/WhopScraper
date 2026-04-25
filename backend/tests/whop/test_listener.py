"""Tests for WhopListener — dedup + publish logic.

Uses a fake browser to avoid launching real Playwright. The WhopBrowser class
is monkey-patched inside the listener module so no network or browser process
is needed.
"""
from __future__ import annotations

import asyncio

import pytest

from app.core.event_bus import Event, EventBus
from app.core.events import Topics
from app.whop.listener import WhopListener  # noqa: E402

# ---------------------------------------------------------------------------
# Fake browser
# ---------------------------------------------------------------------------


class _FakeBrowser:
    """Minimal WhopBrowser stand-in that returns HTML from a pre-loaded sequence."""

    def __init__(self, html_sequence: list[str]) -> None:
        self._htmls = list(html_sequence)
        self._idx = 0
        self.closed = False

    async def start(self):  # noqa: ANN201
        return None  # real WhopBrowser returns a Page; tests don't need it

    async def navigate(self, url: str) -> bool:  # noqa: ARG002
        return True

    async def scrape_html(self) -> str:
        if self._idx < len(self._htmls):
            html = self._htmls[self._idx]
            self._idx += 1
        else:
            html = self._htmls[-1] if self._htmls else "<html></html>"
        return html

    async def close(self) -> None:
        self.closed = True


# ---------------------------------------------------------------------------
# HTML helpers
# ---------------------------------------------------------------------------


def _msg_html(msg_id: str, body: str = "test") -> str:
    """Return minimal Whop-shaped message HTML for a single message."""
    return (
        f'<div data-message-id="{msg_id}" '
        f'data-has-message-above="false" data-has-message-below="false">'
        f'<span role="button" class="truncate fui-HoverCardTrigger">tester</span>'
        f'<div class="bg-gray-3 rounded">'
        f'<div class="whitespace-pre-wrap"><p>{body}</p></div>'
        f"</div>"
        f"</div>"
    )


# ---------------------------------------------------------------------------
# Fixture: patch WhopBrowser inside listener module
# ---------------------------------------------------------------------------


@pytest.fixture
def patch_browser(monkeypatch):
    """Replace app.whop.listener.WhopBrowser with a factory that returns _FakeBrowser.

    Usage:
        instances = patch_browser(html_sequence)
        # instances is a list; after start() it contains the created _FakeBrowser.
    """

    def _setup(html_seq: list[str]) -> list[_FakeBrowser]:
        instances: list[_FakeBrowser] = []

        def _factory(*args, **kwargs) -> _FakeBrowser:  # noqa: ARG001
            b = _FakeBrowser(html_seq)
            instances.append(b)
            return b

        monkeypatch.setattr("app.whop.listener.WhopBrowser", _factory)
        return instances

    return _setup


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_listener_publishes_new_messages(patch_browser) -> None:
    """Messages from each poll are published; messages from multiple scrapes all appear."""
    htmls = [
        _msg_html("post_1", "first") + _msg_html("post_2", "second"),
        _msg_html("post_1") + _msg_html("post_2") + _msg_html("post_3", "third"),
    ]
    patch_browser(htmls)

    bus = EventBus()
    received: list[Event] = []

    async def capture(evt: Event) -> None:
        received.append(evt)

    bus.subscribe(Topics.MESSAGE_RECEIVED, capture)

    listener = WhopListener(
        bus=bus,
        url="http://test",
        source="stock",
        poll_interval=0.05,
        skip_initial=False,
    )
    await listener.start()
    await asyncio.sleep(0.2)
    await listener.stop()
    await bus.wait_idle(timeout=1)

    ids = [evt.payload.message.id for evt in received]
    assert "post_1" in ids
    assert "post_2" in ids
    assert "post_3" in ids


@pytest.mark.asyncio
async def test_listener_skip_initial_primes_seen_set(patch_browser) -> None:
    """skip_initial=True primes seen IDs from first scrape; only new messages are published."""
    htmls = [
        _msg_html("post_1") + _msg_html("post_2"),             # initial scrape — skipped
        _msg_html("post_1") + _msg_html("post_2") + _msg_html("post_3"),  # only post_3 is new
    ]
    patch_browser(htmls)

    bus = EventBus()
    received: list[Event] = []

    async def capture(evt: Event) -> None:
        received.append(evt)

    bus.subscribe(Topics.MESSAGE_RECEIVED, capture)

    listener = WhopListener(
        bus=bus,
        url="http://test",
        source="stock",
        poll_interval=0.05,
        skip_initial=True,
    )
    await listener.start()
    await asyncio.sleep(0.2)
    await listener.stop()
    await bus.wait_idle(timeout=1)

    ids = [evt.payload.message.id for evt in received]
    assert "post_1" not in ids
    assert "post_2" not in ids
    assert "post_3" in ids


@pytest.mark.asyncio
async def test_listener_dedupes_same_message_across_polls(patch_browser) -> None:
    """A message present in every scrape is published exactly once."""
    same_html = _msg_html("post_only")
    patch_browser([same_html, same_html, same_html])

    bus = EventBus()
    received: list[Event] = []

    async def capture(evt: Event) -> None:
        received.append(evt)

    bus.subscribe(Topics.MESSAGE_RECEIVED, capture)

    listener = WhopListener(
        bus=bus,
        url="http://test",
        source="stock",
        poll_interval=0.03,
        skip_initial=False,
    )
    await listener.start()
    await asyncio.sleep(0.15)
    await listener.stop()
    await bus.wait_idle(timeout=1)

    ids = [evt.payload.message.id for evt in received]
    assert ids.count("post_only") == 1


@pytest.mark.asyncio
async def test_listener_handles_browser_navigate_failure(monkeypatch) -> None:
    """If navigate() returns False on start(), RuntimeError is raised and browser is closed."""

    class _BadBrowser(_FakeBrowser):
        async def navigate(self, url: str) -> bool:  # noqa: ARG002
            return False

    instances: list[_BadBrowser] = []

    def _factory(*args, **kwargs) -> _BadBrowser:  # noqa: ARG001
        b = _BadBrowser([])
        instances.append(b)
        return b

    monkeypatch.setattr("app.whop.listener.WhopBrowser", _factory)

    bus = EventBus()
    listener = WhopListener(bus=bus, url="http://x", source="stock", poll_interval=0.05)

    with pytest.raises(RuntimeError):
        await listener.start()

    assert len(instances) == 1
    assert instances[0].closed is True


# ---------------------------------------------------------------------------
# register_whop_listeners — placeholder / missing URL detection
# ---------------------------------------------------------------------------


def test_register_skips_placeholder_urls() -> None:
    """Listener factory must skip placeholder/example URLs without launching Playwright."""
    from types import SimpleNamespace

    from app.whop.listener import register_whop_listeners

    settings = SimpleNamespace(
        whop_stock_url="https://whop.com/joined/stock-and-option/xxx/app/",
        whop_option_url="",
        whop_poll_interval=2.0,
        whop_headless=True,
    )
    bus = EventBus()
    listeners = register_whop_listeners(bus, settings)  # type: ignore[arg-type]
    assert listeners == []


def test_register_skips_empty_urls() -> None:
    """Empty string URLs (default .env.example) must also produce no listeners."""
    from types import SimpleNamespace

    from app.whop.listener import register_whop_listeners

    settings = SimpleNamespace(
        whop_stock_url=None,
        whop_option_url=None,
        whop_poll_interval=2.0,
        whop_headless=True,
    )
    bus = EventBus()
    listeners = register_whop_listeners(bus, settings)  # type: ignore[arg-type]
    assert listeners == []


def test_register_creates_listeners_for_real_urls() -> None:
    """Real URLs (no placeholder tokens) must produce listeners."""
    from types import SimpleNamespace

    from app.whop.listener import register_whop_listeners

    settings = SimpleNamespace(
        whop_stock_url="https://whop.com/joined/stock-and-option/abc123/app/",
        whop_option_url="https://whop.com/joined/stock-and-option/def456/app/",
        whop_poll_interval=2.0,
        whop_headless=True,
    )
    bus = EventBus()
    listeners = register_whop_listeners(bus, settings)  # type: ignore[arg-type]
    assert len(listeners) == 2
    assert listeners[0]._source == "stock"
    assert listeners[1]._source == "option"
