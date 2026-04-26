"""Tests for scripts/validate_parser.py — matcher + run_validation."""

import pytest

from app.domain.instruction import InstructionType, StockInstruction
from scripts.validate_parser import match


def _stock(
    *,
    instruction_type: InstructionType = InstructionType.SELL,
    ticker: str = "TSLL",
    price: float | None = 27.2,
    price_range: tuple[float, float] | None = None,
    referenced_lot_price: float | None = None,
    sell_quantity: str | None = None,
    position_size: str | None = None,
) -> StockInstruction:
    return StockInstruction(
        instruction_type=instruction_type,
        price=price,
        price_range=price_range,
        quantity=None,
        position_size=position_size,
        stop_loss_price=None,
        take_profit_price=None,
        context_source=None,
        parser_notes=[],
        ticker=ticker,
        symbol=f"{ticker}.US",
        sell_quantity=sell_quantity,
        referenced_lot_price=referenced_lot_price,
    )


def _expected(**overrides) -> dict:
    base = {
        "instruction_type": "SELL",
        "ticker": "TSLL",
        "price": 27.2,
        "price_range": None,
        "referenced_lot_price": None,
        "sell_quantity": None,
        "position_size": None,
    }
    base.update(overrides)
    return base


def test_match_both_none_passes() -> None:
    assert match(None, None) is True


def test_match_one_none_fails() -> None:
    assert match(_stock(), None) is False
    assert match(None, _expected()) is False


def test_match_identical_passes() -> None:
    assert match(_stock(), _expected()) is True


def test_match_different_instruction_type_fails() -> None:
    assert match(_stock(instruction_type=InstructionType.BUY), _expected()) is False


def test_match_different_ticker_fails() -> None:
    assert match(_stock(ticker="HOOD"), _expected()) is False


def test_match_price_within_tolerance_passes() -> None:
    # 0.0009 difference < 0.001 tolerance
    assert match(_stock(price=27.2009), _expected(price=27.2)) is True


def test_match_price_outside_tolerance_fails() -> None:
    assert match(_stock(price=27.21), _expected(price=27.2)) is False


def test_match_price_one_null_fails() -> None:
    # StockInstruction requires price or price_range; supply a range so the
    # domain invariant holds, but expected still has a scalar price — mismatch.
    assert match(_stock(price=None, price_range=(27.0, 27.5)), _expected(price=27.2)) is False


def test_match_price_both_null_passes() -> None:
    assert match(_stock(price=None, price_range=(27.0, 27.5)),
                 _expected(price=None, price_range=[27.0, 27.5])) is True


def test_match_price_range_within_tolerance_passes() -> None:
    assert match(_stock(price=None, price_range=(27.0009, 27.5)),
                 _expected(price=None, price_range=[27.0, 27.5])) is True


def test_match_price_range_outside_tolerance_fails() -> None:
    assert match(_stock(price=None, price_range=(27.1, 27.5)),
                 _expected(price=None, price_range=[27.0, 27.5])) is False


def test_match_referenced_lot_price_compared() -> None:
    assert match(_stock(referenced_lot_price=12.42),
                 _expected(referenced_lot_price=12.42)) is True
    assert match(_stock(referenced_lot_price=12.42),
                 _expected(referenced_lot_price=12.5)) is False


def test_match_sell_quantity_strict() -> None:
    assert match(_stock(sell_quantity="1/2"), _expected(sell_quantity="1/2")) is True
    assert match(_stock(sell_quantity="一半"), _expected(sell_quantity="1/2")) is False


def test_match_position_size_strict() -> None:
    assert match(_stock(position_size="常规仓的一半"),
                 _expected(position_size="常规仓的一半")) is True


def test_match_ticker_case_sensitive_uppercase() -> None:
    """Ticker comes uppercase from _make_stock; expected also uppercase. Match is direct."""
    assert match(_stock(ticker="TSLL"), _expected(ticker="TSLL")) is True


# ---------------------------------------------------------------------------
# run_validation tests
# ---------------------------------------------------------------------------

import json
from pathlib import Path

from scripts.validate_parser import (
    Diff,
    ValidationResult,
    run_validation,
)


def _write_corpus(tmp_path: Path, entries: list[dict]) -> Path:
    p = tmp_path / "corpus.json"
    p.write_text(json.dumps(entries, ensure_ascii=False))
    return p


def _write_golden(tmp_path: Path, entries: list[dict]) -> Path:
    p = tmp_path / "golden.json"
    p.write_text(json.dumps(entries, ensure_ascii=False))
    return p


def _msg(domid: str, content: str) -> dict:
    return {"domID": domid, "content": content,
            "timestamp": "2025-10-07 00:00:00.000",
            "refer": None, "position": "single", "history": []}


