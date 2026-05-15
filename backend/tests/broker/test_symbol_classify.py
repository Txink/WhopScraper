"""Tests for app.broker.symbol_classify — OCC option-symbol parser."""

from __future__ import annotations

import pytest

from app.broker.symbol_classify import OptionLeg, parse_option_symbol


class TestParseOptionSymbol:
    @pytest.mark.parametrize(
        "symbol,expected",
        [
            (
                # 4-digit unpadded strike: 7000 / 1000 = $7.00
                "RXRX260618C7000",
                OptionLeg(ticker="RXRX", expiry="2026-06-18", cp="CALL", strike=7.0),
            ),
            (
                # 6-digit strike: 300000 → 300.000
                "TSLA250117C300000.US",
                OptionLeg(ticker="TSLA", expiry="2025-01-17", cp="CALL", strike=300.0),
            ),
            (
                "TSLA250117P150000.US",
                OptionLeg(ticker="TSLA", expiry="2025-01-17", cp="PUT", strike=150.0),
            ),
            (
                # 8-digit OCC zero-padded: 00250000 → 250.000
                "AAPL241220C00250000.US",
                OptionLeg(ticker="AAPL", expiry="2024-12-20", cp="CALL", strike=250.0),
            ),
            (
                # 8-digit strike with fractional part: 00100500 → 100.500
                "NVDA260619P00100500.US",
                OptionLeg(ticker="NVDA", expiry="2026-06-19", cp="PUT", strike=100.5),
            ),
            (
                # Fractional 3-digit strike: 500 / 1000 = $0.50 (penny option)
                "PENNY260101C500",
                OptionLeg(ticker="PENNY", expiry="2026-01-01", cp="CALL", strike=0.5),
            ),
        ],
    )
    def test_parses_option_symbols(self, symbol: str, expected: OptionLeg) -> None:
        assert parse_option_symbol(symbol) == expected

    @pytest.mark.parametrize(
        "symbol",
        [
            "TSLA.US",       # plain stock
            "700.HK",        # plain stock (numeric HK ticker)
            "BABA.US",       # plain stock
            "TSLL.US",       # plain stock with double L
            "",              # empty
            "INVALID",       # nonsense
            "TSLA13xxx.US",  # not a valid date block
            "ABC241350C300000.US",  # month 13 — invalid
        ],
    )
    def test_rejects_non_option_symbols(self, symbol: str) -> None:
        assert parse_option_symbol(symbol) is None
