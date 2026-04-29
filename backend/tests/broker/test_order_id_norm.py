"""Tests for ``normalize_broker_order_id``."""

from __future__ import annotations

import pytest

from app.broker.order_id_norm import normalize_broker_order_id


def test_normalize_int_large() -> None:
    oid = 1233811935523246080
    assert normalize_broker_order_id(oid) == "1233811935523246080"


def test_normalize_str_digits() -> None:
    assert normalize_broker_order_id("  1233811935523246080  ") == "1233811935523246080"


def test_normalize_empty() -> None:
    assert normalize_broker_order_id(None) == ""
    assert normalize_broker_order_id("") == ""
    assert normalize_broker_order_id("null") == ""


@pytest.mark.parametrize(
    "raw, expected",
    [
        (1.233811935523246e18, "1233811935523246080"),  # exact float for this int
    ],
)
def test_normalize_integral_float(raw: float, expected: str) -> None:
    assert normalize_broker_order_id(raw) == expected


def test_normalize_numpy_int64_if_available() -> None:
    np = pytest.importorskip("numpy")
    assert normalize_broker_order_id(np.int64(1233811935523246080)) == "1233811935523246080"
