"""Tests for app/whop/extractor.py — pure-function DOM → Message parser."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from textwrap import dedent

import pytest

from app.whop.extractor import extract_messages

# ---------------------------------------------------------------------------
# Fixture paths (skip if not present on this machine)
# ---------------------------------------------------------------------------
WORKTREE_ROOT = Path(__file__).resolve().parents[3]
STOCK_FIXTURE = WORKTREE_ROOT / "tmp" / "stock" / "page_html.html"
OPTION_FIXTURE = WORKTREE_ROOT / "tmp" / "option" / "page_html.html"


# ---------------------------------------------------------------------------
# Synthetic HTML that mirrors the real Whop DOM structure.
# Based on docs/dom_structure_guide.md — production DOM attributes.
# ---------------------------------------------------------------------------


def _whop_page(inner_html: str) -> str:
    """Wrap inner_html in a minimal Whop-like page skeleton."""
    return dedent(f"""\
        <!DOCTYPE html>
        <html>
          <body>
            <div class="message-list">
              {inner_html}
            </div>
          </body>
        </html>
    """)


def _single_message(
    msg_id: str,
    author: str,
    timestamp: str,
    content: str,
    quote_content: str = "",
    quote_author: str = "quoted_user",
    has_above: str = "false",
    has_below: str = "false",
) -> str:
    """Build a single Whop message element matching real DOM structure.

    Quote block, when ``quote_content`` is set, mirrors the real Whop DOM:
    avatar + author span (``fui-r-weight-medium``) + content span. The
    extractor requires both author and content to keep a quote — see
    ``_extract_quote`` in extractor.py.
    """
    quote_block = ""
    if quote_content:
        quote_block = f"""\
            <div class="peer/reply relative mb-1.5">
              <div class="flex items-center gap-1.5 truncate">
                <span class="fui-AvatarRoot size-5">
                  <span class="fui-AvatarFallback hidden">X</span>
                </span>
                <span class="fui-Text truncate fui-r-size-1 fui-r-weight-medium">{quote_author}</span>
                <span class="fui-Text truncate fui-r-size-1">{quote_content}</span>
              </div>
            </div>"""

    return f"""\
      <div class="group/message"
           data-message-id="{msg_id}"
           data-is-own-message="false"
           data-has-message-above="{has_above}"
           data-has-message-below="{has_below}">
        <span class="fui-AvatarRoot size-8 fui-r-size-3 fui-shape-circle">
          <span class="fui-AvatarFallback fui-one-letter hidden">X</span>
          <img alt="avatar" class="fui-AvatarImage" src="https://img.whop.com/avatar.jpg">
        </span>
        <span class="text-1 text-gray-10 inline-flex items-center gap-1">
          <span role="button" class="truncate cursor-pointer hover:underline fui-HoverCardTrigger"
                tabindex="0">{author}</span>
          <div class="flex shrink-0 items-center gap-1">
            <span>•</span>
            <span>{timestamp}</span>
          </div>
        </span>
        {quote_block}
        <div class="bg-gray-3 rounded-[18px] px-3 py-1.5 text-[15px]">
          <div class="text-[15px] whitespace-pre-wrap"><p>{content}</p></div>
          <svg fill="none" height="16" width="16"><title>Tail</title></svg>
        </div>
        <span class="text-gray-11 text-0 h-[15px] px-0.5">由 42阅读</span>
      </div>"""


def _continuation_message(
    msg_id: str,
    content: str,
    has_above: str = "true",
    has_below: str = "false",
) -> str:
    """Build a continuation (middle/last) message in a group (no header)."""
    return f"""\
      <div class="group/message"
           data-message-id="{msg_id}"
           data-is-own-message="false"
           data-has-message-above="{has_above}"
           data-has-message-below="{has_below}">
        <div class="bg-gray-3 rounded-[18px] rounded-tl-lg px-3 py-1.5 text-[15px]">
          <div class="text-[15px] whitespace-pre-wrap"><p>{content}</p></div>
          <svg fill="none" height="16" width="16"><title>Tail</title></svg>
        </div>
        <span class="text-gray-11 text-0 h-[15px] px-0.5">由 15阅读</span>
      </div>"""


# ---------------------------------------------------------------------------
# Fixture-based tests (skip when HTML file is absent)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not STOCK_FIXTURE.is_file(), reason="stock fixture not present")
def test_extract_stock_html_produces_messages() -> None:
    html = STOCK_FIXTURE.read_text(encoding="utf-8")
    messages = extract_messages(html, source="stock")
    assert len(messages) > 0, "should extract at least one message from real DOM"
    # All IDs must be unique
    ids = [m.id for m in messages]
    assert len(ids) == len(set(ids)), "message IDs must be unique"
    # All messages have non-empty content
    for m in messages:
        assert m.content, f"message {m.id} has empty content"
        assert m.source == "stock"


@pytest.mark.skipif(not OPTION_FIXTURE.is_file(), reason="option fixture not present")
def test_extract_option_html_produces_messages() -> None:
    html = OPTION_FIXTURE.read_text(encoding="utf-8")
    messages = extract_messages(html, source="option")
    assert len(messages) > 0
    for m in messages:
        assert m.source == "option"


# ---------------------------------------------------------------------------
# Synthetic unit tests
# ---------------------------------------------------------------------------


def test_extract_empty_html_returns_empty() -> None:
    assert extract_messages("<html></html>", source="stock") == []


def test_extract_single_stock_message() -> None:
    html = _whop_page(
        _single_message(
            "post_abc123",
            "xiaozhaolucky",
            "Jan 23, 2026 12:51 AM",
            "nvda剩下部分也2.45附近出",
        )
    )
    msgs = extract_messages(html, source="stock")
    assert len(msgs) == 1
    m = msgs[0]
    assert m.id == "post_abc123"
    assert "nvda" in m.content.lower() or "nvda" in m.raw_content.lower()
    assert m.author == "xiaozhaolucky"
    assert m.source == "stock"
    # Beijing 12:51 AM Jan 23 → UTC 4:51 PM Jan 22
    assert m.posted_at == datetime(2026, 1, 22, 16, 51, tzinfo=UTC)
    assert m.quoted is None


def test_extract_preserves_raw_content_with_emoji() -> None:
    html = _whop_page(
        _single_message(
            "post_emoji1",
            "trader_x",
            "Apr 24, 2026 10:00 AM",
            "NVDA 135C 本周 2.15 进 🚀",
        )
    )
    msgs = extract_messages(html, source="option")
    assert len(msgs) == 1
    m = msgs[0]
    # raw_content should preserve the emoji
    assert "🚀" in m.raw_content
    # content might or might not have emoji, but must be non-empty
    assert m.content


def test_extract_message_with_quote() -> None:
    html = _whop_page(
        _single_message(
            "post_reply1",
            "user_b",
            "Apr 24, 2026 11:00 AM",
            "已出",
            quote_content="GILD - $130 CALLS 这周 1.5-1.60",
            quote_author="zhouzhou chen",
        )
    )
    msgs = extract_messages(html, source="stock")
    assert len(msgs) == 1
    m = msgs[0]
    assert m.quoted is not None
    assert "GILD" in m.quoted.content or "GILD" in m.quoted.raw_content
    assert m.quoted.id == "post_reply1-quoted"
    # Author must be captured too — the API drops quotes whose author is
    # NULL (see _row_to_quoted gating in http.py).
    assert m.quoted.author == "zhouzhou chen"


def test_extract_multiple_messages_unique_ids() -> None:
    inner = "\n".join(
        [
            _single_message(f"post_{i}", "author", "Jan 1, 2026 1:00 AM", f"content {i}")
            for i in range(5)
        ]
    )
    html = _whop_page(inner)
    msgs = extract_messages(html, source="stock")
    assert len(msgs) == 5
    ids = [m.id for m in msgs]
    assert len(ids) == len(set(ids)), "all message IDs must be unique"


def test_extract_metadata_messages_filtered() -> None:
    """Messages containing only metadata (read count, Tail, timestamps) are dropped."""
    # Build a message where the only text content is read-count noise
    noise_html = """\
      <div class="group/message"
           data-message-id="post_noise1"
           data-has-message-above="false"
           data-has-message-below="false">
        <span class="text-gray-11 text-0 h-[15px]">由 268阅读</span>
        <svg><title>Tail</title></svg>
      </div>"""
    html = _whop_page(noise_html)
    msgs = extract_messages(html, source="stock")
    assert len(msgs) == 0, "read-count-only message should be filtered out"


def test_extract_message_group_inherits_author_and_timestamp() -> None:
    """Continuation messages in a group inherit author + timestamp from group start."""
    inner = (
        _single_message(
            "post_g1",
            "groupauthor",
            "Apr 24, 2026 9:00 AM",
            "first message",
            has_above="false",
            has_below="true",
        )
        + "\n"
        + _continuation_message(
            "post_g2",
            "second message in group",
            has_above="true",
            has_below="false",
        )
    )
    html = _whop_page(inner)
    msgs = extract_messages(html, source="stock")
    assert len(msgs) == 2
    first, second = msgs
    # Both from the same group — continuation inherits author
    assert first.author == "groupauthor"
    assert second.author == "groupauthor"
    # Both share the same minute (parsed from "Apr 24, 2026 9:00 AM" Beijing → 01:00 UTC);
    # subminute seconds are 0, 1 respectively.
    assert first.posted_at == datetime(2026, 4, 24, 1, 0, 0, tzinfo=UTC)
    assert second.posted_at == datetime(2026, 4, 24, 1, 0, 1, tzinfo=UTC)


def test_extract_source_tagged_correctly() -> None:
    html = _whop_page(
        _single_message("post_opt1", "author", "Jan 1, 2026 1:00 AM", "some option text")
    )
    msgs = extract_messages(html, source="option")
    assert all(m.source == "option" for m in msgs)


def test_received_at_defaults_to_now() -> None:
    html = _whop_page(_single_message("post_now1", "author", "Jan 1, 2026 1:00 AM", "hello"))
    before = datetime.now(UTC)
    msgs = extract_messages(html, source="stock")
    after = datetime.now(UTC)
    assert len(msgs) == 1
    assert before <= msgs[0].received_at <= after


def test_received_at_custom_value_propagated() -> None:
    fixed_ts = datetime(2026, 4, 24, 12, 0, 0, tzinfo=UTC)
    html = _whop_page(_single_message("post_custom1", "author", "Jan 1, 2026 1:00 AM", "hello"))
    msgs = extract_messages(html, source="stock", received_at=fixed_ts)
    assert msgs[0].received_at == fixed_ts


def test_history_hint_always_empty() -> None:
    html = _whop_page(_single_message("post_h1", "author", "Jan 1, 2026 1:00 AM", "content"))
    msgs = extract_messages(html, source="stock")
    assert msgs[0].history_hint == []


def test_absolute_timestamp_pm_parsed_correctly() -> None:
    """12-hour AM/PM timestamps converted as Beijing wall-clock → real UTC."""
    # "Jan 23, 2026 12:51 AM" Beijing → midnight BJT → UTC 16:51 the previous day
    html_am = _whop_page(_single_message("post_am", "a", "Jan 23, 2026 12:51 AM", "am msg"))
    msgs_am = extract_messages(html_am, source="stock")
    assert msgs_am[0].posted_at.hour == 16
    assert msgs_am[0].posted_at.minute == 51

    # "Jan 23, 2026 12:51 PM" Beijing → noon BJT → UTC 04:51 same day
    html_pm = _whop_page(_single_message("post_pm", "a", "Jan 23, 2026 12:51 PM", "pm msg"))
    msgs_pm = extract_messages(html_pm, source="stock")
    assert msgs_pm[0].posted_at.hour == 4
    assert msgs_pm[0].posted_at.minute == 51


def test_system_notification_no_data_message_id_skipped() -> None:
    """Elements without data-message-id are not picked up."""
    html = _whop_page(
        """\
        <div class="system-notification">System: channel created</div>
        """
    )
    assert extract_messages(html, source="stock") == []


# ---------------------------------------------------------------------------
# parse_whop_timestamp unit tests
# ---------------------------------------------------------------------------

from app.domain.message import Message  # noqa: E402
from app.whop.extractor import _assign_subminute_seconds, parse_whop_timestamp  # noqa: E402

# Pin "now" deterministically. _NOW is Saturday 2026-04-25 20:00 Beijing
# (= 12:00 UTC). Beijing "today" therefore = Apr 25 2026.
_NOW = datetime(2026, 4, 25, 12, 0, 0, tzinfo=UTC)


def test_parse_today_at() -> None:
    # Beijing 14:30 Apr 25 → UTC 06:30 Apr 25
    got = parse_whop_timestamp("Today at 2:30 PM", now=_NOW)
    assert got == datetime(2026, 4, 25, 6, 30, 0, tzinfo=UTC)


def test_parse_today_no_at() -> None:
    got = parse_whop_timestamp("Today 2:30 PM", now=_NOW)
    assert got == datetime(2026, 4, 25, 6, 30, 0, tzinfo=UTC)


def test_parse_yesterday_at() -> None:
    # Beijing 23:24 Apr 24 → UTC 15:24 Apr 24
    got = parse_whop_timestamp("Yesterday at 11:24 PM", now=_NOW)
    assert got == datetime(2026, 4, 24, 15, 24, 0, tzinfo=UTC)


def test_parse_yesterday_no_at() -> None:
    got = parse_whop_timestamp("Yesterday 11:24 PM", now=_NOW)
    assert got == datetime(2026, 4, 24, 15, 24, 0, tzinfo=UTC)


def test_parse_thursday_at() -> None:
    # Beijing now is Sat Apr 25; Thursday = Apr 23. Beijing 11:35 → UTC 03:35
    got = parse_whop_timestamp("Thursday at 11:35 AM", now=_NOW)
    assert got == datetime(2026, 4, 23, 3, 35, 0, tzinfo=UTC)


def test_parse_weekday_no_at() -> None:
    got = parse_whop_timestamp("Thursday 11:35 AM", now=_NOW)
    assert got == datetime(2026, 4, 23, 3, 35, 0, tzinfo=UTC)


def test_parse_full_date_with_year() -> None:
    # Beijing 17:43 Apr 13 → UTC 09:43 Apr 13
    got = parse_whop_timestamp("Apr 13, 2026 5:43 PM", now=_NOW)
    assert got == datetime(2026, 4, 13, 9, 43, 0, tzinfo=UTC)


def test_parse_full_date_implicit_year() -> None:
    got = parse_whop_timestamp("Apr 13 5:43 PM", now=_NOW)
    assert got == datetime(2026, 4, 13, 9, 43, 0, tzinfo=UTC)


def test_parse_weekday_when_today_same_weekday() -> None:
    # Beijing now = Sat Apr 25; "Saturday" must mean LAST Saturday (Apr 18).
    # Beijing 09:00 Apr 18 → UTC 01:00 Apr 18
    got = parse_whop_timestamp("Saturday at 9:00 AM", now=_NOW)
    assert got == datetime(2026, 4, 18, 1, 0, 0, tzinfo=UTC)


def test_parse_midnight_am() -> None:
    # 12:51 AM Beijing → 16:51 UTC the previous day
    got = parse_whop_timestamp("Apr 13, 2026 12:51 AM", now=_NOW)
    assert got is not None
    assert got == datetime(2026, 4, 12, 16, 51, 0, tzinfo=UTC)


def test_parse_noon_pm() -> None:
    # 12:00 PM Beijing → 04:00 UTC same day
    got = parse_whop_timestamp("Apr 13, 2026 12:00 PM", now=_NOW)
    assert got is not None
    assert got == datetime(2026, 4, 13, 4, 0, 0, tzinfo=UTC)


def test_parse_garbage_returns_none() -> None:
    assert parse_whop_timestamp("not a real timestamp", now=_NOW) is None
    assert parse_whop_timestamp("", now=_NOW) is None


def test_parse_today_when_utc_and_beijing_dates_differ() -> None:
    """Regression: real-world bug.

    At 2026-04-28 03:02 Beijing the UTC clock still reads 2026-04-27 19:02.
    A Whop "Today at 6:00 PM" message must resolve to Beijing Apr 28 18:00,
    not Apr 27 18:00. (The old UTC-date logic produced the wrong day.)
    """
    now = datetime(2026, 4, 27, 19, 2, 0, tzinfo=UTC)  # = 2026-04-28 03:02 Beijing
    got = parse_whop_timestamp("Today at 6:00 PM", now=now)
    # Beijing 18:00 Apr 28 → UTC 10:00 Apr 28
    assert got == datetime(2026, 4, 28, 10, 0, 0, tzinfo=UTC)


def test_parse_yesterday_when_utc_and_beijing_dates_differ() -> None:
    """At Beijing Apr 28 03:02 (UTC Apr 27 19:02), "Yesterday" = Beijing Apr 27."""
    now = datetime(2026, 4, 27, 19, 2, 0, tzinfo=UTC)
    got = parse_whop_timestamp("Yesterday at 11:00 AM", now=now)
    # Beijing 11:00 Apr 27 → UTC 03:00 Apr 27
    assert got == datetime(2026, 4, 27, 3, 0, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# _assign_subminute_seconds unit tests
# ---------------------------------------------------------------------------


def _make_msg(id_: str, posted_at: datetime) -> Message:
    return Message(
        id=id_,
        content="x",
        raw_content="x",
        author=None,
        posted_at=posted_at,
        received_at=posted_at,
        source="stock",
    )


def test_subminute_seconds_increments_within_minute() -> None:
    base = datetime(2026, 4, 25, 10, 30, 0, tzinfo=UTC)
    msgs = [_make_msg("a", base), _make_msg("b", base), _make_msg("c", base)]
    out = _assign_subminute_seconds(msgs)
    assert [m.posted_at.second for m in out] == [0, 1, 2]  # type: ignore[union-attr]


def test_subminute_seconds_resets_on_new_minute() -> None:
    msgs = [
        _make_msg("a", datetime(2026, 4, 25, 10, 30, 0, tzinfo=UTC)),
        _make_msg("b", datetime(2026, 4, 25, 10, 30, 0, tzinfo=UTC)),
        _make_msg("c", datetime(2026, 4, 25, 10, 31, 0, tzinfo=UTC)),
        _make_msg("d", datetime(2026, 4, 25, 10, 31, 0, tzinfo=UTC)),
    ]
    out = _assign_subminute_seconds(msgs)
    assert [m.posted_at.second for m in out] == [0, 1, 0, 1]  # type: ignore[union-attr]


def test_subminute_seconds_single_message() -> None:
    msg = _make_msg("a", datetime(2026, 4, 25, 10, 30, 0, tzinfo=UTC))
    out = _assign_subminute_seconds([msg])
    assert out[0].posted_at.second == 0  # type: ignore[union-attr]


def test_subminute_seconds_overflows_into_microsecond_past_60() -> None:
    """Chat-source bursts can exceed 60 msgs in a single minute; seq>=60
    overflows into microsecond rather than crashing on replace(second=60)."""
    base = datetime(2026, 4, 25, 10, 30, 0, tzinfo=UTC)
    msgs = [_make_msg(f"m{i}", base) for i in range(62)]
    out = _assign_subminute_seconds(msgs)
    # 0..59 → second=0..59, microsecond=0
    for i in range(60):
        assert out[i].posted_at.second == i  # type: ignore[union-attr]
        assert out[i].posted_at.microsecond == 0  # type: ignore[union-attr]
    # 60, 61 → second=59, microsecond=1, 2
    assert out[60].posted_at.second == 59  # type: ignore[union-attr]
    assert out[60].posted_at.microsecond == 1  # type: ignore[union-attr]
    assert out[61].posted_at.second == 59  # type: ignore[union-attr]
    assert out[61].posted_at.microsecond == 2  # type: ignore[union-attr]
    # Strict ordering preserved end-to-end.
    timestamps = [m.posted_at for m in out]
    assert timestamps == sorted(timestamps)  # type: ignore[type-var]


# ---------------------------------------------------------------------------
# Integration: extract_messages with relative timestamps
# ---------------------------------------------------------------------------


def test_extract_today_timestamp() -> None:
    """Messages with 'Today at H:MM AM/PM' get correct posted_at date."""
    # received Apr 25 15:00 UTC = Apr 25 23:00 Beijing → Beijing "today" = Apr 25
    received = datetime(2026, 4, 25, 15, 0, 0, tzinfo=UTC)
    html = _whop_page(_single_message("post_today", "author", "Today at 10:30 AM", "hello today"))
    msgs = extract_messages(html, source="stock", received_at=received)
    assert len(msgs) == 1
    # Beijing 10:30 AM Apr 25 → UTC 02:30 Apr 25
    assert msgs[0].posted_at == datetime(2026, 4, 25, 2, 30, 0, tzinfo=UTC)


def test_extract_yesterday_timestamp() -> None:
    """Messages with 'Yesterday at H:MM PM' go back one day."""
    # received Apr 25 15:00 UTC = Apr 25 23:00 Beijing → Beijing "yesterday" = Apr 24
    received = datetime(2026, 4, 25, 15, 0, 0, tzinfo=UTC)
    html = _whop_page(
        _single_message("post_yest", "author", "Yesterday at 11:24 PM", "hello yesterday")
    )
    msgs = extract_messages(html, source="stock", received_at=received)
    assert len(msgs) == 1
    # Beijing 11:24 PM Apr 24 → UTC 15:24 Apr 24
    assert msgs[0].posted_at == datetime(2026, 4, 24, 15, 24, 0, tzinfo=UTC)


def test_extract_weekday_timestamp() -> None:
    """Messages with 'Thursday at H:MM AM' resolve to most recent Thursday."""
    # received Apr 25 15:00 UTC = Apr 25 23:00 Beijing (Saturday) — Thursday = Apr 23
    received = datetime(2026, 4, 25, 15, 0, 0, tzinfo=UTC)
    html = _whop_page(
        _single_message("post_thu", "author", "Thursday at 11:35 AM", "hello thursday")
    )
    msgs = extract_messages(html, source="stock", received_at=received)
    assert len(msgs) == 1
    # Beijing 11:35 AM Apr 23 → UTC 03:35 Apr 23
    assert msgs[0].posted_at == datetime(2026, 4, 23, 3, 35, 0, tzinfo=UTC)


def test_extract_same_minute_subminute_seconds() -> None:
    """Multiple messages in same minute get sequential seconds."""
    received = datetime(2026, 4, 25, 15, 0, 0, tzinfo=UTC)
    inner = (
        _single_message(
            "post_1", "author", "Today at 10:30 AM", "msg one", has_above="false", has_below="true"
        )
        + "\n"
        + _continuation_message("post_2", "msg two", has_above="true", has_below="true")
        + "\n"
        + _continuation_message("post_3", "msg three", has_above="true", has_below="false")
    )
    html = _whop_page(inner)
    msgs = extract_messages(html, source="stock", received_at=received)
    assert len(msgs) == 3
    seconds = [m.posted_at.second for m in msgs]  # type: ignore[union-attr]
    assert seconds == [0, 1, 2]
