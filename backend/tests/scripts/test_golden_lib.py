"""Tests for scripts/golden_lib.py — schema validator + few-shot examples."""

import pytest

from scripts.golden_lib import (
    FEW_SHOT_EXAMPLES,
    validate_golden_entry,
)


def test_validates_well_formed_chatter_entry() -> None:
    entry = {
        "domID": "post_1",
        "content": "大家好",
        "classification": "chatter",
        "expected": None,
        "requires_context": False,
        "notes": "纯打招呼",
    }
    assert validate_golden_entry(entry) == []


def test_validates_well_formed_trade_signal_entry() -> None:
    entry = {
        "domID": "post_2",
        "content": "TSLL 27.2出一半",
        "classification": "trade_signal",
        "expected": {
            "instruction_type": "SELL",
            "ticker": "TSLL",
            "price": 27.2,
            "price_range": None,
            "referenced_lot_price": None,
            "sell_quantity": "1/2",
            "position_size": None,
        },
        "requires_context": False,
        "notes": "",
    }
    assert validate_golden_entry(entry) == []


def test_validates_well_formed_ambiguous_entry() -> None:
    entry = {
        "domID": "post_3",
        "content": "TSLL 跌破 11 都出",
        "classification": "ambiguous",
        "expected": None,
        "requires_context": False,
        "notes": "条件触发",
    }
    assert validate_golden_entry(entry) == []


def test_rejects_missing_required_field() -> None:
    entry = {
        "domID": "post_x",
        "content": "x",
        "classification": "chatter",
        # missing: expected, requires_context, notes
    }
    errors = validate_golden_entry(entry)
    assert any("expected" in e for e in errors)
    assert any("requires_context" in e for e in errors)
    assert any("notes" in e for e in errors)


def test_rejects_bad_classification_value() -> None:
    entry = {
        "domID": "post_x",
        "content": "x",
        "classification": "garbage",
        "expected": None,
        "requires_context": False,
        "notes": "",
    }
    errors = validate_golden_entry(entry)
    assert any("classification" in e for e in errors)


def test_rejects_chatter_with_non_null_expected() -> None:
    entry = {
        "domID": "post_x",
        "content": "x",
        "classification": "chatter",
        "expected": {"instruction_type": "SELL", "ticker": "X", "price": 1.0,
                     "price_range": None, "referenced_lot_price": None,
                     "sell_quantity": None, "position_size": None},
        "requires_context": False,
        "notes": "",
    }
    errors = validate_golden_entry(entry)
    assert any("chatter" in e and "expected" in e for e in errors)


def test_rejects_ambiguous_with_non_null_expected() -> None:
    entry = {
        "domID": "post_x",
        "content": "x",
        "classification": "ambiguous",
        "expected": {"instruction_type": "SELL", "ticker": "X", "price": 1.0,
                     "price_range": None, "referenced_lot_price": None,
                     "sell_quantity": None, "position_size": None},
        "requires_context": False,
        "notes": "",
    }
    errors = validate_golden_entry(entry)
    assert any("ambiguous" in e and "expected" in e for e in errors)


def test_rejects_trade_signal_with_null_expected() -> None:
    entry = {
        "domID": "post_x",
        "content": "x",
        "classification": "trade_signal",
        "expected": None,
        "requires_context": False,
        "notes": "",
    }
    errors = validate_golden_entry(entry)
    assert any("trade_signal" in e and "expected" in e for e in errors)


def test_rejects_trade_signal_with_missing_expected_field() -> None:
    entry = {
        "domID": "post_x",
        "content": "x",
        "classification": "trade_signal",
        "expected": {"instruction_type": "SELL", "ticker": "X", "price": 1.0},
        # missing: price_range, referenced_lot_price, sell_quantity, position_size
        "requires_context": False,
        "notes": "",
    }
    errors = validate_golden_entry(entry)
    assert any("price_range" in e for e in errors)
    assert any("referenced_lot_price" in e for e in errors)
    assert any("sell_quantity" in e for e in errors)
    assert any("position_size" in e for e in errors)


def test_rejects_trade_signal_with_bad_instruction_type() -> None:
    entry = {
        "domID": "post_x",
        "content": "x",
        "classification": "trade_signal",
        "expected": {
            "instruction_type": "CLOSE",
            "ticker": "X", "price": 1.0,
            "price_range": None, "referenced_lot_price": None,
            "sell_quantity": None, "position_size": None,
        },
        "requires_context": False,
        "notes": "",
    }
    errors = validate_golden_entry(entry)
    assert any("instruction_type" in e for e in errors)


def test_few_shot_examples_are_themselves_valid() -> None:
    """All 10 baked-in few-shot examples must pass schema validation."""
    for i, entry in enumerate(FEW_SHOT_EXAMPLES):
        errors = validate_golden_entry(entry)
        assert errors == [], f"few-shot example {i} fails validation: {errors}"


def test_few_shot_covers_all_classifications() -> None:
    classifications = {e["classification"] for e in FEW_SHOT_EXAMPLES}
    assert classifications == {"chatter", "trade_signal", "ambiguous"}
