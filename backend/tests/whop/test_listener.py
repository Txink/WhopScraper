"""Tests for WhopListener — dedup + publish logic.

Uses a fake browser to avoid launching real Playwright. The WhopBrowser class
is monkey-patched inside the listener module so no network or browser process
is needed.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from app.core.event_bus import Event, EventBus
from app.core.events import MessagePayload, Topics
from app.domain.message import Message
from app.whop.extractor import parse_whop_timestamp
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
        _msg_html("post_1") + _msg_html("post_2"),  # initial scrape — skipped
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


# ---------------------------------------------------------------------------
# is_historical tagging (T5)
# ---------------------------------------------------------------------------


def _historical_test_msg(mid: str, posted_at: datetime | None) -> Message:
    return Message(
        id=mid,
        content=f"hello {mid}",
        raw_content=f"hello {mid}",
        author=None,
        posted_at=posted_at,  # type: ignore[arg-type]
        received_at=datetime.now(UTC),
        source="stock",
        url=None,
        quoted=None,
        history_hint=[],
    )


@pytest.mark.asyncio
async def test_scan_once_marks_messages_as_historical_when_posted_before_started_at(
    monkeypatch, patch_browser
) -> None:
    """posted_at < started_at → is_historical=True; posted_at > started_at → False."""
    started_at = datetime(2026, 4, 28, 12, 0, 0, tzinfo=UTC)
    old = _historical_test_msg("hist-old", started_at - timedelta(hours=1))
    new = _historical_test_msg("hist-new", started_at + timedelta(seconds=30))

    # Patch extractor BEFORE start() so the first scan returns our synthetic messages.
    monkeypatch.setattr(
        "app.whop.listener.extract_messages",
        lambda html, source, received_at=None: [old, new],
    )
    patch_browser(["<html></html>", "<html></html>"])

    captured: list[MessagePayload] = []

    async def capture(evt: Event) -> None:
        captured.append(evt.payload)

    bus = EventBus()
    bus.subscribe(Topics.MESSAGE_RECEIVED, capture)

    listener = WhopListener(
        bus=bus,
        url="http://test",
        source="stock",
        poll_interval=0.05,
        skip_initial=False,
    )
    # Pin started_at so the comparison is deterministic regardless of wall clock.
    await listener.start()
    listener._started_at = started_at  # override the auto-set value for determinism
    # Trigger one scan; start() already kicked off _loop; sleep briefly to ensure publication.
    await asyncio.sleep(0.15)
    await listener.stop()
    await bus.wait_idle(timeout=1)

    by_id = {p.message.id: p for p in captured}
    assert "hist-old" in by_id, f"missing old message in {list(by_id)}"
    assert "hist-new" in by_id, f"missing new message in {list(by_id)}"
    assert by_id["hist-old"].is_historical is True
    assert by_id["hist-new"].is_historical is False


@pytest.mark.asyncio
async def test_scan_once_treats_missing_posted_at_as_not_historical(
    monkeypatch, patch_browser
) -> None:
    """posted_at None → is_historical=False (defensive default)."""
    started_at = datetime(2026, 4, 28, 12, 0, 0, tzinfo=UTC)
    msg_no_posted = _historical_test_msg("hist-nopost", None)

    monkeypatch.setattr(
        "app.whop.listener.extract_messages",
        lambda html, source, received_at=None: [msg_no_posted],
    )
    patch_browser(["<html></html>"])

    captured: list[MessagePayload] = []
    bus = EventBus()
    bus.subscribe(Topics.MESSAGE_RECEIVED, lambda e: captured.append(e.payload))

    listener = WhopListener(
        bus=bus, url="http://test", source="stock",
        poll_interval=0.05, skip_initial=False,
    )
    await listener.start()
    listener._started_at = started_at
    await asyncio.sleep(0.15)
    await listener.stop()
    await bus.wait_idle(timeout=1)

    assert len(captured) >= 1
    payload = next(p for p in captured if p.message.id == "hist-nopost")
    assert payload.is_historical is False


def test_historical_marker_does_not_misclassify_across_utc_beijing_date_boundary() -> None:
    """At Beijing Apr 28 03:02 (= UTC Apr 27 19:02), a Whop 'Today at 6 PM'
    message means Beijing Apr 28 18:00 = UTC Apr 28 10:00. That instant is
    in the FUTURE relative to listener start, so is_historical must be False.
    Regression for the bug that surfaced when block_historical_messages was
    enabled at 03:02 local time."""

    # Anchor "now" so the parser sees Beijing Apr 28 03:02.
    fake_now = datetime(2026, 4, 27, 19, 2, 0, tzinfo=UTC)

    started_at = fake_now  # listener started "just now"
    posted_at = parse_whop_timestamp("Today at 6:00 PM", now=fake_now)
    assert posted_at == datetime(2026, 4, 28, 10, 0, 0, tzinfo=UTC)

    # Replicate the listener's exact comparison.
    is_historical = (
        posted_at is not None
        and posted_at.astimezone(UTC) < started_at
    )
    assert is_historical is False, (
        f"Today's message (posted_at={posted_at}) wrongly marked historical "
        f"vs started_at={started_at}"
    )


# ---------------------------------------------------------------------------
# on_status_change callback + _safe_status_callback helper
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_safe_status_callback_noop_when_none() -> None:
    """_safe_status_callback returns silently when no callback is wired."""
    listener = WhopListener(
        bus=EventBus(),
        url="http://test",
        source="stock",
        poll_interval=0.05,
        on_status_change=None,
    )
    # Should not raise.
    await listener._safe_status_callback("errored")


@pytest.mark.asyncio
async def test_safe_status_callback_swallows_exceptions(caplog: pytest.LogCaptureFixture) -> None:
    """A raising callback must not propagate — it's logged and absorbed."""
    async def boom(_action: str) -> None:
        raise RuntimeError("intentional")

    listener = WhopListener(
        bus=EventBus(),
        url="http://test",
        source="stock",
        poll_interval=0.05,
        on_status_change=boom,
    )
    with caplog.at_level("WARNING"):
        await listener._safe_status_callback("errored")
    assert any("status callback failed" in r.getMessage() for r in caplog.records)
