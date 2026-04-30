"""Chatter rejection (anchor-level filter).

Two-layer policy + right-neighbor PAST particle check (per spec §9):

Layer 1 — clause-level (粗筛):
  If the anchor's clause contains ANY MODAL or CONDITIONAL token → reject.

Layer 2 — anchor-scope ±K (精确):
  In a window of K=3 tokens on each side of the verb_token (excluding the
  verb itself), if any OBSERVATION or PAST_REF token appears → reject.

Right-neighbor PAST particle:
  If verb_token's immediate right token is OTHER with value in
  {"的", "了的", "过的"} → reject (handles '吸的' / '吸过的').

Returns True if the anchor should be rejected (i.e., looks like chatter).
"""

from __future__ import annotations

from app.parser_v2 import vocab
from app.parser_v2.anchors import Anchor

ANCHOR_SCOPE_K = 3


def is_chatter(anchor: Anchor) -> bool:
    tokens = anchor.clause.tokens

    # Layer 1: clause-level MODAL/CONDITIONAL
    clause_tags = {t.tag for t in tokens}
    if "MODAL" in clause_tags or "CONDITIONAL" in clause_tags:
        return True

    # Layer 2: anchor-scope ±K OBSERVATION/PAST_REF
    i = anchor.verb_index
    lo = max(0, i - ANCHOR_SCOPE_K)
    hi = min(len(tokens), i + ANCHOR_SCOPE_K + 1)
    scope = tokens[lo:hi]
    for t in scope:
        if t is anchor.verb_token:
            continue
        if t.tag in {"OBSERVATION", "PAST_REF"}:
            return True

    # Right-neighbor PAST particle
    if i + 1 < len(tokens):
        right = tokens[i + 1]
        if right.tag == "OTHER" and right.value in vocab.PAST_PARTICLES:
            return True

    return False
