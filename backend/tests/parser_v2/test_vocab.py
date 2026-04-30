"""Vocab table integrity tests."""

from app.parser_v2 import vocab


def test_buy_verbs_tagged_action_imp() -> None:
    for v in vocab.IMPERATIVE_VERBS_BUY:
        assert vocab.PHRASE_TO_TAG[v] == "ACTION_IMP"
        assert vocab.verb_direction(v) == "BUY"


def test_sell_verbs_tagged_action_imp() -> None:
    for v in vocab.IMPERATIVE_VERBS_SELL:
        assert vocab.PHRASE_TO_TAG[v] == "ACTION_IMP"
        assert vocab.verb_direction(v) == "SELL"


def test_descriptive_verbs_not_action_imp() -> None:
    for v in vocab.DESCRIPTIVE_VERBS:
        assert vocab.PHRASE_TO_TAG[v] == "ACTION_DESC"
        assert vocab.verb_direction(v) is None


def test_modal_markers_tagged() -> None:
    for v in vocab.MODAL_MARKERS:
        assert vocab.PHRASE_TO_TAG[v] == "MODAL"


def test_quantifier_weak_subset() -> None:
    assert vocab.QUANTIFIER_WEAK <= vocab.SELL_QUANTIFIERS


def test_phrases_length_desc_sorted() -> None:
    lengths = [len(p) for p in vocab.PHRASES_LENGTH_DESC]
    assert lengths == sorted(lengths, reverse=True)


def test_no_phrase_double_tagged() -> None:
    """No phrase appears in two category sets (would cause tokenize ambiguity)."""
    seen: dict[str, str] = {}
    pairs = [
        ("ACTION_IMP_BUY", vocab.IMPERATIVE_VERBS_BUY),
        ("ACTION_IMP_SELL", vocab.IMPERATIVE_VERBS_SELL),
        ("ACTION_DESC", vocab.DESCRIPTIVE_VERBS),
        ("MODAL", vocab.MODAL_MARKERS),
        ("CONDITIONAL", vocab.CONDITIONAL_MARKERS),
        ("OBSERVATION", vocab.OBSERVATION_MARKERS),
        ("PAST_REF", vocab.PAST_REF_MARKERS),
        ("QUANTIFIER", vocab.SELL_QUANTIFIERS),
        ("POSITION_SIZE", vocab.POSITION_SIZE_PHRASES),
        ("CONJ", vocab.CONJUNCTIONS),
    ]
    for cat, phrases in pairs:
        for p in phrases:
            assert p not in seen, f"{p!r} appears in both {seen[p]} and {cat}"
            seen[p] = cat


def test_known_anchor_examples() -> None:
    """Spot-check phrases that audit cases reference."""
    for v in ["买", "吸", "回吸", "加仓", "建仓", "进了"]:
        assert vocab.verb_direction(v) == "BUY", f"{v!r} should be BUY"
    for v in ["出", "卖", "减仓", "兑现", "清仓"]:
        assert vocab.verb_direction(v) == "SELL", f"{v!r} should be SELL"


def test_chatter_markers_present() -> None:
    """Core chatter markers per category present.

    '可以' intentionally excluded from MODAL — it functions as a benign
    softener in directives ('可以19.6出一半') in this corpus.
    """
    assert "可能" in vocab.MODAL_MARKERS
    assert "估计" in vocab.MODAL_MARKERS
    assert "等" in vocab.CONDITIONAL_MARKERS
    assert "看" in vocab.OBSERVATION_MARKERS
    assert "昨天" in vocab.PAST_REF_MARKERS
