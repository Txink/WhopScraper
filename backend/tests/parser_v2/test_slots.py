"""Slot-fill phase tests — including 5 lot-ref rules."""

from app.parser_v2.anchors import find_anchor
from app.parser_v2.clauses import split_clauses
from app.parser_v2.slots import fill_slots
from app.parser_v2.tokenize import tokenize


def _slots(content: str):
    toks = tokenize(content)
    clauses = split_clauses(toks, content=content)
    anchor = find_anchor(clauses)
    assert anchor is not None, f"no anchor for {content!r}"
    return fill_slots(anchor)


def test_basic_sell_fields() -> None:
    s = _slots("TSLL 27.2出一半")
    assert s["instruction_type"] == "SELL"
    assert s["ticker"] == "TSLL"
    assert s["symbol"] == "TSLL.US"
    assert s["price"] == 27.2
    assert s["price_range"] is None
    assert s["referenced_lot_price"] is None
    assert s["sell_quantity"] == "一半"
    assert s["position_size"] is None


def test_basic_buy_with_position_size() -> None:
    s = _slots("nvdl 79加常规仓的一半")
    assert s["instruction_type"] == "BUY"
    assert s["ticker"] == "NVDL"
    assert s["price"] == 79.0
    assert s["sell_quantity"] is None
    assert s["position_size"] == "常规仓的一半"


def test_buy_position_size_dual_role_yiban() -> None:
    """'17.07回吸了一半tsll' — '一半' as POSITION_SIZE in BUY context."""
    s = _slots("17.07回吸了一半tsll")
    assert s["instruction_type"] == "BUY"
    assert s["ticker"] == "TSLL"
    assert s["position_size"] == "一半"


def test_price_range() -> None:
    s = _slots("nvdl 88.5-88.6 接")
    assert s["price"] is None
    assert s["price_range"] == (88.5, 88.6)


# Lot-ref rules R1-R5


def test_lot_ref_R1_price_de() -> None:
    """R1: PRICE + 的 → '200出昨天192的' → lot=192."""
    s = _slots("amd 200出昨天192的")
    assert s["price"] == 200.0
    assert s["referenced_lot_price"] == 192.0


def test_lot_ref_R2_price_part() -> None:
    """R2: PRICE + 部分 → 'tsll 12.32 部分 12.4出' → lot=12.32."""
    s = _slots("tsll 12.32 部分 12.4出")
    assert s["price"] == 12.4
    assert s["referenced_lot_price"] == 12.32


def test_lot_ref_R3_past_ref_then_price() -> None:
    """R3: PAST_REF near PRICE → '之前78...在78.4出' → lot=78."""
    s = _slots("oklo盘前有利好把之前78的部分在78.4出")
    assert s["price"] == 78.4
    assert s["referenced_lot_price"] == 78.0


def test_lot_ref_R4_price_action_de() -> None:
    """R4: PRICE + ACTION_IMP + 的 → '14.31出一半 14吸的' → lot=14."""
    s = _slots("tsll 14.31出一半 14吸的")
    assert s["price"] == 14.31
    assert s["referenced_lot_price"] == 14.0


def test_lot_ref_R5_right_side_price_quantifier() -> None:
    """R5: anchor right has TICKER+PRICE+QUANTIFIER, left has main price.
    '23.32出了bmnr21.5剩下一半' → main=23.32, lot=21.5."""
    s = _slots("23.32出了bmnr21.5剩下一半")
    assert s["price"] == 23.32
    assert s["referenced_lot_price"] == 21.5
    assert s["sell_quantity"] == "剩下一半"


def test_lot_ref_R5_alt() -> None:
    s = _slots("12.52出tsll11.76剩下一半")
    assert s["price"] == 12.52
    assert s["referenced_lot_price"] == 11.76


# Quantifier handling


def test_sell_quantity_full_form() -> None:
    s = _slots("conl 17.5出全部")
    assert s["sell_quantity"] == "全部"


def test_sell_quantity_remaining_half() -> None:
    s = _slots("hood 135.2出剩下一半")
    assert s["sell_quantity"] == "剩下一半"


def test_weak_quantifier_ignored() -> None:
    """'减点' — '点' is weak; sell_quantity should be None."""
    s = _slots("tsll 12 减点")
    assert s["sell_quantity"] is None


# Position size variants


def test_position_size_didi() -> None:
    """'19.1建了底仓' → '底仓'."""
    s = _slots("tsll 19.1建底仓")
    assert s["position_size"] == "底仓"


def test_no_referenced_lot_when_only_one_price() -> None:
    """Single PRICE clause → referenced_lot_price=None."""
    s = _slots("tsll14.1出掉财报前博财报的仓位")
    assert s["referenced_lot_price"] is None
