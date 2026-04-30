"""Slot-fill phase — Anchor → 6-field dict.

Output dict keys:
  instruction_type, ticker, symbol, price, price_range,
  referenced_lot_price, sell_quantity, position_size

Lot-ref rules (R1-R5) per spec §10.4:
  R1: PRICE + OTHER:'的'        → that PRICE is lot ref
  R2: PRICE + OTHER:'部分'/'那部分' (with optional 的)
  R3: PAST_REF + PRICE within ≤3 tokens
  R4: PRICE + ACTION_IMP + OTHER:'的'  (e.g., '14 吸 的')
  R5: anchor right side TICKER?+PRICE+QUANTIFIER, left side has main PRICE
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.parser_v2.anchors import Anchor
from app.parser_v2.tokenize import Token


def fill_slots(anchor: Anchor) -> dict[str, Any]:
    tokens = anchor.clause.tokens
    verb_idx = anchor.verb_index

    out: dict[str, Any] = {
        "instruction_type": anchor.direction,
        "ticker": None,
        "symbol": "",
        "price": None,
        "price_range": None,
        "referenced_lot_price": None,
        "sell_quantity": None,
        "position_size": None,
    }

    # ----- ticker -----
    ticker_tok = _nearest(tokens, verb_idx, lambda t: t.tag == "TICKER")
    if ticker_tok is not None:
        out["ticker"] = ticker_tok.value
        out["symbol"] = f"{ticker_tok.value}.US"

    # ----- main price / range -----
    main_pr = _nearest(tokens, verb_idx, lambda t: t.tag in {"PRICE", "RANGE"})
    if main_pr is not None:
        if main_pr.tag == "RANGE":
            out["price_range"] = _parse_range(main_pr.value)
        else:
            out["price"] = float(main_pr.value)

    # ----- referenced_lot_price (R1-R5) -----
    out["referenced_lot_price"] = _find_lot_ref(tokens, verb_idx, main_pr)

    # ----- sell_quantity / position_size -----
    if anchor.direction == "SELL":
        quant = _nearest(
            tokens,
            verb_idx,
            lambda t: t.tag == "QUANTIFIER" and not t.weak,
        )
        if quant is not None:
            out["sell_quantity"] = quant.value
        elif verb_idx > 0 and tokens[verb_idx - 1].tag == "OTHER" and tokens[verb_idx - 1].value in {"都", "全"}:
            # '都出' / '全出': verb's immediate left is '都' or '全'; treat as
            # sell-all marker. Canonical form '全部' so canonicalize maps to
            # the same string the golden curator wrote.
            out["sell_quantity"] = "全部"
    else:  # BUY
        ps = _nearest(tokens, verb_idx, lambda t: t.tag == "POSITION_SIZE")
        if ps is None:
            ps = _nearest(
                tokens,
                verb_idx,
                lambda t: t.tag == "QUANTIFIER" and not t.weak and t.value == "一半",
            )
        out["position_size"] = ps.value if ps is not None else None

    return out


# Helpers


def _nearest(tokens: list[Token], pivot_idx: int, predicate: Callable[[Token], bool]) -> Token | None:
    """Return the token nearest to pivot_idx (any direction) matching predicate."""
    n = len(tokens)
    for d in range(1, n):
        for j in (pivot_idx - d, pivot_idx + d):
            if 0 <= j < n and j != pivot_idx and predicate(tokens[j]):
                return tokens[j]
    if 0 <= pivot_idx < n and predicate(tokens[pivot_idx]):
        return tokens[pivot_idx]
    return None


def _parse_range(value: str) -> tuple[float, float]:
    """Parse RANGE token string ('28-29', '88.5 到 88.6', etc.)."""
    cleaned = value.replace("到", "-").replace("至", "-").replace(" ", "")
    parts = cleaned.split("-")
    a, b = float(parts[0]), float(parts[1])
    return (min(a, b), max(a, b))


def _find_lot_ref(
    tokens: list[Token],
    verb_idx: int,
    main_pr: Token | None,
) -> float | None:
    """Apply R1-R5 to find a lot-ref PRICE distinct from main_pr."""
    main_id = id(main_pr) if main_pr is not None else None

    # R1/R2/R4 exemption: if clause mentions '撤' (撤单 = cancel order) the
    # PRICE+的 pattern refers to a cancelled price, not a lot ref.
    has_cancel = any(t.tag == "OTHER" and t.value == "撤" for t in tokens)

    for i, t in enumerate(tokens):
        if t.tag != "PRICE" or id(t) == main_id:
            continue
        if has_cancel:
            # Skip 的-based rules; only R3 (PAST_REF before PRICE) and R5 still
            # apply because they reference a different syntactic pattern.
            for j in range(max(0, i - 3), i):
                if tokens[j].tag == "PAST_REF":
                    return float(t.value)
            if i > verb_idx and main_pr is not None and main_pr.tag == "PRICE":
                for j in range(i + 1, min(len(tokens), i + 3)):
                    if tokens[j].tag == "QUANTIFIER" and not tokens[j].weak:
                        return float(t.value)
            continue

        # R1: PRICE + OTHER:'的'
        if i + 1 < len(tokens):
            right = tokens[i + 1]
            if right.tag == "OTHER" and right.value == "的":
                return float(t.value)

        # R2: PRICE + '部分'/'那部分' (tagged QUANTIFIER per vocab; with optional 的)
        if i + 1 < len(tokens):
            right = tokens[i + 1]
            if right.value in {"部分", "那部分"} and right.tag in {"OTHER", "QUANTIFIER"}:
                return float(t.value)
        if i + 2 < len(tokens):
            r1 = tokens[i + 1]
            r2 = tokens[i + 2]
            if (
                r1.tag == "OTHER" and r1.value == "的"
                and r2.value in {"部分", "那部分"} and r2.tag in {"OTHER", "QUANTIFIER"}
            ):
                return float(t.value)

        # R3: PAST_REF preceding PRICE within ≤3 tokens
        for j in range(max(0, i - 3), i):
            if tokens[j].tag == "PAST_REF":
                return float(t.value)

        # R4: PRICE + ACTION_IMP + OTHER:'的'
        if i + 2 < len(tokens):
            r1 = tokens[i + 1]
            r2 = tokens[i + 2]
            if r1.tag == "ACTION_IMP" and r2.tag == "OTHER" and r2.value == "的":
                return float(t.value)

        # R5: anchor right side TICKER?+PRICE+QUANTIFIER, left side has main PRICE
        if i > verb_idx and main_pr is not None and main_pr.tag == "PRICE":
            for j in range(i + 1, min(len(tokens), i + 3)):
                if tokens[j].tag == "QUANTIFIER" and not tokens[j].weak:
                    return float(t.value)

    return None
