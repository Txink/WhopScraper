import pytest

from app.whop.page_settings import (
    DEFAULT_OPTION_SETTINGS,
    DEFAULT_STOCK_SETTINGS,
    PageSettings,
    TickerConfig,
    default_settings_for,
    page_settings_from_dict,
    page_settings_to_dict,
    position_size_to_fraction,
    sell_quantity_to_fraction,  # ← new
)


def test_default_stock_settings_shape():
    s = DEFAULT_STOCK_SETTINGS
    assert s.dedupe_processed_messages is True
    assert s.price_deviation_tolerance == 1.0
    assert s.block_historical_messages is False
    assert s.launch_headless is False
    assert s.tickers == {}
    assert s.option_buy_quantity_enabled is False
    assert s.option_buy_quantity is None
    assert s.option_total_price_limit_enabled is False
    assert s.option_total_price_limit is None


def test_default_option_settings_shape():
    s = DEFAULT_OPTION_SETTINGS
    assert s.dedupe_processed_messages is True
    assert s.price_deviation_tolerance == 5.0
    assert s.block_historical_messages is False
    assert s.launch_headless is False
    assert s.tickers is None
    assert s.option_buy_quantity_enabled is False
    assert s.option_buy_quantity is None
    assert s.option_total_price_limit_enabled is False
    assert s.option_total_price_limit is None


def test_round_trip_stock():
    src = PageSettings(
        dedupe_processed_messages=False,
        price_deviation_tolerance=0.7,
        block_historical_messages=True,
        launch_headless=True,
        tickers={"TSLL": TickerConfig(trade_quantity=2000)},
    )
    out = page_settings_from_dict(page_settings_to_dict(src), source="stock")
    assert out == src


def test_round_trip_option_drops_tickers():
    src = PageSettings(
        dedupe_processed_messages=True,
        price_deviation_tolerance=8.0,
        block_historical_messages=True,
        tickers=None,
        option_buy_quantity_enabled=True,
        option_buy_quantity=3,
        option_total_price_limit_enabled=True,
        option_total_price_limit=1200.0,
    )
    d = page_settings_to_dict(src)
    assert "tickers" not in d
    assert d["block_historical_messages"] is True
    out = page_settings_from_dict(d, source="option")
    assert out.tickers is None
    assert out.block_historical_messages is True


def test_default_stock_settings_block_historical_false():
    s = default_settings_for("stock")
    assert s.block_historical_messages is False


def test_default_option_settings_block_historical_false():
    s = default_settings_for("option")
    assert s.block_historical_messages is False


def test_to_dict_writes_block_historical_key():
    s = PageSettings(
        dedupe_processed_messages=True,
        price_deviation_tolerance=1.0,
        block_historical_messages=True,
        launch_headless=False,
        tickers={},
    )
    d = page_settings_to_dict(s)
    assert d["block_historical_messages"] is True
    assert "block_non_today_messages" not in d


def test_from_dict_reads_block_historical_key():
    d = {
        "dedupe_processed_messages": True,
        "price_deviation_tolerance": 1.0,
        "block_historical_messages": True,
        "launch_headless": False,
    }
    s = page_settings_from_dict(d, source="stock")
    assert s.block_historical_messages is True


def test_from_dict_missing_key_defaults_to_false():
    d = {
        "dedupe_processed_messages": True,
        "price_deviation_tolerance": 1.0,
        "launch_headless": False,
    }
    s = page_settings_from_dict(d, source="stock")
    assert s.block_historical_messages is False


def test_from_dict_ignores_legacy_block_non_today_key():
    """Legacy key in saved JSON must NOT silently activate the new field.

    Spec §3 'Why delete-and-add': users who consciously enabled the old
    'non-today' must re-opt-in to the tightened semantics through the UI.
    """
    d = {
        "dedupe_processed_messages": True,
        "price_deviation_tolerance": 1.0,
        "block_non_today_messages": True,  # legacy
        "launch_headless": False,
    }
    s = page_settings_from_dict(d, source="stock")
    assert s.block_historical_messages is False


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
    assert position_size_to_fraction("重仓") == 1.5
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


