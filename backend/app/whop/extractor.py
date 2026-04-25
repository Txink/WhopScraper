"""
extractor.py — DOM → Message pure function, offline-testable with saved HTML.

Parses Whop chat page HTML (produced by browser.py) into a list of domain
Message objects.  No Playwright dependency; uses BeautifulSoup + lxml.

DOM structure (from docs/dom_structure_guide.md):
  <div class="group/message"
       data-message-id="post_xxx"
       data-has-message-above="false"
       data-has-message-below="true">
    <!-- author (first msg in group only) -->
    <span role="button" class="truncate … fui-HoverCardTrigger">xiaozhaolucky</span>
    <!-- timestamp (first msg in group only) -->
    <span class="… inline-flex items-center gap-1">
      <span>•</span><span>Jan 23, 2026 12:46 AM</span>
    </span>
    <!-- optional quote/reply -->
    <div class="peer/reply …">
      <span class="fui-Text truncate …">quoted text…</span>
    </div>
    <!-- message bubble -->
    <div class="bg-gray-3 rounded-[18px] …">
      <div class="… whitespace-pre-wrap"><p>message text</p></div>
    </div>
  </div>
"""
from __future__ import annotations

import re
from dataclasses import replace
from datetime import UTC, date, datetime, time, timedelta
from typing import Literal

from bs4 import BeautifulSoup, Tag

from app.domain.message import Message

# ---------------------------------------------------------------------------
# Timestamp patterns (mirrors JS regexes in message_extractor.py)
# ---------------------------------------------------------------------------
_TS_ABSOLUTE = re.compile(
    r"[A-Z][a-z]{2}\s+\d{1,2},\s+\d{4}\s+\d{1,2}:\d{2}\s+[AP]M"
)
_TS_RELATIVE = re.compile(
    r"^(Yesterday at|Today|Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)"
    r"\s+(\d{1,2}:\d{2}\s+[AP]M|at\s+\d{1,2}:\d{2}\s+[AP]M)$",
    re.IGNORECASE,
)
_TS_TIME_ONLY = re.compile(r"^\d{1,2}:\d{2}\s+[AP]M$", re.IGNORECASE)

# ---------------------------------------------------------------------------
# Filter patterns (mirrors MessageFilter in message_filter.py)
# ---------------------------------------------------------------------------
_FILTER_FIXED = {"•", "Tail", "X", "Edited", "Reply", "Delete", "已编辑", "回复", "删除"}
_FILTER_PATTERNS = [
    re.compile(r"^(由\s*)?\d+\s*阅读$"),           # read count "由 268阅读"
    re.compile(r"^(已编辑|Edited)$"),              # edit marker
    re.compile(r"^(回复|Reply|删除|Delete)$"),      # action markers
    re.compile(r"^•.*\d{1,2}:\d{2}\s+[AP]M$"),   # timestamp line "•Wednesday 11:04 PM"
    re.compile(r"^[•·]\s*[A-Z]"),                  # bullet + capital (metadata)
    re.compile(r"^[A-Z][a-z]{2}\s+\d{1,2},\s+\d{4}"),  # date "Jan 22, 2026"
    re.compile(r"^\d{1,2}:\d{2}\s+[AP]M$", re.IGNORECASE),  # bare time "10:49 PM"
]
_WEEKDAYS = {
    "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday",
}


def _should_filter(text: str) -> bool:
    """Return True if the text is metadata/noise (not a real message)."""
    t = text.strip()
    if not t or len(t) < 2:
        return True
    if t in _FILTER_FIXED:
        return True
    for pat in _FILTER_PATTERNS:
        if pat.search(t):
            return True
    # Weekday + AM/PM + short → pure timestamp row
    has_weekday = any(day in t for day in _WEEKDAYS)
    has_ampm = "PM" in t or "AM" in t
    return has_weekday and has_ampm and len(t.split()) <= 4 and len(t) < 30


def _clean_text(text: str) -> str:
    """Strip 'Tail' suffix and collapse whitespace."""
    text = re.sub(r"Tail$", "", text).strip()
    text = re.sub(r"\s+", " ", text)
    return text


# ---------------------------------------------------------------------------
# Timestamp parsing
# ---------------------------------------------------------------------------
_MONTH_MAP = {
    "Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6,
    "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12,
}

_WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
_MONTHS = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]

# Whop timestamp patterns (all case-insensitive)
_TIME_RE = r"(\d{1,2}):(\d{2})\s*(AM|PM|am|pm)"
_TODAY_RE = re.compile(rf"^Today(?:\s+at)?\s+{_TIME_RE}$", re.IGNORECASE)
_YESTERDAY_RE = re.compile(rf"^Yesterday(?:\s+at)?\s+{_TIME_RE}$", re.IGNORECASE)
_WEEKDAY_RE = re.compile(rf"^(\w+)(?:\s+at)?\s+{_TIME_RE}$", re.IGNORECASE)
_FULL_DATE_RE = re.compile(rf"^(\w{{3}})\s+(\d{{1,2}})(?:,\s*(\d{{4}}))?\s+{_TIME_RE}$", re.IGNORECASE)


