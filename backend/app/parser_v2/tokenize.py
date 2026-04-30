"""Tokenize phase — content string → list[Token].

Algorithm: single-pass greedy scanner.
At each position i:
  1. Skip whitespace + punctuation.
  2. Try RANGE regex (PRICE + sep + PRICE).
  3. Try PRICE regex (with sanity cap < 10000).
  4. Try TICKER (ASCII letters [A-Za-z]{2,5}).
  5. Try Chinese alias longest-match (from ticker_aliases).
  6. Try vocab phrase longest-match (from vocab.PHRASES_LENGTH_DESC).
  7. Else single-char OTHER token.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.parser import ticker_aliases
from app.parser_v2 import vocab

_WHITESPACE = set(" \t\n　")
_PUNCT = set("，。；：、！？,.;:!?、")

# PRICE accepts ASCII '.' as well as Chinese fullwidth '。' as decimal point —
# corpus has '203。3' / '15。03' input from sloppy mobile typing.
_RANGE_RE = re.compile(r"(\d{1,4}(?:[.。]\d{1,3})?)\s*(?:-|到|至)\s*(\d{1,4}(?:[.。]\d{1,3})?)")
_PRICE_RE = re.compile(r"\d{1,4}(?:[.。]\d{1,3})?")
_TICKER_RE = re.compile(r"[A-Za-z]{2,5}")

# Common English words frequently embedded in Chinese signal text but not
# meant as stock tickers. Excluding these as TICKER prevents '杀call' /
# 'put结算' / 'AI股' / 'TRUMP THREATENS' from anchoring directives.
_COMMON_WORD_BLOCKLIST: frozenset[str] = frozenset({
    "CALL", "PUT", "AI", "BULL", "BEAR", "ETF",
    "AS", "IS", "IT", "OF", "ON", "AT", "TO", "OR", "BY",
    "AND", "THE", "FOR", "BUT", "NOT", "NTS",
})


@dataclass
class Token:
    tag: str
    value: str
    start: int
    end: int
    direction: str | None = None  # 'BUY' | 'SELL' for ACTION_IMP only
    weak: bool = False  # for QUANTIFIER ('点' etc.)


def tokenize(content: str) -> list[Token]:
    if not content:
        return []
    tokens: list[Token] = []
    n = len(content)
    i = 0
    aliases_sorted = ticker_aliases._get_items_sorted()

    while i < n:
        c = content[i]
        # 1. Skip whitespace + punctuation
        if c in _WHITESPACE or c in _PUNCT:
            i += 1
            continue

        # 2. RANGE (must come before PRICE because PRICE is a prefix).
        # Reject when followed by '点' (time-of-day '4-4点半' / '3-4点钟') or
        # when start == end (degenerate '4-4').
        m = _RANGE_RE.match(content, i)
        if m:
            try:
                start_v = float(m.group(1).replace("。", "."))
                end_v = float(m.group(2).replace("。", "."))
                # Look-ahead for '点' which indicates time, not price
                end_pos = m.end()
                followed_by_dian = end_pos < len(content) and content[end_pos] == "点"
                if start_v != end_v and not followed_by_dian:
                    tokens.append(Token(tag="RANGE", value=m.group(0).replace("。", "."), start=i, end=m.end()))
                    i = m.end()
                    continue
                if followed_by_dian:
                    # Skip the entire range as time chars
                    for ch in m.group(0):
                        tokens.append(Token(tag="OTHER", value=ch, start=i, end=i + 1))
                        i += 1
                    continue
            except ValueError:
                pass

        # 3. PRICE (with sanity bound + time-of-day filter)
        if c.isdigit():
            m = _PRICE_RE.match(content, i)
            if m:
                val = m.group(0).replace("。", ".")
                try:
                    if 0 < float(val) < 10000:
                        # Time-of-day filter: '4点半' / '3点38分' → not a price.
                        # Percentage filter: '4成' / '7成左右' → not a price.
                        # Month/date filter: '9月' / '11月28日' → not a price.
                        end_pos = m.end()
                        rest = content[end_pos:end_pos + 3]
                        next_ch = content[end_pos] if end_pos < len(content) else ""
                        is_time = (
                            rest.startswith("点半")
                            or rest.startswith("点钟")
                            or (rest.startswith("点") and len(content) > end_pos + 1 and content[end_pos + 1].isdigit())
                        )
                        is_pct = next_ch == "成"
                        is_month = next_ch == "月"
                        if not (is_time or is_pct or is_month):
                            tokens.append(Token(tag="PRICE", value=val, start=i, end=m.end()))
                            i = m.end()
                            continue
                except ValueError:
                    pass

        # 4. TICKER (ASCII letters; common-English-word blocklist;
        # context-suppress when preceded by '指数'/'港股'/'A股' — those mark
        # market-index references, not the stock ticker itself).
        if c.isascii() and c.isalpha():
            m = _TICKER_RE.match(content, i)
            if m:
                ticker = m.group(0).upper()
                preceded_by_index = (
                    i >= 2 and content[i - 2:i] in {"指数", "港股", "美股", "A股"}
                )
                if ticker not in _COMMON_WORD_BLOCKLIST and not preceded_by_index:
                    tokens.append(Token(tag="TICKER", value=ticker, start=i, end=m.end()))
                    i = m.end()
                    continue
                else:
                    for ch in m.group(0):
                        tokens.append(Token(tag="OTHER", value=ch, start=i, end=i + 1))
                        i += 1
                    continue

        # 5. Chinese alias longest-match
        matched_alias = False
        for alias, ticker in aliases_sorted:
            if content.startswith(alias, i):
                tokens.append(Token(tag="TICKER", value=ticker, start=i, end=i + len(alias)))
                i += len(alias)
                matched_alias = True
                break
        if matched_alias:
            continue

        # 6. Vocab phrase longest-match
        matched_phrase = False
        for phrase in vocab.PHRASES_LENGTH_DESC:
            if content.startswith(phrase, i):
                tag = vocab.PHRASE_TO_TAG[phrase]
                direction = vocab.verb_direction(phrase) if tag == "ACTION_IMP" else None
                weak = phrase in vocab.QUANTIFIER_WEAK
                tokens.append(Token(
                    tag=tag,
                    value=phrase,
                    start=i,
                    end=i + len(phrase),
                    direction=direction,
                    weak=weak,
                ))
                i += len(phrase)
                matched_phrase = True
                break
        if matched_phrase:
            continue

        # 7. Fallback: single-char OTHER
        tokens.append(Token(tag="OTHER", value=c, start=i, end=i + 1))
        i += 1

    return tokens
