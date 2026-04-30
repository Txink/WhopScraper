"""Smoke test: vocab_shared maps are importable and complete."""

from app.parser.vocab_shared import _FRACTION_MAP, _SELL_FRACTION_MAP


def test_fraction_map_has_core_entries() -> None:
    for k in ["常规仓", "常规仓的一半", "一半", "半仓"]:
        assert k in _FRACTION_MAP, f"{k!r} missing from _FRACTION_MAP"
    # 底仓 not in fraction map by design — appears only in vocab.py POSITION_SIZE_PHRASES
    assert "底仓" not in _FRACTION_MAP


def test_sell_fraction_map_has_core_entries() -> None:
    for k in ["1/2", "全部", "剩下一半", "部分", "那部分"]:
        assert k in _SELL_FRACTION_MAP, f"{k!r} missing from _SELL_FRACTION_MAP"


def test_page_settings_still_imports() -> None:
    from app.whop.page_settings import position_size_to_fraction, sell_quantity_to_fraction

    assert position_size_to_fraction("常规仓的一半") == 0.5
    assert sell_quantity_to_fraction("剩下一半") == 0.5
    assert position_size_to_fraction(None) == 1.0
    assert sell_quantity_to_fraction("") == 1.0
