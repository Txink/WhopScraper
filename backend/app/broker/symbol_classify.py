"""Classify a Longbridge position symbol as stock or option.

The trade API's ``stock_positions`` endpoint actually returns BOTH stock
and option holdings — the docs only describe the stock case, but in
practice option contracts the user holds also surface here, with symbols
in OCC-ish format (e.g. ``TSLA250117C300.US`` = TSLA call exp 2025-01-17
strike 300). The frontend wants them split into separate buckets so the
"期权" tab shows option contracts and the "正股" tab shows pure equity.

This module is the single place that knows the symbol shapes Longbridge
emits. Keep heuristics narrow — false positives are worse than false
negatives (a misclassified option as stock can be re-fetched via the
ticker; a misclassified stock as option can't).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

# Pattern: <TICKER><YYMMDD><C|P><STRIKE>.<MARKET>
# Examples Longbridge has been observed to emit:
#   "TSLA250117C300.US"     → TSLA, 2025-01-17, CALL, strike 300
#   "TSLA250117P150.US"     → TSLA, 2025-01-17, PUT,  strike 150
#   "AAPL241220C00250000.US" → AAPL, 2024-12-20, CALL, strike 250.00 (OCC zero-padded)
# Strike can be an integer or an OCC-style 8-digit zero-padded form where
# the last 3 digits are the decimal part.
_OPTION_RE = re.compile(
    r"""
    ^
    (?P<ticker>[A-Z]{1,6})
    (?P<yy>\d{2})(?P<mm>\d{2})(?P<dd>\d{2})
    (?P<cp>[CP])
    # Strike: any digit count.  OCC encodes 3 implicit decimal places, so
    # divide by 1000 to recover the dollar strike. Longbridge does NOT
    # consistently zero-pad — observed strikes range from 4 digits
    # (``7000`` = $7 on RXRX) through 6 digits (``300000`` = $300 on
    # TSLA) up to the canonical 8-digit OCC form (``00250000`` = $250 on
    # AAPL). Accept any width and rely on the ``\d{6}`` date block to
    # anchor the parse — stock tickers don't carry a YYMMDDCP suffix.
    (?P<strike>\d+)
    (?:\.(?P<market>[A-Z]+))?
    $
    """,
    re.VERBOSE | re.IGNORECASE,
)


@dataclass(frozen=True)
class OptionLeg:
    ticker: str
    expiry: str  # ISO date "2025-01-17"
    cp: Literal["CALL", "PUT"]
    strike: float


def parse_option_symbol(symbol: str) -> OptionLeg | None:
    """Return parsed OptionLeg if ``symbol`` is option OCC format, else None.

    Stock symbols ("TSLA.US", "700.HK") do not match the option pattern
    because they lack the YYMMDDCP block.
    """
    m = _OPTION_RE.match(symbol)
    if m is None:
        return None
    yy = int(m.group("yy"))
    mm = int(m.group("mm"))
    dd = int(m.group("dd"))
    # Pivot 2-digit year at 70 — anything below = 20xx, above = 19xx.
    # Options before 2070 fits; the broker won't emit 50-year-old contracts.
    full_year = 2000 + yy if yy < 70 else 1900 + yy
    if not (1 <= mm <= 12 and 1 <= dd <= 31):
        return None
    raw_strike = m.group("strike")
    # OCC convention: the last 3 digits of the strike block are implicit
    # decimal places, regardless of total digit count. "00250000" → 250.000
    # and "250000" → 250.000 both mean a $250 strike. Always divide by 1000
    # — the only case this breaks is a hypothetical sub-3-digit strike
    # ("100" would parse to $0.10), which Longbridge does not emit.
    strike = int(raw_strike) / 1000.0
    cp: Literal["CALL", "PUT"] = "CALL" if m.group("cp").upper() == "C" else "PUT"
    return OptionLeg(
        ticker=m.group("ticker").upper(),
        expiry=f"{full_year:04d}-{mm:02d}-{dd:02d}",
        cp=cp,
        strike=strike,
    )
