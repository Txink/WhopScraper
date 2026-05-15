"""LongPort broker configuration dataclass and loader.

Multi-account-era shape: instead of paper/real flags, the config carries
the active OAuth ``account_id`` (= client_id). ``LongPortClient`` uses
``OAuthBuilder(account_id).build()`` to retrieve the cached token and
construct a SDK ``Config`` via ``Config.from_oauth(...)``.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.broker.oauth import is_authorized
from app.broker.runtime_settings import LongPortRuntimeSettings
from app.core.config import Settings


@dataclass(frozen=True)
class LongPortConfig:
    """Immutable config for ``LongPortClient``.

    Holds the OAuth ``account_id`` of the active account + runtime feature
    flags. The label is carried through for log-friendly identification.
    No SDK types leak here.
    """

    account_id: str
    label: str = ""
    region: str = "cn"
    auto_trade: bool = True
    dry_run: bool = True
    max_option_total_price: float = 500.0
    max_option_quantity: int = 3
    price_deviation_tolerance: float = 5.0
    stock_price_deviation_tolerance: float = 1.0


def load_longport_config_from_runtime(
    runtime: LongPortRuntimeSettings,
    *,
    settings: Settings,
) -> LongPortConfig:
    """Build LongPortConfig from persisted runtime settings + risk defaults.

    Raises ``ValueError`` if there is no active account, or if the active
    account's OAuth token cache is missing. Callers should catch this and
    fall back to ``NoopBrokerClient``.
    """
    active = runtime.active_account
    if active is None:
        raise ValueError(
            "No active LongBridge account — add one via the UI settings "
            "dialog (登录长桥)."
        )
    if not is_authorized(active.account_id):
        raise ValueError(
            f"LongBridge account {active.label!r} is not authorized — "
            "complete the OAuth login flow via the UI settings dialog."
        )
    return LongPortConfig(
        account_id=active.account_id,
        label=active.label,
        region=runtime.region,
        auto_trade=runtime.auto_trade,
        dry_run=runtime.dry_run,
        max_option_total_price=settings.max_option_total_price,
        max_option_quantity=settings.max_option_quantity,
        price_deviation_tolerance=settings.price_deviation_tolerance,
        stock_price_deviation_tolerance=settings.stock_price_deviation_tolerance,
    )
