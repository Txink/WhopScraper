"""Anchor finding phase — Clause → Anchor | None.

An Anchor is an ACTION_IMP token in a clause that:
  1. Has at least one TICKER token within ±N tokens in the same clause.
  2. Has at least one PRICE or RANGE token within ±N tokens.
  3. Passes the chatter check (caller's responsibility — see chatter.py).

This module implements 1+2; chatter check lives in `chatter.py` and is
applied by the orchestrator (`parse.py`).
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

from app.parser_v2.clauses import Clause
from app.parser_v2.tokenize import Token

@dataclass
class Anchor:
    clause: Clause
    verb_token: Token
    verb_index: int
    direction: str  # 'BUY' | 'SELL'


def proximity_ok(anchor: Anchor) -> bool:
    """True if anchor's clause contains TICKER and PRICE/RANGE.

    Proximity is clause-scoped (not a tight ±N window). The clause split
    already enforces sentence-level locality; long Chinese sentences with
    intervening descriptive material still produce one clause and one anchor.
    Tighter chatter scope (±K=3) is enforced in chatter.py.
    """
    has_ticker = any(t.tag == "TICKER" for t in anchor.clause.tokens)
    has_price = any(t.tag in {"PRICE", "RANGE"} for t in anchor.clause.tokens)
    return has_ticker and has_price


def iter_imperative_anchors(clauses: list[Clause]) -> Iterator[tuple[Clause, int, Token]]:
    """Generator yielding (clause, verb_index, verb_token) for every ACTION_IMP
    token in clause order, then token order."""
    for clause in clauses:
        for idx, tok in enumerate(clause.tokens):
            if tok.tag == "ACTION_IMP":
                yield clause, idx, tok


def find_anchor(clauses: list[Clause]) -> Anchor | None:
    """Return the first ACTION_IMP that satisfies proximity_ok.

    Note: chatter check is NOT applied here — caller (parse.py orchestrator)
    must apply chatter.is_chatter() before accepting and may need to retry
    with the next candidate. This function returns the first proximity-OK
    anchor; caller iterates if rejected.
    """
    for clause, idx, tok in iter_imperative_anchors(clauses):
        a = Anchor(
            clause=clause,
            verb_token=tok,
            verb_index=idx,
            direction=tok.direction or "",
        )
        if proximity_ok(a) and a.direction in {"BUY", "SELL"}:
            return a
    return None
