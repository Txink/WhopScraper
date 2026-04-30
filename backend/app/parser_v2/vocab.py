"""Vocab tables for parser_v2.

All token tagging is driven by these phrase sets. Tokenize phase uses
PHRASE_TO_TAG for greedy longest-match against PHRASES_LENGTH_DESC.

Initial contents drawn from:
  - 778 trade_signal entries in data/parser_golden.json
  - 27 chatter false-positives in current v1 baseline
  - audit-flagged boundary cases

Add new phrases conservatively — every new entry can affect 1899 messages.
"""

from __future__ import annotations

# ----------------------------------------------------------------------------
# Imperative trading verbs (ACTION_IMP token tag — anchor candidates)
# ----------------------------------------------------------------------------

IMPERATIVE_VERBS_BUY: frozenset[str] = frozenset({
    "买", "买入",
    "吸", "回吸", "低吸",
    "加", "加仓", "加了", "再加",
    "开", "开仓", "建仓", "建了",
    "接", "接回", "补", "补仓", "补了",
    "进了",
})

IMPERATIVE_VERBS_SELL: frozenset[str] = frozenset({
    "卖", "卖出",
    "出", "出掉", "出了",
    "减", "减仓", "减了",
    "兑现", "平仓", "清仓",
})

# NOTE: Compound "X点" forms (买点 / 吸点 / 加点 / 出点 / 减点) are NOT compound
# verbs. They split into the verb + standalone QUANTIFIER '点' (weak) so that
# slot-fill can ignore the weak quantifier (see test_weak_quantifier_ignored).

# ----------------------------------------------------------------------------
# Descriptive verbs (ACTION_DESC — never anchor)
# ----------------------------------------------------------------------------

DESCRIPTIVE_VERBS: frozenset[str] = frozenset({
    "回踩", "转弯", "震荡", "突破", "测试", "反弹", "回调",
    "跌破", "站稳", "撑住", "持有",
})

# ----------------------------------------------------------------------------
# Modal / forecast markers (MODAL)
# ----------------------------------------------------------------------------

MODAL_MARKERS: frozenset[str] = frozenset({
    "可能", "可以", "估计", "应该", "大概", "也许", "或许",
    "打算", "计划", "准备", "会",
})

# ----------------------------------------------------------------------------
# Conditional markers (CONDITIONAL)
# ----------------------------------------------------------------------------

CONDITIONAL_MARKERS: frozenset[str] = frozenset({
    "等", "如果", "假如", "万一",
    "没破", "没跌破", "没站稳", "才",
})

# ----------------------------------------------------------------------------
# Observation markers (OBSERVATION)
# ----------------------------------------------------------------------------

OBSERVATION_MARKERS: frozenset[str] = frozenset({
    "看", "看下", "看看", "看一下",
    "注意", "关注", "观察",
    "比如", "比方", "之类",
    "盘后看", "盘前看",
})

# ----------------------------------------------------------------------------
# Past-reference markers (PAST_REF)
# ----------------------------------------------------------------------------

PAST_REF_MARKERS: frozenset[str] = frozenset({
    "之前", "上次", "上一次", "上一轮",
    "昨天", "前天", "财报那天", "上周",
    "历史", "原来",
})

# ----------------------------------------------------------------------------
# Quantifiers (QUANTIFIER — sell_quantity candidates; "一半" also drives
# position_size dual-role at slot phase)
# ----------------------------------------------------------------------------

SELL_QUANTIFIERS: frozenset[str] = frozenset({
    "一半", "全部", "全出", "都出",
    "剩下", "剩下一半",
    "部分", "那部分",
    "1/2", "1/3", "1/4", "2/3", "3/4",
    "三分之一", "三分之二", "四分之一",
    "点",
})

# Weak quantifiers — present as tokens (so they don't fall to OTHER) but
# slot phase ignores them when filling sell_quantity.
QUANTIFIER_WEAK: frozenset[str] = frozenset({"点"})

# ----------------------------------------------------------------------------
# Position size phrases (POSITION_SIZE)
# ----------------------------------------------------------------------------

POSITION_SIZE_PHRASES: frozenset[str] = frozenset({
    "常规仓", "中仓位",
    "常规仓的一半", "常规一半", "常规的一半",
    "半仓", "一半仓",
    "小仓位", "轻仓",
    "大仓位", "重仓",
    "满仓", "底仓",
})

# ----------------------------------------------------------------------------
# Conjunctions (CONJ — drive soft clause splits)
# ----------------------------------------------------------------------------

CONJUNCTIONS: frozenset[str] = frozenset({"和", "与", "或者", "或", "再"})

# ----------------------------------------------------------------------------
# Past particles (used by chatter.py right-neighbor check; not vocab tokens)
# ----------------------------------------------------------------------------

PAST_PARTICLES: frozenset[str] = frozenset({"的", "了的", "过的"})

# ----------------------------------------------------------------------------
# Derived tables: PHRASE_TO_TAG (lookup) + PHRASES_LENGTH_DESC (greedy scan)
# ----------------------------------------------------------------------------


def _build_phrase_to_tag() -> dict[str, str]:
    table: dict[str, str] = {}
    for v in IMPERATIVE_VERBS_BUY:
        table[v] = "ACTION_IMP"
    for v in IMPERATIVE_VERBS_SELL:
        table[v] = "ACTION_IMP"
    for v in DESCRIPTIVE_VERBS:
        table[v] = "ACTION_DESC"
    for v in MODAL_MARKERS:
        table[v] = "MODAL"
    for v in CONDITIONAL_MARKERS:
        table[v] = "CONDITIONAL"
    for v in OBSERVATION_MARKERS:
        table[v] = "OBSERVATION"
    for v in PAST_REF_MARKERS:
        table[v] = "PAST_REF"
    for v in SELL_QUANTIFIERS:
        table[v] = "QUANTIFIER"
    for v in POSITION_SIZE_PHRASES:
        table[v] = "POSITION_SIZE"
    for v in CONJUNCTIONS:
        table[v] = "CONJ"
    return table


PHRASE_TO_TAG: dict[str, str] = _build_phrase_to_tag()

PHRASES_LENGTH_DESC: list[str] = sorted(PHRASE_TO_TAG.keys(), key=lambda p: -len(p))


def verb_direction(verb: str) -> str | None:
    """Return 'BUY' / 'SELL' for imperative verbs; None otherwise."""
    if verb in IMPERATIVE_VERBS_BUY:
        return "BUY"
    if verb in IMPERATIVE_VERBS_SELL:
        return "SELL"
    return None
