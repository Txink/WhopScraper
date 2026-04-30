"""End-to-end parse() smoke tests — small set, full harness in Task 9."""

import pytest

from app.domain.instruction import InstructionType
from app.parser_v2.parse import parse


def test_basic_sell_e2e() -> None:
    inst = parse("TSLL 27.2出一半", message_id="t1")
    assert inst is not None
    assert inst.instruction_type == InstructionType.SELL
    assert inst.ticker == "TSLL"
    assert inst.symbol == "TSLL.US"
    assert inst.price == pytest.approx(27.2)
    assert inst.sell_quantity == "一半"


def test_basic_buy_e2e() -> None:
    inst = parse("nvdl 79加常规仓的一半", message_id="t2")
    assert inst is not None
    assert inst.instruction_type == InstructionType.BUY
    assert inst.ticker == "NVDL"
    assert inst.price == pytest.approx(79.0)
    assert inst.position_size == "常规仓的一半"


def test_lot_ref_e2e() -> None:
    inst = parse("amd 200出昨天192的", message_id="t3")
    assert inst is not None
    assert inst.instruction_type == InstructionType.SELL
    assert inst.ticker == "AMD"
    assert inst.price == pytest.approx(200.0)
    assert inst.referenced_lot_price == pytest.approx(192.0)


def test_chatter_modal_returns_none() -> None:
    """'78-80附近可以买了长拿' — MODAL '可以' rejects."""
    inst = parse("nvdl 78-80附近可以买了长拿", message_id="t4")
    assert inst is None


def test_chatter_observation_returns_none() -> None:
    inst = parse("hims 都看能到43附近在回吸", message_id="t5")
    assert inst is None


def test_chatter_past_ref_returns_none() -> None:
    inst = parse("oklo 昨天是106吸的", message_id="t6")
    assert inst is None


def test_no_anchor_returns_none() -> None:
    inst = parse("这个我就再拿一会看", message_id="t7")
    assert inst is None


def test_no_ticker_returns_none() -> None:
    """'加一半' — no ticker → proximity gate fails."""
    inst = parse("加一半", message_id="t8")
    assert inst is None


def test_alias_resolved_e2e() -> None:
    inst = parse("博通 26.5 买一半", message_id="t9")
    assert inst is not None
    assert inst.ticker == "AVGO"
    assert inst.price == pytest.approx(26.5)


def test_chatter_anchor_rejected_falls_through_to_next_clause() -> None:
    """Multi-clause: first clause is chatter, second is valid signal.
    '昨天是106吸的。tsll 27.2出一半' — period splits clauses, first clause has
    past-ref chatter, second clause is valid."""
    inst = parse("昨天是106吸的。TSLL 27.2出一半", message_id="t10")
    assert inst is not None
    assert inst.ticker == "TSLL"
    assert inst.price == pytest.approx(27.2)
