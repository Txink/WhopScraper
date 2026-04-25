"""LongPort broker configuration dataclass and loader.

``load_longport_config()`` reads from the application ``Settings`` singleton
(``app.core.config.get_settings()``) and assembles a frozen ``LongPortConfig``.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class LongPortConfig:
    """Immutable config for ``LongPortClient``.

    All fields are plain Python values — no SDK types leak here.
    """

    mode: Literal["paper", "real"]
    app_key: str
    app_secret: str
    access_token: str
    region: str = "cn"
    auto_trade: bool = True
    dry_run: bool = True
    max_option_total_price: float = 500.0
    max_option_quantity: int = 3
    price_deviation_tolerance: float = 5.0
    stock_price_deviation_tolerance: float = 1.0


def load_longport_config() -> LongPortConfig:
    """Build ``LongPortConfig`` from core ``Settings`` / env.

    Selects ``paper_*`` or ``real_*`` credentials based on ``mode``.
    Raises ``ValueError`` if required credentials for the selected mode
    are missing or empty.
    """
    from app.core.config import get_settings  # local import to allow test patching

    s = get_settings()
    mode = s.longport_mode.lower()

    if mode not in ("paper", "real"):
        raise ValueError(
            f"LONGPORT_MODE must be 'paper' or 'real', got: {mode!r}"
        )

    if mode == "paper":
        app_key = s.longport_paper_app_key
        app_secret = s.longport_paper_app_secret
        access_token = s.longport_paper_access_token
        _prefix = "LONGPORT_PAPER"
    else:
        app_key = s.longport_real_app_key
        app_secret = s.longport_real_app_secret
        access_token = s.longport_real_access_token
        _prefix = "LONGPORT_REAL"

    for field_name, value in (
        (f"{_prefix}_APP_KEY", app_key),
        (f"{_prefix}_APP_SECRET", app_secret),
        (f"{_prefix}_ACCESS_TOKEN", access_token),
    ):
        if not value:
            raise ValueError(
                f"{field_name} is empty but mode={mode!r}. "
                "Set the variable in your .env file."
            )

    return LongPortConfig(
        mode=mode,  # type: ignore[arg-type]
        app_key=app_key,
        app_secret=app_secret,
        access_token=access_token,
        region=s.longport_region,
        auto_trade=s.longport_auto_trade,
        dry_run=s.longport_dry_run,
        max_option_total_price=s.max_option_total_price,
        max_option_quantity=s.max_option_quantity,
        price_deviation_tolerance=s.price_deviation_tolerance,
        stock_price_deviation_tolerance=s.stock_price_deviation_tolerance,
    )
