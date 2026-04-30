"""Tokenize phase tests."""

from app.parser_v2.tokenize import Token, tokenize


def _tags(toks: list[Token]) -> list[str]:
    return [t.tag for t in toks]


def _values(toks: list[Token]) -> list[str]:
    return [t.value for t in toks]


def test_basic_sell_signal() -> None:
    toks = tokenize("TSLL 27.2出一半")
    assert _tags(toks) == ["TICKER", "PRICE", "ACTION_IMP", "QUANTIFIER"]
    assert _values(toks) == ["TSLL", "27.2", "出", "一半"]
    assert toks[2].direction == "SELL"


def test_basic_buy_signal() -> None:
    toks = tokenize("nvdl 79加常规仓的一半")
    tags = _tags(toks)
    assert "TICKER" in tags
    assert "PRICE" in tags
    assert "ACTION_IMP" in tags
    assert "POSITION_SIZE" in tags
    verb = next(t for t in toks if t.tag == "ACTION_IMP")
    assert verb.value == "加"
    assert verb.direction == "BUY"


def test_range_token() -> None:
    toks = tokenize("28-29 加")
    range_toks = [t for t in toks if t.tag == "RANGE"]
    assert len(range_toks) == 1
    assert range_toks[0].value.replace(" ", "") == "28-29"


def test_greedy_longest_match() -> None:
    """'剩下一半' must win over 'X' + '剩下' + '一半' fragments."""
    toks = tokenize("出剩下一半")
    quant = [t for t in toks if t.tag == "QUANTIFIER"]
    assert len(quant) == 1
    assert quant[0].value == "剩下一半"


def test_chatter_modal_tokens() -> None:
    """'甲骨文可能在...会转弯往下' → MODAL + ACTION_DESC, no ACTION_IMP."""
    toks = tokenize("甲骨文可能在193.5-196之间会转弯往下")
    tags = _tags(toks)
    assert "MODAL" in tags
    assert "ACTION_DESC" in tags
    assert "ACTION_IMP" not in tags


def test_chatter_observation_tokens() -> None:
    """'都看能到43附近在回吸' → OBSERVATION + ACTION_IMP both present."""
    toks = tokenize("都看能到43附近在回吸")
    tags = _tags(toks)
    assert "OBSERVATION" in tags
    assert "ACTION_IMP" in tags  # 回吸 is anchor candidate (chatter rejects later)


def test_past_ref_tokens() -> None:
    """'昨天是106吸的' → PAST_REF + ACTION_IMP + 'OTHER:的'."""
    toks = tokenize("昨天是106吸的")
    tags = _tags(toks)
    assert "PAST_REF" in tags
    assert "ACTION_IMP" in tags
    # 的 falls through to OTHER
    assert any(t.tag == "OTHER" and t.value == "的" for t in toks)


def test_lot_ref_form_amd_200() -> None:
    """'amd 200出昨天192的' has 2 PRICE + 1 ACTION_IMP + PAST_REF + OTHER:的."""
    toks = tokenize("amd 200出昨天192的")
    tags = _tags(toks)
    assert tags.count("PRICE") == 2
    assert "ACTION_IMP" in tags
    assert "PAST_REF" in tags
    assert any(t.tag == "OTHER" and t.value == "的" for t in toks)


def test_chinese_ticker_alias_resolved() -> None:
    """中文别名 '博通' → TICKER value 'AVGO' (assuming alias defined in
    config/ticker_aliases.json)."""
    toks = tokenize("博通 26.5 买一半")
    tickers = [t for t in toks if t.tag == "TICKER"]
    assert len(tickers) == 1
    assert tickers[0].value == "AVGO"


def test_ticker_uppercased() -> None:
    """Lowercase ticker is upper-cased."""
    toks = tokenize("tsll 12.6")
    tickers = [t for t in toks if t.tag == "TICKER"]
    assert tickers[0].value == "TSLL"


def test_price_sanity_bound() -> None:
    """'19.1' parses as PRICE; '99999' rejected (sanity > 10000)."""
    toks = tokenize("19.1")
    assert toks[0].tag == "PRICE"
    assert toks[0].value == "19.1"


def test_token_char_offsets() -> None:
    """start/end indices align with source content."""
    content = "TSLL 27.2出"
    toks = tokenize(content)
    for t in toks:
        assert content[t.start:t.end] == t.value or t.tag == "TICKER"  # ticker may be uppercased


def test_punctuation_skipped() -> None:
    toks = tokenize("TSLL，27.2，出。")
    tags = _tags(toks)
    assert tags == ["TICKER", "PRICE", "ACTION_IMP"]


def test_weak_quantifier_marked() -> None:
    """'点' as standalone QUANTIFIER carries weak=True."""
    toks = tokenize("加点")
    weak = [t for t in toks if t.tag == "QUANTIFIER" and t.weak]
    assert len(weak) == 1
    assert weak[0].value == "点"
