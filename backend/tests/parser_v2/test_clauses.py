"""Clause-split phase tests."""

from app.parser_v2.clauses import split_clauses
from app.parser_v2.tokenize import tokenize


def test_single_clause_basic() -> None:
    toks = tokenize("TSLL 27.2出一半")
    clauses = split_clauses(toks)
    assert len(clauses) == 1


def test_split_on_double_space() -> None:
    """≥2 spaces splits."""
    content = "TSLL 27.2出一半  剩下一半 收盘再看看"
    toks = tokenize(content)
    clauses = split_clauses(toks, content=content)
    assert len(clauses) == 2


def test_no_split_on_single_space() -> None:
    content = "tsll 14.31 出 一半"
    toks = tokenize(content)
    clauses = split_clauses(toks, content=content)
    assert len(clauses) == 1


def test_split_on_period_punct() -> None:
    content = "TSLL 27.2出。NVDL 80加"
    toks = tokenize(content)
    clauses = split_clauses(toks, content=content)
    assert len(clauses) == 2


def test_split_on_conj_with_new_ticker() -> None:
    """CONJ '和' followed by new TICKER → split."""
    content = "tsll 14 加 和 nvdl 80 加"
    toks = tokenize(content)
    clauses = split_clauses(toks, content=content)
    assert len(clauses) == 2


def test_no_split_on_conj_without_new_ticker() -> None:
    """CONJ '和' followed by non-ticker → don't split."""
    content = "小仓位 和 大仓位 都不加"
    toks = tokenize(content)
    clauses = split_clauses(toks, content=content)
    assert len(clauses) == 1


def test_clause_has_char_range() -> None:
    content = "TSLL 27.2出一半"
    toks = tokenize(content)
    clauses = split_clauses(toks, content=content)
    assert clauses[0].char_start == 0
    assert clauses[0].char_end >= len(content) - 1


def test_lot_ref_form_stays_one_clause() -> None:
    """'tsll 14.31出一半 14吸的' is a single clause (single space, no CONJ + new ticker)."""
    content = "tsll 14.31出一半 14吸的"
    toks = tokenize(content)
    clauses = split_clauses(toks, content=content)
    assert len(clauses) == 1
