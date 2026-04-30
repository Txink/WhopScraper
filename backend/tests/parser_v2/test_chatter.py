"""Chatter-rejection tests — every 27 chatter FP from v1 baseline must
either (a) yield no anchor at all, or (b) trip is_chatter."""

import pytest

from app.parser_v2.anchors import Anchor, find_anchor, iter_imperative_anchors, proximity_ok
from app.parser_v2.chatter import is_chatter
from app.parser_v2.clauses import split_clauses
from app.parser_v2.tokenize import tokenize


def _all_anchors_rejected(content: str) -> bool:
    """Either no proximity-OK anchor exists, or every such anchor trips chatter."""
    toks = tokenize(content)
    clauses = split_clauses(toks, content=content)
    for clause, idx, tok in iter_imperative_anchors(clauses):
        a = Anchor(clause=clause, verb_token=tok, verb_index=idx, direction=tok.direction or "")
        if not proximity_ok(a) or a.direction not in {"BUY", "SELL"}:
            continue
        if not is_chatter(a):
            return False
    return True


# Layer 1 — clause-level MODAL/CONDITIONAL


def test_modal_kexi_rejects() -> None:
    """'78-80附近可以买了长拿' — MODAL '可以' in clause."""
    assert _all_anchors_rejected("78-80附近可以买了长拿")


def test_modal_keneng_rejects() -> None:
    """'甲骨文可能在...会转弯往下' — MODAL but no ACTION_IMP either way."""
    assert _all_anchors_rejected("甲骨文可能在193.5-196之间会转弯往下")


def test_conditional_deng_rejects() -> None:
    """'等讲话有大跳水再加' — CONDITIONAL '等' in clause."""
    assert _all_anchors_rejected("tsll 19.3 等讲话有大跳水再加")


# Layer 2 — anchor-scope OBSERVATION/PAST_REF


def test_observation_kan_within_scope_rejects() -> None:
    """'都看能到43附近在回吸' — OBSERVATION '看' within K=3 of anchor '吸'."""
    assert _all_anchors_rejected("hims 都看能到43附近在回吸")


def test_past_ref_zuotian_within_scope_rejects() -> None:
    """'昨天是106吸的' — PAST_REF '昨天' near anchor '吸'."""
    assert _all_anchors_rejected("oklo 昨天是106吸的")


# Right-neighbor PAST particle '的' / '了的' / '过的'


def test_right_neighbor_de_rejects() -> None:
    """'49-50吸的' — anchor '吸' right-neighbor is '的'."""
    assert _all_anchors_rejected("rklb 49-50吸的")


# Negative cases — must NOT be rejected


def test_basic_sell_not_chatter() -> None:
    """'TSLL 27.2出一半' — clean trade signal."""
    toks = tokenize("TSLL 27.2出一半")
    clauses = split_clauses(toks, content="TSLL 27.2出一半")
    a = find_anchor(clauses)
    assert a is not None
    assert is_chatter(a) is False


def test_lot_ref_with_past_far_away_not_chatter() -> None:
    """'oklo盘前有利好把之前78的部分在78.4出' — '之前' is far from '出',
    well beyond K=3. Should NOT reject."""
    toks = tokenize("oklo盘前有利好把之前78的部分在78.4出")
    clauses = split_clauses(toks, content="oklo盘前有利好把之前78的部分在78.4出")
    a = find_anchor(clauses)
    if a is None:
        pytest.skip("anchor not found; defer to slot tests")
    assert is_chatter(a) is False


def test_basic_buy_with_position_size_not_chatter() -> None:
    toks = tokenize("nvdl 79加常规仓的一半")
    clauses = split_clauses(toks, content="nvdl 79加常规仓的一半")
    a = find_anchor(clauses)
    assert a is not None
    assert is_chatter(a) is False