def _gold_chatter(domid: str, content: str) -> dict:
    return {"domID": domid, "content": content,
            "classification": "chatter", "expected": None,
            "requires_context": False, "notes": ""}


def _gold_ambiguous(domid: str, content: str, notes: str = "") -> dict:
    return {"domID": domid, "content": content,
            "classification": "ambiguous", "expected": None,
            "requires_context": False, "notes": notes}


def _gold_signal(domid: str, content: str, expected: dict, *, requires_context: bool = False) -> dict:
    return {"domID": domid, "content": content,
            "classification": "trade_signal", "expected": expected,
            "requires_context": requires_context, "notes": ""}


def test_run_validation_alias_exemption_skips_recovery_check(tmp_path: Path) -> None:
    """When parser_v2.parse is stock_parser.parse (the B1 alias), recovery
    constraint must be skipped — even if v1 fails on real signals."""
    corpus = [_msg("m1", "TSLL 27.2出一半"),  # v1 parses, expected matches
              _msg("m2", "未知形状的信号 28.4 出 hood")]  # v1 may fail
    golden = [_gold_signal("m1", "TSLL 27.2出一半", _expected()),
              _gold_signal("m2", "未知形状的信号 28.4 出 hood",
                           _expected(ticker="HOOD", price=28.4))]
    result = run_validation(
        corpus_path=_write_corpus(tmp_path, corpus),
        golden_path=_write_golden(tmp_path, golden),
    )
    # Under alias mode: regressions=0 and chatter_fp=0 enough for PASS,
    # regardless of how many trade_signals v2 still misses.
    assert result.summary.passed is True
    assert result.summary.recovery_rate is None  # exempt → undefined


def test_run_validation_chatter_false_positive_fails(tmp_path: Path, monkeypatch) -> None:
    """If v2 (= v1 in alias mode) returns non-None on a chatter message,
    that's a false positive and run_validation must report it."""
    from scripts import validate_parser as vp

    def _fake_parse(content, *, message_id):
        return _stock()  # always returns SELL TSLL 27.2

    monkeypatch.setattr(vp, "_v1_parse", _fake_parse)
    monkeypatch.setattr(vp, "_v2_parse", _fake_parse)
    monkeypatch.setattr(vp, "_v2_is_alias_of_v1", lambda: False)

    corpus = [_msg("c1", "大家好")]
    golden = [_gold_chatter("c1", "大家好")]
    result = run_validation(
        corpus_path=_write_corpus(tmp_path, corpus),
        golden_path=_write_golden(tmp_path, golden),
    )
    assert len(result.false_positives_on_chatter_v2) == 1
    assert result.summary.passed is False


def test_run_validation_ambiguous_skipped(tmp_path: Path) -> None:
    corpus = [_msg("a1", "TSLL 跌破 11 都出")]
    golden = [_gold_ambiguous("a1", "TSLL 跌破 11 都出", "条件触发")]
    result = run_validation(
        corpus_path=_write_corpus(tmp_path, corpus),
        golden_path=_write_golden(tmp_path, golden),
    )
    assert result.summary.by_classification["ambiguous"] == 1
    # Ambiguous never enters regression / recovery / still_failing buckets
    assert len(result.regressions) == 0
    assert len(result.recoveries) == 0
    assert len(result.still_failing_non_context) == 0


def test_run_validation_requires_context_separate_bucket(tmp_path: Path) -> None:
    """A trade_signal with requires_context=True doesn't enter regression /
    recovery / still_failing_non_context — it goes to its own bucket."""
    corpus = [_msg("r1", "15.2 全出")]  # parser can't extract ticker
    golden = [_gold_signal(
        "r1", "15.2 全出",
        _expected(ticker="TSLL", price=15.2, sell_quantity="全部"),
        requires_context=True,
    )]
    result = run_validation(
        corpus_path=_write_corpus(tmp_path, corpus),
        golden_path=_write_golden(tmp_path, golden),
    )
    assert len(result.still_failing_context_dependent) == 1
    assert len(result.still_failing_non_context) == 0
    # still_failing_context_dependent does NOT block PASS (informational)
    assert result.summary.passed is True


def test_run_validation_counts_classifications(tmp_path: Path) -> None:
    corpus = [
        _msg("a", "大家好"),
        _msg("b", "TSLL 跌破 11 都出"),
        _msg("c", "TSLL 27.2出一半"),
    ]
    golden = [
        _gold_chatter("a", "大家好"),
        _gold_ambiguous("b", "TSLL 跌破 11 都出"),
        _gold_signal("c", "TSLL 27.2出一半", _expected()),
    ]
    result = run_validation(
        corpus_path=_write_corpus(tmp_path, corpus),
        golden_path=_write_golden(tmp_path, golden),
    )
    assert result.summary.by_classification == {
        "chatter": 1, "ambiguous": 1, "trade_signal": 1,
    }
