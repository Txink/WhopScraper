"""Normalize broker ``order_id`` values to a single decimal string key.

SDK values may be ``int``, ``str``, or ``numbers.Integral`` subclasses (e.g.
``numpy.int64``). ``float`` is avoided for large ids (> ~2^53) where ``str``
would be scientific / lossy — we still coerce integral floats with a warning.
"""

from __future__ import annotations

import logging
from decimal import Decimal, InvalidOperation
from numbers import Integral
from typing import Any

logger = logging.getLogger(__name__)


def normalize_broker_order_id(value: Any) -> str:
    """Return a stable non-empty string, or ``\"\"`` if missing / invalid."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return ""
    if isinstance(value, Integral):
        return str(int(value))
    if isinstance(value, str):
        s = value.strip()
        if not s or s.lower() in ("none", "null", "undefined"):
            return ""
        return s
    if isinstance(value, float):
        if not value.is_integer():
            logger.warning("broker order_id is non-integral float: %r", value)
            return str(value).strip()
        try:
            return str(int(value))
        except (OverflowError, ValueError):
            return str(value).strip()
    try:
        dec = Decimal(str(value))
        if dec != dec.to_integral_value():
            logger.warning("broker order_id is non-integral Decimal: %r", value)
            return str(dec).strip()
        return format(dec, "f").split(".")[0]
    except (InvalidOperation, TypeError, ValueError):
        pass
    out = str(value).strip()
    if out.lower() in ("none", "null"):
        return ""
    return out
