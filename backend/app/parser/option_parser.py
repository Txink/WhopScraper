"""
期权指令解析器 — 单条消息文本 → OptionInstruction。

不做 ticker 上下文补全（Task 19）；不做关注列表校验（调用方职责）。
纯函数，无副作用。

expiry 永远是 Python date 对象（而非字符串）。
symbol 使用 LongPort 格式，如 NVDA260425C135000.US。
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta

from app.domain.instruction import InstructionType, OptionInstruction

# ---------------------------------------------------------------------------
# Non-ticker words (ported from old option_parser.py)
# ---------------------------------------------------------------------------

_NON_TICKER_WORDS = frozenset(
    {
        "CALL",
        "PUT",
        "CALLS",
        "PUTS",
        "THE",
        "AND",
        "FOR",
        "ALL",
        "OUT",
        "NEW",
        "ONE",
        "SEE",
        "BUY",
        "SELL",
        "ETF",
        "ITM",
        "OTM",
        "ATM",
    }
)

# ---------------------------------------------------------------------------
# Expiry helpers
# ---------------------------------------------------------------------------


def _get_friday_of_week(dt: datetime) -> datetime:
    """Return Friday of the same ISO week as *dt*.

    If *dt* is already Friday (weekday == 4), return *dt* itself.
    Ported verbatim from old OptionParser._get_friday_of_week.
    """
    days_until_friday = (4 - dt.weekday()) % 7
    if days_until_friday == 0:
        return dt
    return dt + timedelta(days=days_until_friday)


def _resolve_expiry(text: str, posted_at: datetime) -> date | None:
    """Convert an expiry token to a concrete Python ``date``.

    Supported inputs
    ----------------
    - 相对日期: 本周 / 这周 / 当周 / 下周 / 今天 / 明天 /
               this week / next week / weekly / today / tomorrow / 0DTE
    - 具体日期: 5/3 / 12/15 / 1月9日 / Jan 15

    Returns ``None`` if the token cannot be parsed.
    """
    if not text or not str(text).strip():
        return None

    text_upper = text.strip().upper()

    # ---- relative date keywords ----
    this_week_kws = {"本周", "这周", "当周", "THIS WEEK", "WEEKLY"}
    next_week_kws = {"下周", "NEXT WEEK"}
    today_kws = {"今天", "TODAY", "0DTE"}
    tomorrow_kws = {"明天", "TOMORROW"}

    for kw in this_week_kws:
        if kw in text_upper:
            target = _get_friday_of_week(posted_at)
            return target.date() if isinstance(target, datetime) else target

    for kw in next_week_kws:
        if kw in text_upper:
            target = _get_friday_of_week(posted_at + timedelta(days=7))
            return target.date() if isinstance(target, datetime) else target

    for kw in today_kws:
        if kw in text_upper:
            return posted_at.date()

    for kw in tomorrow_kws:
        if kw in text_upper:
            return (posted_at + timedelta(days=1)).date()

    # ---- explicit numeric patterns ----
    # M/D or M月D日
    m = re.match(r"(\d{1,2})/(\d{1,2})", text)
    if m:
        month, day = int(m.group(1)), int(m.group(2))
        if 1 <= month <= 12 and 1 <= day <= 31:
            return date(posted_at.year, month, day)

    m = re.match(r"(\d{1,2})月(\d{1,2})日?", text)
    if m:
        month, day = int(m.group(1)), int(m.group(2))
        if 1 <= month <= 12 and 1 <= day <= 31:
            return date(posted_at.year, month, day)

    # English month abbreviation: Jan 15 / MAY 3
    _MONTHS = {
        "JAN": 1,
        "FEB": 2,
        "MAR": 3,
        "APR": 4,
        "MAY": 5,
        "JUN": 6,
        "JUL": 7,
        "AUG": 8,
        "SEP": 9,
        "OCT": 10,
        "NOV": 11,
        "DEC": 12,
    }
    m = re.match(r"([A-Za-z]{3})\s*(\d{1,2})", text)
    if m:
        mon = _MONTHS.get(m.group(1).upper())
        if mon:
            return date(posted_at.year, mon, int(m.group(2)))

    return None


# ---------------------------------------------------------------------------
# LongPort symbol helper
# ---------------------------------------------------------------------------


def _make_longport_symbol(
    ticker: str,
    expiry: date,
    option_type: str,
    strike: float,
) -> str:
    """Generate LongPort option symbol.

    Format: {TICKER}{YYMMDD}{C|P}{int(strike*1000)}.US
    Example: NVDA260425C135000.US
    """
    date_str = expiry.strftime("%y%m%d")  # YYMMDD
    option_code = "C" if option_type.upper() == "CALL" else "P"
    strike_code = str(int(round(strike * 1000)))
    return f"{ticker}{date_str}{option_code}{strike_code}.US"


# ---------------------------------------------------------------------------
# Price parsing helper
# ---------------------------------------------------------------------------


def _parse_price_range(
    price_str: str,
) -> tuple[float | None, tuple[float, float] | None]:
    """Parse a price token into (price, price_range).

    Supports:
    - Single value: "2.15" → (2.15, None)
    - Range: "1.5-1.6" → (None, (1.5, 1.6))
    - Full-width decimal: "2。15" → treated like "2.15"
    - Comma decimal (1,5): treated like "1.5"
    """
    if not price_str or not str(price_str).strip():
        return (None, None)

    s = str(price_str).strip()
    s = s.replace("。", ".").replace("．", ".")
    s = re.sub(r"(\d),(\d{1,3})\b", r"\1.\2", s)

    if "-" in s:
        try:
            lo_str, hi_str = s.split("-", 1)
            lo, hi = float(lo_str.strip()), float(hi_str.strip())
            return (None, (min(lo, hi), max(lo, hi)))
        except ValueError:
            try:
                return (float(lo_str.strip()), None)
            except ValueError:
                return (None, None)

    try:
        return (float(s), None)
    except ValueError:
        return (None, None)


# ---------------------------------------------------------------------------
# Ticker extraction helper
# ---------------------------------------------------------------------------


def _extract_ticker(message: str) -> str | None:
    """Extract first plausible ticker (2-5 letters) from message text."""
    words: list[str] = re.findall(r"(?:^|[^A-Za-z])([A-Za-z]{2,5})(?=[^A-Za-z]|$)", message)
    for w in words:
        u = w.upper()
        if u not in _NON_TICKER_WORDS:
            return u
    return None


# ---------------------------------------------------------------------------
# Open (BUY) patterns  — ported from old OptionParser
# ---------------------------------------------------------------------------

# Pattern 1: TICKER STRIKE CALL/PUT [EXPIRY] PRICE
# e.g. "NVDA 135 CALL 本周 2.15"
_OPEN_PAT_1 = re.compile(
    r"([A-Z]{2,5})\s*[-–]?\s*\$?(\d+(?:\.\d+)?)\s*"
    r"(?:(?:ITM|OTM|ATM)\s+)?"
    r"(CALLS?|PUTS?)\s*"
    r"(?:"
    r"(本周|下周|这周|当周|今天|0DTE)(?:的)?\s*"
    r"|(?:EXPIRATION\s+)?(\d{1,2}/\d{1,2}|\d{1,2}月\d{1,2}日?)\s*"
    r"|(?:EXPIRATION\s+)?(NEXT\s+WEEK|THIS\s+WEEK)(?:到期)?\s*"
    r")?"
    r"\$?((?:\d+(?:\.\d+)?|\.\d+)(?:-(?:\d+(?:\.\d+)?|\.\d+))?)",
    re.IGNORECASE,
)

# Pattern 2: TICKER STRIKEc/p [EXPIRY] PRICE  (shorthand like "INTC 48C")
_OPEN_PAT_2 = re.compile(
    r"([A-Z]{2,5})\s+(?:\d{1,2}/\d{1,2}\s+)?"
    r"(\d+(?:\.\d+)?)[cCpP]\s+"
    r"(?:(\d{1,2}/\d{1,2}|1月\d{1,2}|2月\d{1,2}|本周|下周|这周)\s+)?"
    r"(?:入场价?[：:])?\s*"
    r"(?:彩票)?\s*"
    r".*?"
    r"(\d+(?:\.\d+)?|\.\d+)"
    r"(?![\/])",
    re.IGNORECASE,
)

# Pattern 3: TICKER EXPIRY STRIKE call/put PRICE  (expiry first)
_OPEN_PAT_3 = re.compile(
    r"([A-Z]{2,5})\s+"
    r"(\d{1,2}月\d{1,2}日?|本周|下周|这周)\s*"
    r"(\d+(?:\.\d+)?)(?:的)?\s*"
    r"(call|put)s?\s+"
    r"(\d+(?:\.\d+)?|\.\d+)",
    re.IGNORECASE,
)

# Pattern 4: TICKER STRIKEcall/put PRICE  (compact, no expiry)
_OPEN_PAT_4 = re.compile(
    r"([A-Z]{2,5})\s+"
    r"(\d+(?:\.\d+)?)(call|put)s?\s*"
    r"(?:可以)?(?:在)?"
    r"(\d+(?:\.\d+)?|\.\d+)",
    re.IGNORECASE,
)

# Pattern 7: TICKER DATE STRIKE c/p PRICE  (date in middle, most explicit)
_OPEN_PAT_7 = re.compile(
    r"([A-Z]{2,5})\s+"
    r"(\d{1,2}/\d{1,2}|\d{1,2}月\d{1,2}日?)\s+"
    r"(\d+(?:\.\d+)?)\s*"
    r"[cCpP](?:all|ut)?s?\s*"
    r"(?:入场价?[：:])?\s*"
    r"(?:备注[：:]?)?\s*"
    r"((?:\d+(?:\.\d+)?|\.\d+)(?:-(?:\d+(?:\.\d+)?|\.\d+))?)",
    re.IGNORECASE,
)

# Pattern 8: $TICKER [RELDATE] [CONCRDATE] STRIKE 看涨/看跌/CALL/PUT PRICE
_OPEN_PAT_8 = re.compile(
    r"\$?([A-Z]{2,5})\s*[-–]?\s*"
    r"(?:(下周|本周|这周)(?:到期)?)??\s*"
    r"(?:(\d{1,2}月\d{1,2}日?)\s+)?"
    r"\$?(\d+(?:\.\d+)?)\s*"
    r"(看涨期权|看跌期权|CALLS?|PUTS?)\s*"
    r"(?:入场[：:]?)?\s*"
    r"\$?((?:\d+(?:\.\d+)?|\.\d+)(?:-(?:\d+(?:\.\d+)?|\.\d+))?)",
    re.IGNORECASE,
)

# Pattern 9: $TICKER STRIKE RELDATE [call/put] PRICE
_OPEN_PAT_9 = re.compile(
    r"\$?([A-Z]{2,5})\s*[-–]?\s*"
    r"\$?(\d+(?:\.\d+)?)\s+"
    r"(本周|下周|这周|当周|今天|this\s+week|next\s+week)(?:的)?\s*"
    r"(?:(call|put)s?[\s\S]{0,30}?)?"
    r"\$?((?:\d+(?:\.\d+)?|\.\d+)(?:-(?:\d+(?:\.\d+)?|\.\d+))?)",
    re.IGNORECASE,
)

# Pattern 10: TICKER call/put STRIKE PRICE  (no expiry → this week)
_OPEN_PAT_10 = re.compile(
    r"\$?([A-Z]{2,5})\s+"
    r"(call|put)s?\s+"
    r"\$?(\d+(?:\.\d+)?)\s+"
    r"\$?((?:\d+(?:\.\d+)?|\.\d+)(?:-(?:\d+(?:\.\d+)?|\.\d+))?)",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Modify / stop-loss / take-profit patterns
# ---------------------------------------------------------------------------

_STOP_LOSS_PAT = re.compile(
    r"(?:止损|SL|stop\s*loss)(?:价|点位|价位)?\s*(?:设置)?\s*(?:到|至|在)?\s*(\d+(?:[.。．]\d+)?)",
    re.IGNORECASE,
)
_REVERSE_STOP_PAT = re.compile(
    r"(\d+(?:[.。．]\d+)?)\s*(?:附近)?\s*(?:止损|SL)",
    re.IGNORECASE,
)
_ADJUST_STOP_PAT = re.compile(
    r"(?:止损|SL|stop\s*loss)\s*(?:点位|价|设置)?\s*(?:提高|调整|移动|上调|上移)(?:到|至)?\s*(\d+(?:[.。．]\d+)?)",
    re.IGNORECASE,
)

_TAKE_PROFIT_PAT = re.compile(
    r"(?:止盈|TP|take\s*profit)\s*(?:价|点位|价位)?\s*(?:设置)?\s*(?:到|至|在)?\s*(\d+(?:[.。．]\d+)?)",
    re.IGNORECASE,
)

_POSITION_SIZE_PAT = re.compile(
    r"(小仓位|中仓位|大仓位|轻仓|重仓|半仓|满仓)",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Internal build helpers
# ---------------------------------------------------------------------------


def _build_buy(
    *,
    ticker: str,
    option_type: str,
    strike: float,
    expiry_raw: str | None,
    price_str: str,
    message: str,
    message_id: str,
    posted_at: datetime,
) -> OptionInstruction | None:
    """Common factory: resolve expiry + build OptionInstruction for BUY."""
    expiry: date | None = _resolve_expiry(expiry_raw, posted_at) if expiry_raw else None
    if expiry is None:
        return None

    price, price_range = _parse_price_range(price_str)
    if price is None and price_range is None:
        return None

    pos_m = _POSITION_SIZE_PAT.search(message)
    position_size = pos_m.group(1) if pos_m else None

    symbol = _make_longport_symbol(ticker, expiry, option_type, strike)

    notes: list[str] = []
    if expiry_raw and any(
        kw in expiry_raw.upper()
        for kw in ("本周", "这周", "当周", "下周", "THIS WEEK", "NEXT WEEK", "WEEKLY")
    ):
        notes.append(f"{expiry_raw} → {expiry.isoformat()}")

    return OptionInstruction(
        instruction_type=InstructionType.BUY,
        price=price,
        price_range=price_range,
        quantity=None,
        position_size=position_size,
        stop_loss_price=None,
        take_profit_price=None,
        context_source=None,
        parser_notes=notes,
        ticker=ticker,
        option_type=option_type,  # type: ignore[arg-type]
        strike=strike,
        expiry=expiry,
        symbol=symbol,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def parse(
    content: str,
    *,
    message_id: str,
    message_posted_at: datetime,
) -> OptionInstruction | None:
    """Parse a single option-channel message into OptionInstruction.

    ``message_posted_at`` is used to resolve relative expiry like "本周" / "下周".
    Returns None if the message doesn't match any known option pattern.
    Does NOT resolve quoted/history context (see context_resolver, Task 19).
    """
    content = content.strip()
    if not content:
        return None

    # Try to parse a stop-loss / modify first (before buy patterns interfere)
    result = _try_modify(content, message_id=message_id)
    if result is not None:
        return result

    # Try all BUY patterns in priority order
    result = _try_buy(content, message_id=message_id, posted_at=message_posted_at)
    if result is not None:
        return result

    return None


# ---------------------------------------------------------------------------
# BUY parsing — try patterns in priority order
# ---------------------------------------------------------------------------


def _try_buy(message: str, *, message_id: str, posted_at: datetime) -> OptionInstruction | None:
    """Try all BUY open patterns in priority order."""

    # --- Pattern 7: TICKER DATE STRIKE[c/p] PRICE (most explicit) ---
    m = _OPEN_PAT_7.search(message)
    if m:
        ticker = m.group(1).upper()
        expiry_raw = m.group(2)
        strike = float(m.group(3))
        price_str = m.group(4)

        # Determine option type from the character after the strike digits
        ot_m = re.search(r"(\d+(?:\.\d+)?|\.\d+)([cCpP])(?:all|ut)?s?", message)
        option_type = "CALL"
        if ot_m:
            option_type = "CALL" if ot_m.group(2).upper() == "C" else "PUT"

        return _build_buy(
            ticker=ticker,
            option_type=option_type,
            strike=strike,
            expiry_raw=expiry_raw,
            price_str=price_str,
            message=message,
            message_id=message_id,
            posted_at=posted_at,
        )

    # --- Pattern 1: TICKER STRIKE CALL/PUT [EXPIRY] PRICE ---
    m = _OPEN_PAT_1.search(message)
    if m:
        ticker = m.group(1).upper()
        strike = float(m.group(2))
        ot_str = m.group(3).upper()
        option_type = "CALL" if ot_str.startswith("CALL") else "PUT"
        expiry_raw = m.group(4) or m.group(5) or m.group(6)
        price_str = m.group(7)

        if expiry_raw is None:
            # No expiry in message; cannot resolve — return None
            return None

        return _build_buy(
            ticker=ticker,
            option_type=option_type,
            strike=strike,
            expiry_raw=expiry_raw,
            price_str=price_str,
            message=message,
            message_id=message_id,
            posted_at=posted_at,
        )

    # --- Pattern 2: TICKER STRIKEc/p [EXPIRY] PRICE ---
    m = _OPEN_PAT_2.search(message)
    if m:
        ticker = m.group(1).upper()
        strike = float(m.group(2))
        # Determine c/p from the character immediately after the strike digits
        indicator = message[m.start() : m.end()]
        option_type = "CALL" if re.search(r"\d[cC]", indicator) else "PUT"
        expiry_raw = m.group(3) if m.group(3) else None
        price_str = m.group(4)

        if expiry_raw is None:
            # Pattern 2 without expiry — try anyway with None expiry → returns None
            return None

        return _build_buy(
            ticker=ticker,
            option_type=option_type,
            strike=strike,
            expiry_raw=expiry_raw,
            price_str=price_str,
            message=message,
            message_id=message_id,
            posted_at=posted_at,
        )

    # --- Pattern 3: TICKER EXPIRY STRIKE call/put PRICE ---
    m = _OPEN_PAT_3.search(message)
    if m:
        ticker = m.group(1).upper()
        expiry_raw = m.group(2)
        strike = float(m.group(3))
        ot_str = m.group(4).upper()
        option_type = "CALL" if ot_str.startswith("CALL") else "PUT"
        price_str = m.group(5)

        return _build_buy(
            ticker=ticker,
            option_type=option_type,
            strike=strike,
            expiry_raw=expiry_raw,
            price_str=price_str,
            message=message,
            message_id=message_id,
            posted_at=posted_at,
        )

    # --- Pattern 8: $TICKER [RELDATE] [CONCRDATE] STRIKE 看涨/看跌/CALL/PUT PRICE ---
    m = _OPEN_PAT_8.search(message)
    if m:
        ticker = m.group(1).upper()
        relative_date = m.group(2)
        specific_date = m.group(3)
        strike = float(m.group(4))
        ot_str = m.group(5)
        price_str = m.group(6)

        option_type = "CALL" if "看涨" in ot_str or "CALL" in ot_str.upper() else "PUT"

        expiry_raw = relative_date or specific_date
        if expiry_raw is None:
            return None

        return _build_buy(
            ticker=ticker,
            option_type=option_type,
            strike=strike,
            expiry_raw=expiry_raw,
            price_str=price_str,
            message=message,
            message_id=message_id,
            posted_at=posted_at,
        )

    # --- Pattern 9: $TICKER STRIKE RELDATE [call/put] PRICE ---
    m = _OPEN_PAT_9.search(message)
    if m:
        ticker = m.group(1).upper()
        strike = float(m.group(2))
        expiry_raw = m.group(3)
        ot_str = m.group(4)
        price_str = m.group(5)

        option_type = ("CALL" if ot_str.upper().startswith("CALL") else "PUT") if ot_str else "CALL"

        return _build_buy(
            ticker=ticker,
            option_type=option_type,
            strike=strike,
            expiry_raw=expiry_raw,
            price_str=price_str,
            message=message,
            message_id=message_id,
            posted_at=posted_at,
        )

    # --- Pattern 10: TICKER call/put STRIKE PRICE  (no expiry → this week) ---
    m = _OPEN_PAT_10.search(message)
    if m:
        ticker = m.group(1).upper()
        ot_str = m.group(2).upper()
        option_type = "CALL" if ot_str.startswith("CALL") else "PUT"
        strike = float(m.group(3))
        price_str = m.group(4)

        return _build_buy(
            ticker=ticker,
            option_type=option_type,
            strike=strike,
            expiry_raw="本周",
            price_str=price_str,
            message=message,
            message_id=message_id,
            posted_at=posted_at,
        )

    # --- Pattern 4: TICKER STRIKEcall/put PRICE (compact, no expiry) ---
    m = _OPEN_PAT_4.search(message)
    if m:
        ticker = m.group(1).upper()
        strike = float(m.group(2))
        ot_str = m.group(3).upper()
        option_type = "CALL" if ot_str.startswith("CALL") else "PUT"
        price_str = m.group(4)

        return _build_buy(
            ticker=ticker,
            option_type=option_type,
            strike=strike,
            expiry_raw="本周",
            price_str=price_str,
            message=message,
            message_id=message_id,
            posted_at=posted_at,
        )

    return None


# ---------------------------------------------------------------------------
# MODIFY parsing (stop-loss / take-profit adjustments)
# ---------------------------------------------------------------------------


def _try_modify(message: str, *, message_id: str) -> OptionInstruction | None:
    """Parse stop-loss / take-profit modify instructions."""

    # Detect any stop-loss pattern
    adjust_m = _ADJUST_STOP_PAT.search(message)
    stop_m = _STOP_LOSS_PAT.search(message)
    reverse_m = _REVERSE_STOP_PAT.search(message)
    tp_m = _TAKE_PROFIT_PAT.search(message)

    if not (adjust_m or stop_m or reverse_m or tp_m):
        return None

    # Extract stop-loss price
    sl_price: float | None = None
    if adjust_m:
        sl_str = adjust_m.group(1).replace("。", ".").replace("．", ".")
        sl_price = float(sl_str)
    elif stop_m:
        sl_str = stop_m.group(1).replace("。", ".").replace("．", ".")
        sl_price = float(sl_str)
    elif reverse_m:
        sl_str = reverse_m.group(1).replace("。", ".").replace("．", ".")
        sl_price = float(sl_str)

    # Extract take-profit price
    tp_price: float | None = None
    if tp_m:
        tp_str = tp_m.group(1).replace("。", ".").replace("．", ".")
        tp_price = float(tp_str)

    # Extract ticker if present (best-effort)
    ticker: str | None = None
    tk_m = re.search(r"([A-Za-z]{2,5})(?:期权|期货|股票)", message)
    if not tk_m:
        tk_m = re.search(r"(?:剩下)?的\s*([A-Za-z]{2,5})(?:\s|$)", message)
    if not tk_m:
        tk_m = re.search(r"\b([A-Z]{2,5})\b", message)
    if tk_m:
        candidate = tk_m.group(1).upper()
        if candidate not in {"SL", "TP", "STOP", "LOSS", "TAKE", "PROFIT"}:
            ticker = candidate

    # MODIFY requires a ticker-less variant that still has a price; but
    # OptionInstruction requires a non-empty ticker.  For pure-stop-loss
    # messages without a ticker (e.g. "止损 0.9"), we cannot build a valid
    # OptionInstruction.  Return None — caller (context resolver, Task 19)
    # will fill the ticker.
    # However, if a ticker was found alongside stop-loss, build the instruction.
    if ticker is None:
        # Cannot construct valid OptionInstruction without ticker
        return None

    # MODIFY also needs a price or price_range (from parent __post_init__).
    # Use stop_loss_price or take_profit_price as the "price" sentinel if
    # no separate price exists.
    sentinel_price = sl_price if sl_price is not None else tp_price
    if sentinel_price is None:
        return None

    return OptionInstruction(
        instruction_type=InstructionType.MODIFY,
        price=sentinel_price,
        price_range=None,
        quantity=None,
        position_size=None,
        stop_loss_price=sl_price,
        take_profit_price=tp_price,
        context_source=None,
        parser_notes=[],
        ticker=ticker,
        option_type="CALL",  # placeholder; irrelevant for MODIFY
        strike=0.0,
        expiry=date.today(),  # placeholder; irrelevant for MODIFY
        symbol="",
    )
