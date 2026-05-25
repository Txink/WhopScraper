"""Tests for /api/quote and /api/candlesticks endpoints."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.http import build_http_router
from app.broker.runtime_settings import LongPortRuntimeStore
from app.core.config import Settings, get_settings
from app.core.event_bus import EventBus
from tests.broker._fakes import FakeBrokerClient

_TOKEN = "test-token-quotes"


@pytest.fixture
def make_app(
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> tuple[FastAPI, FakeBrokerClient]:
    broker = FakeBrokerClient()
    settings = Settings(app_token=_TOKEN)
    bus = EventBus()
    runtime_store = LongPortRuntimeStore(settings_file=tmp_path / "lp.json")
    app = FastAPI()
    app.include_router(
        build_http_router(
            session_factory=session_factory,
            broker=broker,
            settings=settings,
            bus=bus,
            longport_runtime=runtime_store,
        )
    )
    app.dependency_overrides[get_settings] = lambda: settings
    return app, broker


@pytest.fixture
def client_and_broker(
    make_app: tuple[FastAPI, FakeBrokerClient],
) -> tuple[TestClient, FakeBrokerClient]:
    app, broker = make_app
    return TestClient(app, raise_server_exceptions=True), broker


# ---------------------------------------------------------------------------
# /api/quote
# ---------------------------------------------------------------------------


def test_quote_single_symbol(
    client_and_broker: tuple[TestClient, FakeBrokerClient],
) -> None:
    client, broker = client_and_broker
    broker.quote_by_symbol = {"TSLA.US": 248.50}
    resp = client.get("/api/quote", params={"token": _TOKEN, "symbols": "TSLA.US"})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["quotes"]) == 1
    assert data["quotes"][0]["symbol"] == "TSLA.US"
    assert data["quotes"][0]["last_done"] == 248.50


def test_quote_multiple_symbols(
    client_and_broker: tuple[TestClient, FakeBrokerClient],
) -> None:
    client, broker = client_and_broker
    broker.quote_by_symbol = {"TSLA.US": 248.50, "NVDA.US": 123.00}
    resp = client.get(
        "/api/quote", params={"token": _TOKEN, "symbols": "TSLA.US,NVDA.US"},
    )
    assert resp.status_code == 200
    syms = [q["symbol"] for q in resp.json()["quotes"]]
    assert syms == ["TSLA.US", "NVDA.US"]


def test_quote_strips_whitespace(
    client_and_broker: tuple[TestClient, FakeBrokerClient],
) -> None:
    client, broker = client_and_broker
    broker.quote_by_symbol = {"TSLA.US": 100.0, "NVDA.US": 50.0}
    resp = client.get(
        "/api/quote", params={"token": _TOKEN, "symbols": " TSLA.US , NVDA.US "},
    )
    assert resp.status_code == 200
    assert len(resp.json()["quotes"]) == 2


def test_quote_empty_symbols_returns_400(
    client_and_broker: tuple[TestClient, FakeBrokerClient],
) -> None:
    client, _ = client_and_broker
    resp = client.get("/api/quote", params={"token": _TOKEN, "symbols": ""})
    assert resp.status_code == 400


def test_quote_change_pct_calculation(
    client_and_broker: tuple[TestClient, FakeBrokerClient],
) -> None:
    """When the broker returns prev_close, the endpoint computes change %."""
    client, broker = client_and_broker
    # FakeBrokerClient only stores last_done, so monkey-patch get_quote
    def fake_quote(symbols: list[str]) -> dict[str, dict[str, float]]:
        return {
            "TSLA.US": {
                "last_done": 105.0, "prev_close": 100.0,
                "open": 100.5, "high": 106.0, "low": 99.5,
                "volume": 1000, "turnover": 105000.0,
            }
        }
    broker.get_quote = fake_quote  # type: ignore[assignment]

    resp = client.get("/api/quote", params={"token": _TOKEN, "symbols": "TSLA.US"})
    data = resp.json()["quotes"][0]
    assert data["change"] == pytest.approx(5.0)
    assert data["change_pct"] == pytest.approx(5.0)
    assert data["prev_close"] == 100.0


def test_quote_endpoint_forwards_every_quote_out_field(
    client_and_broker: tuple[TestClient, FakeBrokerClient],
) -> None:
    """Lock in that the broker dict → /api/quote response path doesn't
    silently drop fields.

    When a new field is added to ``QuoteOut`` (in
    ``app/api/schemas.py``), the assertion below will fail until the
    new field is also added to the ``exhaustive`` dict — at which
    point the loop verifies every field reaches the JSON response.

    Regression guard for the bug fixed in 5dfcd02 where
    ``quote_endpoint`` hand-marshalled fields one-by-one and silently
    dropped a newly added ``trading_day`` field, producing wrong
    Day P/L on holidays.
    """
    from app.api.schemas import QuoteOut

    client, broker = client_and_broker
    exhaustive: dict[str, object] = {
        "last_done": 1.0,
        "prev_close": 2.0,
        "today_close": 3.0,
        "open": 4.0,
        "high": 5.0,
        "low": 6.0,
        "volume": 7,
        "turnover": 8.0,
        "change": 9.0,
        "change_pct": 10.0,
        "trade_session": "post",
        "trading_day": "2026-05-22",
    }

    # If this fails, ``QuoteOut`` has new fields not covered here —
    # add them to ``exhaustive`` with distinct test values, then the
    # for-loop below will assert they are forwarded end-to-end.
    expected_fields = set(QuoteOut.model_fields) - {"symbol"}
    missing = expected_fields - set(exhaustive)
    assert not missing, (
        f"QuoteOut has new fields not covered by this test: {missing}. "
        f"Add them to the ``exhaustive`` dict with distinct values."
    )

    def fake_quote(symbols: list[str]) -> dict[str, dict[str, object]]:
        return {"TSLA.US": exhaustive.copy()}

    broker.get_quote = fake_quote  # type: ignore[assignment]

    resp = client.get("/api/quote", params={"token": _TOKEN, "symbols": "TSLA.US"})
    assert resp.status_code == 200
    data = resp.json()["quotes"][0]
    assert data["symbol"] == "TSLA.US"
    for field, value in exhaustive.items():
        assert data[field] == value, f"field {field!r} dropped or mangled by endpoint"


# ---------------------------------------------------------------------------
# /api/candlesticks
# ---------------------------------------------------------------------------


def test_candlesticks_today_default_5min_regular(
    client_and_broker: tuple[TestClient, FakeBrokerClient],
) -> None:
    """Default today view: 5-min bars, regular session = 78 bars."""
    client, _ = client_and_broker
    resp = client.get(
        "/api/candlesticks",
        params={"token": _TOKEN, "symbol": "TSLA.US", "period": "today"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["period"] == "today"
    assert len(data["bars"]) == 78
    bar = data["bars"][0]
    assert {"timestamp", "open", "high", "low", "close", "volume"} <= set(bar.keys())


@pytest.mark.parametrize(
    "granularity,sessions,expected",
    [
        # Regular session counts (6.5h)
        ("5min", "regular",  78),
        ("3min", "regular", 130),
        ("2min", "regular", 195),
        # All sessions = full 24h trading day (pre + regular + post +
        # overnight = 5.5 + 6.5 + 4 + 8). The endpoint caps min_1 at the
        # LongBridge per-call limit (1000), but min_2/3/5 carry the
        # exact 24h bar count: 1440/2, 1440/3, 1440/5 = 720/480/288.
        ("5min", "all", 288),
        ("3min", "all", 480),
        ("2min", "all", 720),
    ],
)
def test_candlesticks_today_granularity_and_sessions(
    client_and_broker: tuple[TestClient, FakeBrokerClient],
    granularity: str, sessions: str, expected: int,
) -> None:
    """Today supports 2/3/5min granularity and regular vs all sessions."""
    client, _ = client_and_broker
    resp = client.get(
        "/api/candlesticks",
        params={
            "token": _TOKEN, "symbol": "TSLA.US", "period": "today",
            "granularity": granularity, "sessions": sessions,
        },
    )
    assert resp.status_code == 200
    assert len(resp.json()["bars"]) == expected


def test_candlesticks_today_invalid_granularity(
    client_and_broker: tuple[TestClient, FakeBrokerClient],
) -> None:
    client, _ = client_and_broker
    resp = client.get(
        "/api/candlesticks",
        params={"token": _TOKEN, "symbol": "TSLA.US", "period": "today",
                "granularity": "1h"},
    )
    assert resp.status_code == 400


def test_candlesticks_today_minute_line_granularity(
    client_and_broker: tuple[TestClient, FakeBrokerClient],
) -> None:
    """分时 = Min_1 → 390 bars regular session, 1000 bars all sessions
    (capped at the LongBridge per-call limit, since a full 24h would be
    1440 bars)."""
    client, _ = client_and_broker
    reg = client.get(
        "/api/candlesticks",
        params={"token": _TOKEN, "symbol": "TSLA.US", "period": "today",
                "granularity": "分时", "sessions": "regular"},
    ).json()
    all_ = client.get(
        "/api/candlesticks",
        params={"token": _TOKEN, "symbol": "TSLA.US", "period": "today",
                "granularity": "分时", "sessions": "all"},
    ).json()
    assert len(reg["bars"]) == 390
    assert len(all_["bars"]) == 1000


@pytest.mark.parametrize("sess", ["pre", "post", "overnight"])
def test_candlesticks_today_individual_sessions_fetch_all(
    client_and_broker: tuple[TestClient, FakeBrokerClient],
    sess: str,
) -> None:
    """For session=pre/post/overnight backend fetches ALL bars (24h, capped
    at the LongBridge per-call limit of 1000 for min_1) and lets the client
    filter by ET time. We assert it returns the All-count rather than 400
    / empty."""
    client, _ = client_and_broker
    resp = client.get(
        "/api/candlesticks",
        params={"token": _TOKEN, "symbol": "TSLA.US", "period": "today",
                "granularity": "分时", "sessions": sess},
    )
    assert resp.status_code == 200
    assert len(resp.json()["bars"]) == 1000  # All-session count (min_1 cap)


@pytest.mark.parametrize(
    "period,expected_bars",
    [
        # 5/7-day views remain: multi-day intraday stitched at 5-min granularity.
        ("5", 5 * 78),
        ("7", 7 * 78),
        # "30" is the legacy period for OptionCard miniline (30 daily candles).
        ("30", 30),
        # New K-line periods replace 15/60/90 with fixed batches.
        ("day", 250),
        ("week", 200),
        ("month", 120),
        ("year", 30),
    ],
)
def test_candlesticks_periods_bar_counts(
    client_and_broker: tuple[TestClient, FakeBrokerClient],
    period: str,
    expected_bars: int,
) -> None:
    """5/7 stitch 5-min intraday across days; day/week/month/year are
    candlestick batches the chart pans/zooms within."""
    client, _ = client_and_broker
    resp = client.get(
        "/api/candlesticks",
        params={"token": _TOKEN, "symbol": "TSLA.US", "period": period},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["period"] == period
    assert len(data["bars"]) == expected_bars


@pytest.mark.parametrize("period", ["15", "60", "90"])
def test_candlesticks_removed_periods_return_400(
    client_and_broker: tuple[TestClient, FakeBrokerClient],
    period: str,
) -> None:
    """The old day-count periods are no longer accepted — UI uses
    day/week/month/year instead."""
    client, _ = client_and_broker
    resp = client.get(
        "/api/candlesticks",
        params={"token": _TOKEN, "symbol": "TSLA.US", "period": period},
    )
    assert resp.status_code == 400


def test_candlesticks_invalid_period(
    client_and_broker: tuple[TestClient, FakeBrokerClient],
) -> None:
    client, _ = client_and_broker
    resp = client.get(
        "/api/candlesticks",
        params={"token": _TOKEN, "symbol": "TSLA.US", "period": "monthly"},
    )
    assert resp.status_code == 400


def test_candlesticks_period_out_of_range(
    client_and_broker: tuple[TestClient, FakeBrokerClient],
) -> None:
    client, _ = client_and_broker
    resp = client.get(
        "/api/candlesticks",
        params={"token": _TOKEN, "symbol": "TSLA.US", "period": "9999"},
    )
    assert resp.status_code == 400


def test_candlesticks_default_period_is_today(
    client_and_broker: tuple[TestClient, FakeBrokerClient],
) -> None:
    client, _ = client_and_broker
    resp = client.get(
        "/api/candlesticks",
        params={"token": _TOKEN, "symbol": "TSLA.US"},
    )
    assert resp.status_code == 200
    assert resp.json()["period"] == "today"


def test_candlesticks_broker_override(
    client_and_broker: tuple[TestClient, FakeBrokerClient],
) -> None:
    """If the broker has a custom set of bars for a symbol, they win."""
    client, broker = client_and_broker
    custom_bars = [
        {
            "timestamp": "2026-05-14T10:00:00",
            "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5,
            "volume": 1000, "turnover": 100500.0,
        },
        {
            "timestamp": "2026-05-14T10:05:00",
            "open": 100.5, "high": 102.0, "low": 100.0, "close": 101.5,
            "volume": 2000, "turnover": 203000.0,
        },
    ]
    broker.candlesticks_by_symbol = {"TSLA.US": custom_bars}  # type: ignore[attr-defined]
    resp = client.get(
        "/api/candlesticks",
        params={"token": _TOKEN, "symbol": "TSLA.US", "period": "today"},
    )
    bars = resp.json()["bars"]
    assert len(bars) == 2
    assert bars[0]["open"] == 100.0
    assert bars[1]["close"] == 101.5
