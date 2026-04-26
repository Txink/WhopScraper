"""validate_parser — diff stock parser outputs against parser_golden.json.

Public surface:
  - match(out, expected) -> bool          — single-message comparator
  - run_validation(...) -> ValidationResult — full harness over corpus + golden
  - main()                                — CLI entrypoint

run_validation and CLI are added in later tasks of this plan; this file
starts with the matcher only.

Match semantics — see spec section 6.3:
  strict equality:    instruction_type, ticker, sell_quantity, position_size
  ±0.001 tolerance:   price, referenced_lot_price, price_range (both ends)
  ignored:            parser_notes, context_source, symbol, quantity,
                      raw_message, message_id, stop_loss_price, take_profit_price
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

from app.domain.instruction import StockInstruction
from app.parser import stock_parser
from app.parser_v2 import parse as _parser_v2_parse


# Module-level alias indirection so tests can monkeypatch
_v1_parse: Callable = stock_parser.parse
_v2_parse: Callable = _parser_v2_parse


def _v2_is_alias_of_v1() -> bool:
    """True iff parser_v2.parse is the same function object as stock_parser.parse.
    During B1 the alias holds; B2 will replace parser_v2.__init__ with a real
    implementation, breaking the identity and triggering recovery_rate enforcement."""
    return _v2_parse is _v1_parse

PRICE_TOLERANCE = 0.001


def _float_eq(a: float | None, b: float | None, tol: float = PRICE_TOLERANCE) -> bool:
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    return abs(a - b) <= tol


def _range_eq(
    a: tuple[float, float] | None,
    b: list[float] | tuple[float, float] | None,
    tol: float = PRICE_TOLERANCE,
) -> bool:
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    return _float_eq(a[0], b[0], tol) and _float_eq(a[1], b[1], tol)


def match(out: StockInstruction | None, expected: dict[str, Any] | None) -> bool:
    """Return True iff parser output matches the golden expected dict.

    None on either side: must both be None to match. Non-None on both sides:
    compare 7 load-bearing fields per spec 6.3 rules.
    """
    if out is None and expected is None:
        return True
    if out is None or expected is None:
        return False

    if out.instruction_type.name != expected["instruction_type"]:
        return False
    if out.ticker.upper() != expected["ticker"]:
        return False
    if not _float_eq(out.price, expected["price"]):
        return False
    if not _range_eq(out.price_range, expected["price_range"]):
        return False
    if not _float_eq(out.referenced_lot_price, expected["referenced_lot_price"]):
        return False
    if (out.sell_quantity or None) != (expected["sell_quantity"] or None):
        return False
    if (out.position_size or None) != (expected["position_size"] or None):
        return False
    return True


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass
class Diff:
    """One per-message diff entry, used in regression / recovery / etc lists."""
    domID: str
    content: str
    v1: dict[str, object] | None  # serialized StockInstruction or None
    v2: dict[str, object] | None
    expected: dict[str, object] | None


@dataclass
class Summary:
    total: int
    by_classification: dict[str, int]
    trade_signals_single_msg_solvable: int
    trade_signals_requires_context: int
    v1_pass_single_msg: int
    v1_fail_single_msg: int
    v2_pass_single_msg: int
    v2_fail_single_msg: int
    regressions: int
    recoveries: int
    recovery_rate: float | None  # None when alias-exempt or denominator 0
    false_positives_on_chatter_v2: int
    still_failing_context_dependent: int
    passed: bool


@dataclass
class ValidationResult:
    summary: Summary
    regressions: list[Diff] = field(default_factory=list)
    recoveries: list[Diff] = field(default_factory=list)
    still_failing_non_context: list[Diff] = field(default_factory=list)
    still_failing_context_dependent: list[Diff] = field(default_factory=list)
    false_positives_on_chatter_v2: list[Diff] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Serialization helper for diff entries
# ---------------------------------------------------------------------------


def _instruction_to_dict(inst: StockInstruction | None) -> dict[str, object] | None:
    if inst is None:
        return None
    return {
        "instruction_type": inst.instruction_type.name,
        "ticker": inst.ticker.upper(),
        "price": inst.price,
        "price_range": list(inst.price_range) if inst.price_range else None,
        "referenced_lot_price": inst.referenced_lot_price,
        "sell_quantity": inst.sell_quantity,
        "position_size": inst.position_size,
    }


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


CORPUS_PATH_DEFAULT = Path(__file__).resolve().parent.parent.parent / "data" / "stock_origin_message.json"
GOLDEN_PATH_DEFAULT = Path(__file__).resolve().parent.parent.parent / "data" / "parser_golden.json"
REPORT_PATH_DEFAULT = Path(__file__).resolve().parent.parent.parent / "data" / "parser_validation_report.json"


def run_validation(
    *,
    corpus_path: Path | None = None,
    golden_path: Path | None = None,
) -> ValidationResult:
    """Load corpus + golden, run v1 / v2, return ValidationResult.

    Path overrides are for tests; production CLI uses the defaults.
    """
    corpus = json.loads(Path(corpus_path or CORPUS_PATH_DEFAULT).read_text())
    golden_list = json.loads(Path(golden_path or GOLDEN_PATH_DEFAULT).read_text())
    golden = {g["domID"]: g for g in golden_list}

    by_classification: Counter[str] = Counter()
    requires_context_count = 0
    single_msg_solvable_count = 0
    v1_pass_single = 0
    v1_fail_single = 0
    v2_pass_single = 0
    v2_fail_single = 0

    regressions: list[Diff] = []
    recoveries: list[Diff] = []
    still_failing_non_context: list[Diff] = []
    still_failing_context_dependent: list[Diff] = []
    false_positives_on_chatter_v2: list[Diff] = []

    for msg in corpus:
        gold = golden.get(msg["domID"])
        if gold is None:
            continue  # no golden for this message — skip silently
        cls = gold["classification"]
        by_classification[cls] += 1

        # Single-message parse only — spec decision 7
        v1_out = _v1_parse(msg["content"], message_id=msg["domID"])
        v2_out = _v2_parse(msg["content"], message_id=msg["domID"])

        if cls == "ambiguous":
            continue

        if cls == "chatter":
            if v2_out is not None:
                false_positives_on_chatter_v2.append(Diff(
                    domID=msg["domID"], content=msg["content"],
                    v1=_instruction_to_dict(v1_out),
                    v2=_instruction_to_dict(v2_out),
                    expected=None,
                ))
            continue

        # cls == "trade_signal"
        expected = gold["expected"]
        v1_pass = match(v1_out, expected)
        v2_pass = match(v2_out, expected)

        if gold["requires_context"]:
            requires_context_count += 1
            if not v2_pass:
                still_failing_context_dependent.append(Diff(
                    domID=msg["domID"], content=msg["content"],
                    v1=_instruction_to_dict(v1_out),
                    v2=_instruction_to_dict(v2_out),
                    expected=expected,
                ))
            continue

        # single-msg solvable trade_signal
        single_msg_solvable_count += 1
        if v1_pass:
            v1_pass_single += 1
        else:
            v1_fail_single += 1
        if v2_pass:
            v2_pass_single += 1
        else:
            v2_fail_single += 1

        if v1_pass and not v2_pass:
            regressions.append(Diff(
                domID=msg["domID"], content=msg["content"],
                v1=_instruction_to_dict(v1_out),
                v2=_instruction_to_dict(v2_out),
                expected=expected,
            ))
        elif not v1_pass and v2_pass:
            recoveries.append(Diff(
                domID=msg["domID"], content=msg["content"],
                v1=_instruction_to_dict(v1_out),
                v2=_instruction_to_dict(v2_out),
                expected=expected,
            ))
        elif not v1_pass and not v2_pass:
            still_failing_non_context.append(Diff(
                domID=msg["domID"], content=msg["content"],
                v1=_instruction_to_dict(v1_out),
                v2=_instruction_to_dict(v2_out),
                expected=expected,
            ))
        # else: both pass, "maintained_pass", no bucket

    # Pass criteria
    is_alias = _v2_is_alias_of_v1()
    no_regressions = len(regressions) == 0
    no_chatter_fp = len(false_positives_on_chatter_v2) == 0

    if is_alias:
        recovery_rate: float | None = None
        passed = no_regressions and no_chatter_fp
    else:
        denom = len(recoveries) + len(still_failing_non_context)
        recovery_rate = (len(recoveries) / denom) if denom > 0 else 1.0
        passed = no_regressions and no_chatter_fp and recovery_rate >= 0.20

    summary = Summary(
        total=len(corpus),
        by_classification=dict(by_classification),
        trade_signals_single_msg_solvable=single_msg_solvable_count,
        trade_signals_requires_context=requires_context_count,
        v1_pass_single_msg=v1_pass_single,
        v1_fail_single_msg=v1_fail_single,
        v2_pass_single_msg=v2_pass_single,
        v2_fail_single_msg=v2_fail_single,
        regressions=len(regressions),
        recoveries=len(recoveries),
        recovery_rate=recovery_rate,
        false_positives_on_chatter_v2=len(false_positives_on_chatter_v2),
        still_failing_context_dependent=len(still_failing_context_dependent),
        passed=passed,
    )

    return ValidationResult(
        summary=summary,
        regressions=regressions,
        recoveries=recoveries,
        still_failing_non_context=still_failing_non_context,
        still_failing_context_dependent=still_failing_context_dependent,
        false_positives_on_chatter_v2=false_positives_on_chatter_v2,
    )


# ---------------------------------------------------------------------------
# CLI helpers
# ---------------------------------------------------------------------------


def format_console_summary(result: ValidationResult) -> str:
    """Human-readable summary string suitable for terminal output."""
    s = result.summary
    lines: list[str] = []
    lines.append("==== Parser Validation Report ====")
    lines.append(f"total messages: {s.total}")
    lines.append(f"  · chatter:                {s.by_classification.get('chatter', 0)}")
    lines.append(f"  · ambiguous:              {s.by_classification.get('ambiguous', 0)}  (skipped)")
    lines.append(f"  · trade_signal:           {s.by_classification.get('trade_signal', 0)}")
    lines.append(f"      ├─ requires_context:    {s.trade_signals_requires_context}  (excluded from recovery/regression counts)")
    lines.append(f"      └─ single-msg solvable: {s.trade_signals_single_msg_solvable}")
    lines.append("")
    lines.append("v1 vs golden (single-msg solvable trade_signals only):")
    lines.append(f"  pass={s.v1_pass_single_msg}  fail={s.v1_fail_single_msg}")
    lines.append("v2 vs golden (single-msg solvable trade_signals only):")
    lines.append(f"  pass={s.v2_pass_single_msg}  fail={s.v2_fail_single_msg}")
    lines.append("")
    reg_marker = "✓" if s.regressions == 0 else "✗"
    lines.append(f"regressions:           {s.regressions}   {reg_marker} (must be 0)")
    lines.append(f"recoveries:           {s.recoveries:>2}")
    if s.recovery_rate is None:
        lines.append("recovery_rate:    EXEMPT  (parser_v2 is alias of stock_parser; constraint deferred until B2 lands)")
    else:
        rec_marker = "✓" if s.recovery_rate >= 0.20 else "✗"
        # Denominator = v1's failures on single-msg solvable trade_signals.
        # By construction, v1_fail_single_msg == recoveries + still_failing_non_context.
        denom = s.v1_fail_single_msg
        lines.append(
            f"recovery_rate:    {s.recoveries}/{denom} = {s.recovery_rate*100:.2f}%   "
            f"{rec_marker} (must be ≥ 20%)"
        )
    fp_marker = "✓" if s.false_positives_on_chatter_v2 == 0 else "✗"
    lines.append(f"false_positives_on_chatter_v2:    {s.false_positives_on_chatter_v2}   {fp_marker} (must be 0)")
    lines.append("")
    lines.append(f"still_failing_context_dependent:    {s.still_failing_context_dependent}  (informational)")
    lines.append("")
    overall = "PASS" if s.passed else "FAIL"
    lines.append(f"OVERALL: {overall}")
    return "\n".join(lines)


def write_report_json(result: ValidationResult, path: Path) -> None:
    """Serialize ValidationResult to JSON file (overwrite)."""
    data = {
        "summary": asdict(result.summary),
        "regressions": [asdict(d) for d in result.regressions],
        "recoveries": [asdict(d) for d in result.recoveries],
        "still_failing_non_context": [asdict(d) for d in result.still_failing_non_context],
        "still_failing_context_dependent": [asdict(d) for d in result.still_failing_context_dependent],
        "false_positives_on_chatter_v2": [asdict(d) for d in result.false_positives_on_chatter_v2],
    }
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2))


def main() -> int:
    """CLI entrypoint. Returns process exit code (0 = pass, 1 = fail)."""
    result = run_validation()
    print(format_console_summary(result))
    write_report_json(result, REPORT_PATH_DEFAULT)
    print(f"\nDetail report: {REPORT_PATH_DEFAULT}")
    return 0 if result.summary.passed else 1


if __name__ == "__main__":
    sys.exit(main())