def parse_whop_timestamp(text: str, *, now: datetime | None = None) -> datetime | None:
    """Parse a Whop timestamp string into an aware UTC datetime.

    Handles all 6 formats shown in Whop chat:
      - "Today at 2:30 PM"         → today at that time
      - "Yesterday at 11:24 PM"    → yesterday at that time
      - "Thursday at 11:35 AM"     → most recent Thursday strictly before today
      - "Thursday 11:35 AM"        → same (variant without "at")
      - "Apr 13, 2026 5:43 PM"     → explicit date with year
      - "Apr 13 5:43 PM"           → explicit date (current year)

    Returns datetime with second=0, microsecond=0.
    Returns None if no pattern matches.

    ``now`` defaults to ``datetime.now(UTC)``; pass it for deterministic tests.
    """
    if not text:
        return None
    text = text.strip()
    if now is None:
        now = datetime.now(UTC)
    today = now.date()

    def _build(d: date, h: int, m: int, ampm: str) -> datetime:
        h24 = (h % 12) + (12 if ampm.upper() == "PM" else 0)
        return datetime.combine(d, time(h24, m), tzinfo=UTC)

    # Today at H:MM AM/PM
    if (m := _TODAY_RE.match(text)):
        return _build(today, int(m.group(1)), int(m.group(2)), m.group(3))

    # Yesterday at H:MM AM/PM
    if (m := _YESTERDAY_RE.match(text)):
        return _build(today - timedelta(days=1), int(m.group(1)), int(m.group(2)), m.group(3))

    # <Mon> D[, YYYY] H:MM AM/PM  — try full date before weekday to avoid false match
    if (m := _FULL_DATE_RE.match(text)):
        mon = m.group(1).lower()[:3]
        if mon in _MONTHS:
            month_num = _MONTHS.index(mon) + 1
            day = int(m.group(2))
            year = int(m.group(3)) if m.group(3) else today.year
            try:
                d = date(year, month_num, day)
                return _build(d, int(m.group(4)), int(m.group(5)), m.group(6))
            except ValueError:
                pass

    # <Weekday>[at] H:MM AM/PM  — most recent occurrence strictly before today
    if (m := _WEEKDAY_RE.match(text)):
        wd_name = m.group(1).lower()
        if wd_name in _WEEKDAYS:
            target_wd = _WEEKDAYS.index(wd_name)
            today_wd = today.weekday()
            # days_back must be at least 1 (strictly before today).
            # If today is Thursday and text says "Thursday", that's last Thursday (7 days back).
            days_back = (today_wd - target_wd) % 7
            if days_back == 0:
                days_back = 7
            d = today - timedelta(days=days_back)
            return _build(d, int(m.group(2)), int(m.group(3)), m.group(4))

    return None


def _assign_subminute_seconds(messages_in_dom_order: list[Message]) -> list[Message]:
    """For each consecutive run of messages with the same (date, hour, minute),
    set second=0, 1, 2, ... in DOM order.  Microsecond is always 0.

    Returns a NEW list of Message objects (Message is frozen/dataclass).
    Messages with posted_at=None are passed through unchanged.
    """
    out: list[Message] = []
    last_minute_key: datetime | None = None
    seq = 0
    for msg in messages_in_dom_order:
        if msg.posted_at is None:
            out.append(msg)
            continue
        minute_key = msg.posted_at.replace(second=0, microsecond=0)
        if minute_key == last_minute_key:
            seq += 1
        else:
            seq = 0
            last_minute_key = minute_key
        new_posted_at = msg.posted_at.replace(second=seq, microsecond=0)
        out.append(replace(msg, posted_at=new_posted_at))
    return out


def _parse_timestamp(raw: str, received_at: datetime) -> datetime:
    """Convert a Whop timestamp string to a UTC-aware datetime (legacy wrapper).

    Delegates to parse_whop_timestamp; falls back to received_at on failure.
    """
    parsed = parse_whop_timestamp(raw, now=received_at)
    return parsed if parsed is not None else received_at


def _parse_time_part(raw: str) -> tuple[int, int]:
    """Return (hour24, minute) from "10:45 PM"."""
    m = re.match(r"(\d{1,2}):(\d{2})\s+([AP]M)", raw.strip(), re.IGNORECASE)
    if not m:
        return (0, 0)
    hour = int(m.group(1))
    minute = int(m.group(2))
    ampm = m.group(3).upper()
    if ampm == "PM" and hour != 12:
        hour += 12
    elif ampm == "AM" and hour == 12:
        hour = 0
    return (hour, minute)