def test_sell_quantity_to_fraction_known():
    assert sell_quantity_to_fraction(None) == 1.0
    assert sell_quantity_to_fraction("") == 1.0
    assert sell_quantity_to_fraction("1/2") == 0.5
    assert sell_quantity_to_fraction("1/3") == pytest.approx(1 / 3)
    assert sell_quantity_to_fraction("1/4") == 0.25
    assert sell_quantity_to_fraction("2/3") == pytest.approx(2 / 3)
    assert sell_quantity_to_fraction("3/4") == 0.75
    assert sell_quantity_to_fraction("全部") == 1.0
    assert sell_quantity_to_fraction("剩下") == 1.0
    assert sell_quantity_to_fraction("剩下一半") == 0.5  # decision 5: same as 1/2


def test_sell_quantity_to_fraction_strips_whitespace():
    assert sell_quantity_to_fraction("  1/2  ") == 0.5
    assert sell_quantity_to_fraction("\t全部\n") == 1.0


def test_sell_quantity_to_fraction_unknown_returns_one(caplog):
    import logging
    with caplog.at_level(logging.WARNING, logger="app.whop.page_settings"):
        assert sell_quantity_to_fraction("一点点") == 1.0
    assert any("unrecognized sell_quantity" in r.getMessage() for r in caplog.records)


def test_default_stock_settings_parser_version_v1():
    assert DEFAULT_STOCK_SETTINGS.parser_version == "v1"


def test_default_option_settings_parser_version_v1():
    assert DEFAULT_OPTION_SETTINGS.parser_version == "v1"


def test_to_dict_writes_parser_version():
    s = PageSettings(
        dedupe_processed_messages=True,
        price_deviation_tolerance=1.0,
        block_historical_messages=False,
        launch_headless=False,
        tickers={},
        parser_version="v2",
    )
    d = page_settings_to_dict(s)
    assert d["parser_version"] == "v2"


def test_from_dict_reads_parser_version_v2():
    d = {
        "dedupe_processed_messages": True,
        "price_deviation_tolerance": 1.0,
        "block_historical_messages": False,
        "launch_headless": False,
        "parser_version": "v2",
    }
    s = page_settings_from_dict(d, source="stock")
    assert s.parser_version == "v2"


def test_from_dict_missing_parser_version_defaults_to_v1():
    """Backward compat: settings JSON written before this field existed must
    deserialize cleanly with parser_version='v1'."""
    d = {
        "dedupe_processed_messages": True,
        "price_deviation_tolerance": 1.0,
        "block_historical_messages": False,
        "launch_headless": False,
    }
    s = page_settings_from_dict(d, source="stock")
    assert s.parser_version == "v1"


def test_from_dict_unknown_parser_version_falls_back_to_v1():
    """Sanitization: any value other than 'v2' degrades to 'v1' so a corrupted
    or future-unknown saved value cannot crash the parser dispatcher."""
    d = {
        "dedupe_processed_messages": True,
        "price_deviation_tolerance": 1.0,
        "block_historical_messages": False,
        "launch_headless": False,
        "parser_version": "v3",
    }
    s = page_settings_from_dict(d, source="stock")
    assert s.parser_version == "v1"


def test_round_trip_preserves_parser_version():
    src = PageSettings(
        dedupe_processed_messages=False,
        price_deviation_tolerance=0.7,
        block_historical_messages=True,
        launch_headless=True,
        tickers={"TSLL": TickerConfig(trade_quantity=2000)},
        parser_version="v2",
    )
    out = page_settings_from_dict(page_settings_to_dict(src), source="stock")
    assert out == src
    assert out.parser_version == "v2"
