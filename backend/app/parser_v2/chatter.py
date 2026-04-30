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
    i = anchor.verb_index

    # Layer 1: clause-level MODAL / CONDITIONAL / OBSERVATION.
    # If any of these markers appears anywhere in the clause, the clause is
    # forecast/example/observation, not directive. Long paragraphs that mix
    # a directive with afterword commentary should be split into separate
    # clauses (clause-split rules handle this; see clauses.py).
    clause_tags = {t.tag for t in tokens}
    if "MODAL" in clause_tags or "CONDITIONAL" in clause_tags or "OBSERVATION" in clause_tags:
        return True

    # Layer 2: BEFORE-verb PAST_REF (clause-scoped) with R3 exemption.
    # PAST_REF before the verb = past-tense talk ('昨天是106吸的',
    # '上次也是15.8附近买入') = chatter.
    # EXEMPTION: when the clause has a QUANTIFIER or POSITION_SIZE token, the
    # PAST_REF most likely qualifies a referenced lot ('之前78的部分在78.4出'
    # = R3 lot-ref form), not the action itself.
    has_quant_or_size = any(
        t.tag in {"QUANTIFIER", "POSITION_SIZE"} and not t.weak
        for t in tokens
    )
    if not has_quant_or_size:
        for t in tokens[:i]:
            if t.tag == "PAST_REF":
                return True

    # Layer 2c: verb is a 了-ending compound ('入了', '加了', '开了', '补了',
    # '出了') AND clause has PAST_REF anywhere — past-completion status update,
    # not directive ('今天就44入了 上周四').
    if anchor.verb_token.value.endswith("了") and not has_quant_or_size:
        if any(t.tag == "PAST_REF" for t in tokens):
            return True

    # Right-neighbor PAST particle
    if i + 1 < len(tokens):
        right = tokens[i + 1]
        if right.tag == "OTHER" and right.value in vocab.PAST_PARTICLES:
            return True

    return False
