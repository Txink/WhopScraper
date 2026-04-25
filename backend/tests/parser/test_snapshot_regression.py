"""Snapshot regression: new parser vs gold / old parser output.

Data files (relative to project root, one level above ``backend/``):

* ``data/stock_parsed_message.json``  — 34 TSLL gold records
  Fields: raw_message, ticker, instruction_type, message_id, price, …

* ``data/parsed_message.json``        — 225 option gold records
  Shape: [{origin: {domID, content, timestamp, position, history},
           parsed: {ticker, option_type, strike, expiry, symbol, …} | None,
           status: "✅"|"❌"}]

Stock test (Approach A — gold data already parsed)
---------------------------------------------------
Compare ticker detection only.  Regression = old had ticker, new returns None.
Acceptable threshold: ≤15 % of records that had a ticker.

Option test (Approach A, scoped)
---------------------------------
We only test ``position == "first"`` records whose gold instruction_type is
``"BUY"``.  SELL / CLOSE / MODIFY records in the gold set were resolved via
context (watchlist / history chain) which is outside the scope of the stateless
``option_parser.parse()``.  Regression threshold: ≤15 % of BUY-first records.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from app.parser import option_parser, stock_parser

# ---------------------------------------------------------------------------
# Paths — data files live one level above ``backend/``
# ---------------------------------------------------------------------------

_BACKEND_DIR = Path(__file__).resolve().parents[2]  # backend/
_PROJECT_ROOT = _BACKEND_DIR.parent  # signal-station/

STOCK_DATA = _PROJECT_ROOT / "data" / "stock_parsed_message.json"
OPTION_DATA = _PROJECT_ROOT / "data" / "parsed_message.json"


# ---------------------------------------------------------------------------
# Stock snapshot regression
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not STOCK_DATA.is_file(), reason="stock snapshot data not present")
def test_stock_parser_snapshot_regression() -> None:
    """New stock parser must not regress on TSLL gold records."""
    records: list[Any] = json.loads(STOCK_DATA.read_text(encoding="utf-8"))

    match = 0
    regression = 0
    improvement = 0
    divergence = 0
    regression_samples: list[dict[str, Any]] = []
    itype_divergences: list[dict[str, Any]] = []

    for rec in records:
        raw: str = rec.get("raw_message") or rec.get("content") or ""
        old_ticker: str | None = rec.get("ticker")
        old_itype: str | None = rec.get("instruction_type")
        msg_id: str = rec.get("message_id", "unknown")

        new_inst = stock_parser.parse(raw, message_id=msg_id)
        new_ticker = new_inst.ticker if new_inst else None
        new_itype = new_inst.instruction_type.name if new_inst else None

        old_has = bool(old_ticker)
        new_has = bool(new_ticker)

        if old_has and not new_has:
            regression += 1
            if len(regression_samples) < 10:
                regression_samples.append(
                    {"raw": raw, "old_ticker": old_ticker, "old_itype": old_itype}
                )
        elif not old_has and new_has:
            improvement += 1
        elif old_has and new_has and old_ticker != new_ticker:
            divergence += 1
        else:
            match += 1

        # Track instruction_type mismatches separately (informational)
        if old_has and new_has and old_ticker == new_ticker and old_itype != new_itype:
            itype_divergences.append(
                {"raw": raw, "old_itype": old_itype, "new_itype": new_itype}
            )

    total = len(records)
    print(
        f"\nStock snapshot: total={total} match={match} "
        f"regression={regression} improvement={improvement} "
        f"divergence={divergence} itype_mismatch={len(itype_divergences)}"
    )

    if regression_samples:
        print("Regression samples (new parser returned None):")
        for s in regression_samples:
            raw_preview = str(s["raw"])[:80]
            print(f"  old={s['old_ticker']} [{s['old_itype']}] :: {raw_preview}")

    if itype_divergences:
        print("Instruction-type divergences (ticker matched, type differed):")
        for d in itype_divergences:
            raw_preview = str(d["raw"])[:80]
            print(f"  old={d['old_itype']} new={d['new_itype']} :: {raw_preview}")

    # Acceptance threshold: regression rate must not exceed 15 % of records
    # that had a gold ticker.
    tickerable = match + regression + divergence
    if tickerable > 0:
        regression_rate = regression / tickerable
        assert regression_rate <= 0.15, (
            f"Stock regression rate {regression_rate:.1%} exceeds 15% "
            f"(absolute: {regression}/{tickerable}). "
            "See regression_samples printed above."
        )


# ---------------------------------------------------------------------------
# Option snapshot regression
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not OPTION_DATA.is_file(), reason="option snapshot data not present")
def test_option_parser_snapshot_regression() -> None:
    """New option parser must not regress on standalone BUY gold records.

    Scope: ``position == "first"`` records whose gold instruction_type is
    ``"BUY"``.  Context-dependent SELL/CLOSE/MODIFY records are excluded because
    they require the context-resolver tier (watchlist / history) which is outside
    the scope of the stateless ``option_parser.parse()``.
    """
    all_records: list[Any] = json.loads(OPTION_DATA.read_text(encoding="utf-8"))

    # Only consider first-in-series BUY records — these are fully self-contained
    buy_first: list[Any] = [
        rec
        for rec in all_records
        if rec.get("parsed")
        and isinstance(rec.get("origin"), dict)
        and rec["origin"].get("position") == "first"
        and isinstance(rec.get("parsed"), dict)
        and rec["parsed"].get("instruction_type") == "BUY"
    ]

    match = 0
    regression = 0
    improvement = 0
    divergence = 0
    regression_samples: list[dict[str, Any]] = []

    for rec in buy_first:
        origin: dict[str, Any] = rec["origin"]
        parsed: dict[str, Any] = rec["parsed"]

        content: str = origin["content"]
        ts_str: str = origin.get("timestamp", "")
        try:
            posted_at = datetime.fromisoformat(ts_str.split(".")[0])
        except ValueError:
            posted_at = datetime.now()

        msg_id: str = origin.get("domID", "unknown")
        old_ticker: str | None = parsed.get("ticker")
        old_symbol: str | None = parsed.get("symbol")

        new_inst = option_parser.parse(
            content, message_id=msg_id, message_posted_at=posted_at
        )
        new_ticker = new_inst.ticker if new_inst else None

        old_has = bool(old_ticker)
        new_has = bool(new_ticker)

        if old_has and not new_has:
            regression += 1
            if len(regression_samples) < 10:
                regression_samples.append(
                    {
                        "content": content,
                        "old_ticker": old_ticker,
                        "old_symbol": old_symbol,
                    }
                )
        elif not old_has and new_has:
            improvement += 1
        elif old_has and new_has and old_ticker != new_ticker:
            divergence += 1
        else:
            match += 1

    total_buy_first = len(buy_first)
    excluded_context_dependent = len(all_records) - total_buy_first
    print(
        f"\nOption snapshot: total_records={len(all_records)} "
        f"scope=buy_first({total_buy_first}) "
        f"excluded_context_dependent={excluded_context_dependent}"
    )
    print(
        f"  match={match} regression={regression} "
        f"improvement={improvement} divergence={divergence}"
    )

    if regression_samples:
        print("Regression samples (new parser returned None):")
        for s in regression_samples:
            content_preview = str(s["content"])[:80]
            print(
                f"  old_ticker={s['old_ticker']} "
                f"old_symbol={s['old_symbol']} :: {content_preview}"
            )

    # Acceptance threshold: regression rate must not exceed 15 % of BUY-first
    # records that had a gold ticker.
    tickerable = match + regression + divergence
    if tickerable > 0:
        regression_rate = regression / tickerable
        assert regression_rate <= 0.15, (
            f"Option BUY regression rate {regression_rate:.1%} exceeds 15% "
            f"(absolute: {regression}/{tickerable}). "
            "See regression_samples printed above."
        )