# ---------------------------------------------------------------------------
# Element helpers (BeautifulSoup)
# ---------------------------------------------------------------------------

def _get_classes(tag: Tag) -> list[str]:
    cls = tag.get("class")
    if cls is None:
        return []
    if isinstance(cls, list):
        return [str(c) for c in cls]
    return str(cls).split()


def _has_class_fragment(tag: Tag, fragment: str) -> bool:
    return any(fragment in c for c in _get_classes(tag))


def _is_in_quote(tag: Tag) -> bool:
    """Return True if *tag* is inside a peer/reply quote block."""
    for parent in tag.parents:
        if not isinstance(parent, Tag):
            continue
        if "peer/reply" in " ".join(_get_classes(parent)):
            return True
        # Stop at the message root
        if parent.get("data-message-id"):
            break
    return False


def _extract_author(msg_el: Tag) -> str | None:
    """Extract author username from message element."""
    # Most precise: span[role="button"] with truncate + fui-HoverCardTrigger
    for span in msg_el.find_all("span", attrs={"role": "button"}):
        classes = _get_classes(span)
        if "truncate" in classes and any("fui-HoverCardTrigger" in c for c in classes):
            text = span.get_text(strip=True)
            # Validate: not a timestamp marker, not too long, no digits
            if (
                text
                and len(text) <= 50
                and text not in _FILTER_FIXED
                and "PM" not in text
                and "AM" not in text
                and not re.search(r"\d", text)
                and "•" not in text
                and "$" not in text
            ):
                return text
    return None


def _extract_timestamp_raw(msg_el: Tag) -> str:
    """Extract raw timestamp string from message element."""
    # Look for .inline-flex.items-center.gap-1 containers
    for container in msg_el.find_all(
        lambda t: isinstance(t, Tag)
        and "inline-flex" in _get_classes(t)
        and "items-center" in _get_classes(t)
        and "gap-1" in _get_classes(t)
    ):
        for span in container.find_all("span"):
            text = span.get_text(strip=True)
            if _TS_ABSOLUTE.search(text):
                return _TS_ABSOLUTE.search(text).group(0)  # type: ignore[union-attr]
            if _TS_RELATIVE.match(text):
                return text
            if _TS_TIME_ONLY.match(text):
                return text

    # Fallback: scan all text in element
    full_text = msg_el.get_text(" ")
    for pat in (_TS_ABSOLUTE, _TS_RELATIVE, _TS_TIME_ONLY):
        m = pat.search(full_text)
        if m:
            return m.group(0)
    return ""


def _extract_quote_content(msg_el: Tag) -> str:
    """Extract quoted message text from peer/reply block."""
    # Find peer/reply container
    quote_el: Tag | None = None
    for div in msg_el.find_all(True):
        if not isinstance(div, Tag):
            continue
        cls_str = " ".join(_get_classes(div))
        if "peer/reply" in cls_str:
            quote_el = div
            break

    if quote_el is None:
        return ""

    # Find fui-Text truncate spans (not the author span with fui-r-weight-medium)
    candidate_spans = [
        s for s in quote_el.find_all(True)
        if isinstance(s, Tag)
        and _has_class_fragment(s, "fui-Text")
        and _has_class_fragment(s, "truncate")
    ]

    # Prefer spans WITHOUT fui-r-weight-medium (author name)
    content_spans = [
        s for s in candidate_spans
        if not _has_class_fragment(s, "fui-r-weight-medium")
    ]
    if content_spans:
        raw = content_spans[0].get_text(strip=True)
    elif candidate_spans:
        raw = candidate_spans[-1].get_text(strip=True)
    else:
        raw = quote_el.get_text(strip=True)

    # Clean artefacts
    raw = _clean_text(raw)
    # Remove avatar fallback "X" only when it is a standalone leading char
    raw = re.sub(r"^X\s*(?=[^A-Za-z]|$)", "", raw)
    # Remove known author name prefix
    raw = re.sub(r"^xiaozhaolucky\s*", "", raw, flags=re.IGNORECASE)

    if 5 < len(raw) < 500:
        return raw
    return ""


