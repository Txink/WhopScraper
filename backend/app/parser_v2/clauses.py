"""Clause splitting phase — list[Token] → list[Clause].

Splits the token stream into clauses on:
  1. Hard punctuation (。！？；.!?; \\n) — token at boundary is a punctuation
     char that tokenize() drops. Detected via gaps in source `content`.
  2. ≥2 consecutive whitespace chars — also detected via source `content` gaps.
  3. CONJ token (vocab.CONJUNCTIONS) followed within 1-2 tokens by a new
     TICKER or PRICE/RANGE token.
  4. Chinese comma '，' followed by TICKER/PRICE — same as rule 3 but for
     punctuation.

Rules 1-2 require access to the original `content` string to detect the gap
between adjacent tokens. Rule 3 uses token-only logic.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.parser_v2 import vocab
from app.parser_v2.tokenize import Token


@dataclass
class Clause:
    tokens: list[Token]
    char_start: int
    char_end: int


_HARD_SPLIT_CHARS = set("。！？；.!?;\n")
_WS_CHARS = {" ", "\t", "　"}


def split_clauses(tokens: list[Token], content: str | None = None) -> list[Clause]:
    """Split tokens into clauses. `content` is required for whitespace-gap
    detection (rules 1, 2); if None, only token-based rules (3) apply."""
    if not tokens:
        return []

    boundaries: set[int] = set()
    boundaries.add(0)

    n = len(tokens)
    for i in range(1, n):
        prev = tokens[i - 1]
        curr = tokens[i]

        # Rule 1+2: gap-based split (requires content)
        if content is not None:
            gap = content[prev.end:curr.start]
            if any(c in _HARD_SPLIT_CHARS for c in gap):
                boundaries.add(i)
                continue
            ws_run = 0
            for c in gap:
                if c in {" ", "\t", "　"}:
                    ws_run += 1
                    if ws_run >= 2:
                        boundaries.add(i)
                        break
                else:
                    ws_run = 0

        # Rule 3: CONJ token followed by new TICKER/PRICE/RANGE
        if prev.tag == "CONJ" and curr.tag in {"TICKER", "PRICE", "RANGE"}:
            boundaries.add(i)
            continue

        # Rule 4: Chinese comma in gap followed by TICKER/PRICE
        if content is not None:
            gap = content[prev.end:curr.start]
            if "，" in gap and curr.tag in {"TICKER", "PRICE", "RANGE"}:
                boundaries.add(i)

        # Rule 5: ≥1 whitespace gap + curr begins with a soft clause-start
        # marker (temporal/topic-shift like '今天', '盘后', '剩下', '主要' …).
        # Long Chinese messages glue afterword commentary to a directive with
        # a single space; without this, OBSERVATION/MODAL in the commentary
        # disqualifies the directive at chatter Layer 1.
        # Guard: only split if clause 1 (since the previous boundary) already
        # contains TICKER + ACTION_IMP — otherwise '盘前' or '剩下' might appear
        # mid-directive ('onds 盘前冲高...出一半') and shouldn't split.
        if content is not None:
            gap = content[prev.end:curr.start]
            if any(c in _WS_CHARS for c in gap):
                rest = content[curr.start:curr.start + 6]
                if any(rest.startswith(marker) for marker in vocab.SOFT_CLAUSE_STARTS):
                    last_b = max(b for b in boundaries if b <= i)
                    window_tags = {t.tag for t in tokens[last_b:i]}
                    if "TICKER" in window_tags and "ACTION_IMP" in window_tags:
                        boundaries.add(i)

    sorted_b = sorted(boundaries) + [n]
    clauses: list[Clause] = []
    for k in range(len(sorted_b) - 1):
        start_idx = sorted_b[k]
        end_idx = sorted_b[k + 1]
        chunk = tokens[start_idx:end_idx]
        if not chunk:
            continue
        clauses.append(Clause(
            tokens=chunk,
            char_start=chunk[0].start,
            char_end=chunk[-1].end,
        ))
    return clauses
