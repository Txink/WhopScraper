"""parser_v2 entry point — orchestrates the 5 phases.

If the first proximity-OK candidate trips chatter, retry with the next
candidate (chatter is per-anchor, not global). Returns None if every
candidate is rejected or no candidates exist.

Signature mirrors v1's `app.parser.stock_parser.parse(content, *, message_id)`
so the harness and downstream callers don't need to change.
"""

from __future__ import annotations

from app.domain.instruction import StockInstruction
from app.parser_v2._make import make_stock_instruction
from app.parser_v2.anchors import Anchor, iter_imperative_anchors, proximity_ok
from app.parser_v2.chatter import is_chatter
from app.parser_v2.clauses import split_clauses
from app.parser_v2.slots import fill_slots
from app.parser_v2.tokenize import tokenize


def parse(content: str, *, message_id: str) -> StockInstruction | None:
    if not content:
        return None
    tokens = tokenize(content)
    if not tokens:
        return None
    clauses = split_clauses(tokens, content=content)

    for clause, idx, tok in iter_imperative_anchors(clauses):
        direction = tok.direction
        if direction not in {"BUY", "SELL"}:
            continue
        anchor = Anchor(
            clause=clause,
            verb_token=tok,
            verb_index=idx,
            direction=direction,
        )
        if not proximity_ok(anchor):
            continue
        if is_chatter(anchor):
            continue
        slots = fill_slots(anchor)
        return make_stock_instruction(**slots)
    return None
