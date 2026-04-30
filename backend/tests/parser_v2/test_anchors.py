"""Anchor finding phase tests."""

from app.parser_v2.anchors import Anchor, find_anchor, proximity_ok
from app.parser_v2.clauses import split_clauses
from app.parser_v2.tokenize import tokenize


def _anchor_for(content: str) -> Anchor | None:
    toks = tokenize(content)
    clauses = split_clauses(toks, content=content)
    return find_anchor(clauses)


def test_basic_anchor_on_imperative_verb() -> None:
    a = _anchor_for("TSLL 27.2出一半")
    assert a is not None
    assert a.verb_token.value == "出"
    assert a.direction == "SELL"


def test_anchor_buy_direction() -> None:
    a = _anchor_for("nvdl 79加常规仓的一半")
    assert a is not None
    assert a.direction == "BUY"


def test_no_anchor_when_no_imperative() -> None:
    """'tsll 18.7-19.2 振幅小了' — no ACTION_IMP."""
    a = _anchor_for("tsll 18.7-19.2 振幅小了")
    assert a is None


def test_no_anchor_when_proximity_fails() -> None:
    """ACTION_IMP exists but no PRICE/RANGE in clause."""
    a = _anchor_for("tsll 加")
    assert a is None


def test_first_imperative_wins() -> None:
    """When two ACTION_IMP in same clause, take first."""
    a = _anchor_for("tsll 14.31出一半 14吸的")
    assert a is not None
    assert a.verb_token.value == "出"


def test_proximity_ok_within_window() -> None:
    """proximity_ok returns True when TICKER + PRICE within ±N=8."""
    toks = tokenize("TSLL 27.2出一半")
    clauses = split_clauses(toks, content="TSLL 27.2出一半")
    clause = clauses[0]
    verb_idx = next(i for i, t in enumerate(clause.tokens) if t.tag == "ACTION_IMP")
    a = Anchor(clause=clause, verb_token=clause.tokens[verb_idx], verb_index=verb_idx, direction="SELL")
    assert proximity_ok(a) is True