def _extract_content(msg_el: Tag, author: str | None, ts_raw: str) -> tuple[str, str]:
    """Return (content, raw_content) from message bubble(s).

    raw_content preserves emojis and whitespace exactly.
    content collapses whitespace and strips the 'Tail' artefact.
    """
    texts: list[str] = []

    # Strategy 1: look for bg-gray-3 + rounded bubbles
    bubbles = [
        el for el in msg_el.find_all(True)
        if isinstance(el, Tag)
        and "bg-gray-3" in _get_classes(el)
        and _has_class_fragment(el, "rounded")
    ]

    # Strategy 2: whitespace-pre-wrap containers
    if not bubbles:
        bubbles = [
            el for el in msg_el.find_all(True)
            if isinstance(el, Tag)
            and _has_class_fragment(el, "whitespace-pre-wrap")
        ]

    for el in bubbles:
        # Skip anything inside a quote block
        if _is_in_quote(el):
            continue
        # Skip hidden elements (class "hidden")
        if "hidden" in _get_classes(el):
            continue
        # Skip avatar elements
        if any(
            _has_class_fragment(el, frag)
            for frag in ("fui-Avatar", "avatar")
        ):
            continue
        # Skip read-count spans (text-gray-11 text-0)
        if "text-gray-11" in _get_classes(el) and "text-0" in _get_classes(el):
            continue

        raw_text = el.get_text(" ", strip=False)
        cleaned = _clean_text(raw_text)

        if not cleaned:
            continue
        if _should_filter(cleaned):
            continue
        if author and cleaned == author:
            continue
        if ts_raw and cleaned == ts_raw:
            continue

        texts.append(cleaned)

    # Deduplicate while preserving order
    seen: set[str] = set()
    unique: list[str] = []
    for t in texts:
        if t not in seen:
            seen.add(t)
            unique.append(t)

    if not unique:
        return ("", "")

    # Join multiple bubbles with newline
    raw_content = "\n".join(unique)
    content = re.sub(r"\s+", " ", raw_content).strip()
    return (content, raw_content)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def extract_messages(
    html: str,
    *,
    source: Literal["stock", "option"],
    received_at: datetime | None = None,
) -> list[Message]:
    """Parse Whop-page HTML into Message objects.

    Returns messages in page order (oldest first — top of DOM).
    ``received_at`` defaults to ``datetime.now(UTC)`` if not provided.
    """
    if received_at is None:
        received_at = datetime.now(UTC)

    soup = BeautifulSoup(html, "lxml")

    # Find all message elements — prefer precise selector
    msg_elements: list[Tag] = []
    for el in soup.find_all(True, attrs={"data-message-id": True}):
        if isinstance(el, Tag):
            msg_elements.append(el)

    if not msg_elements:
        return []

    messages: list[Message] = []

    # Track current group header for author/timestamp inheritance
    current_author: str | None = None
    current_ts_raw: str = ""
    current_posted_at: datetime = received_at

    for msg_el in msg_elements:
        try:
            msg_id: str = str(msg_el.get("data-message-id") or "")
            if not msg_id:
                # Generate a stable fallback from element position
                msg_id = f"unknown-{len(messages)}"

            has_above = msg_el.get("data-has-message-above", "false") == "true"

            # ---- Author / timestamp (only on group-start messages) ----
            if not has_above:
                # New message group — extract fresh author + timestamp
                author = _extract_author(msg_el)
                ts_raw = _extract_timestamp_raw(msg_el)
                current_author = author or None
                if ts_raw:
                    current_ts_raw = ts_raw
                    current_posted_at = _parse_timestamp(ts_raw, received_at)
            else:
                # Continuation — inherit from group start
                author = current_author
                ts_raw = current_ts_raw

            # ---- Quote ----
            quote_text = _extract_quote_content(msg_el)
            quoted: Message | None = None
            if quote_text:
                # Build a stub Message for the quoted content; ID uses parent + "-quoted"
                quoted = Message(
                    id=f"{msg_id}-quoted",
                    content=quote_text,
                    raw_content=quote_text,
                    author=None,
                    posted_at=current_posted_at,
                    received_at=received_at,
                    source=source,
                    quoted=None,
                    history_hint=[],
                )

            # ---- Content ----
            content, raw_content = _extract_content(msg_el, author, ts_raw)

            # ---- Skip empty / metadata-only messages ----
            if not content:
                continue

            # Also skip messages whose content is pure metadata
            if _should_filter(content):
                continue

            # ---- Check for image-only messages ----
            has_attachment = bool(
                msg_el.find(attrs={"data-attachment-id": True})
                or msg_el.find("img", src=re.compile(r"whop\.com"))
            )
            if has_attachment and (not content or re.match(r"^(由\s*)?\d+\s*阅读$", content)):
                continue  # pure image with only read-count text

            message = Message(
                id=msg_id,
                content=content,
                raw_content=raw_content,
                author=author,
                posted_at=current_posted_at,
                received_at=received_at,
                source=source,
                quoted=quoted,
                history_hint=[],
            )
            messages.append(message)

        except Exception:
            # Never let a single malformed element crash the whole extraction
            continue

    return _assign_subminute_seconds(messages)
