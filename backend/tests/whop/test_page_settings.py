import pytest

from app.whop.page_settings import (
    DEFAULT_OPTION_SETTINGS,
    DEFAULT_STOCK_SETTINGS,
    PageSettings,
    TickerConfig,
    page_settings_from_dict,
    page_settings_to_dict,
    position_size_to_fraction,
)


def test_default_stock_settings_shape():
    s = DEFAULT_STOCK_SETTINGS
    assert s.dedupe_processed_messages is True
    assert s.price_deviation_tolerance == 1.0
    assert s.tickers == {}


def test_default_option_settings_shape():
    s = DEFAULT_OPTION_SETTINGS
    assert s.dedupe_processed_messages is True
    assert s.price_deviation_tolerance == 5.0
    assert s.tickers is None


def test_round_trip_stock():
    src = PageSettings(
        dedupe_processed_messages=False,
        price_deviation_tolerance=0.7,
        tickers={"TSLL": TickerConfig(trade_quantity=2000)},
    )
    out = page_settings_from_dict(page_settings_to_dict(src), source="stock")
    assert out == src


def test_round_trip_option_drops_tickers():
    src = PageSettings(
        dedupe_processed_messages=True,
        price_deviation_tolerance=8.0,
        tickers=None,
    )
    d = page_settings_to_dict(src)
    assert "tickers" not in d
    out = page_settings_from_dict(d, source="option")
    assert out.tickers is None


def test_position_size_to_fraction_known():
    assert position_size_to_fraction(None) == 1.0
    assert position_size_to_fraction("常规仓") == 1.0
    assert position_size_to_fraction("半仓") == 0.5
    assert position_size_to_fraction("常规仓的一半") == 0.5
    assert position_size_to_fraction("常规一半") == 0.5
    assert position_size_to_fraction("常规的一半") == 0.5
    assert position_size_to_fraction("一半") == 0.5
    assert position_size_to_fraction("1/2") == 0.5
    assert position_size_to_fraction("1/3") == pytest.approx(1 / 3)
    assert position_size_to_fraction("2/3") == pytest.approx(2 / 3)
    assert position_size_to_fraction("1/4") == 0.25
    assert position_size_to_fraction("三分之一") == pytest.approx(1 / 3)
    assert position_size_to_fraction("三分之二") == pytest.approx(2 / 3)


def test_position_size_to_fraction_keywords():
    assert position_size_to_fraction("小仓位") == 0.5
    assert position_size_to_fraction("中仓位") == 1.0
    assert position_size_to_fraction("大仓位") == 1.5
    assert position_size_to_fraction("轻仓") == 0.5
    assert position_size_to_fraction("满仓") == 2.0


def test_position_size_to_fraction_unknown_falls_back_to_one(caplog):
    assert position_size_to_fraction("乱七八糟") == 1.0


def test_ticker_keys_uppercased_on_from_dict():
    raw = {
        "dedupe_processed_messages": True,
        "price_deviation_tolerance": 1.0,
        "tickers": {"tsll": {"trade_quantity": 100}},
    }
    out = page_settings_from_dict(raw, source="stock")
    assert "TSLL" in out.tickers
    assert "tsll" not in out.tickers
