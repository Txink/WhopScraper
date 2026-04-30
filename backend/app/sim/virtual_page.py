"""Virtual Whop page registered for simulator tasks.

The trader's gate ① (whitelist) and qty resolution path both consult
``WhopRegistry.get_settings_for_url(task.message.url)``. Sim-injected tasks
carry ``url="sim://scenarios"`` — without a registered page entry the
trader sees ``None`` page settings, falls into the orphan-stock branch,
and SKIPs because parsed ``instruction.quantity`` is None for
position-size signals like "常规仓的一半".

We register a virtual entry on startup with a curated ticker → trade_quantity
map sized so position_size descriptors yield the same per-side qtys the
recorded scenarios use:

  * CONL trade_quantity=20 → "一半" * 20 = 10  (matches buy scenarios)
  * TSLL trade_quantity=200 → "一半" * 200 = 100  (matches sell scenarios)
  * IREN trade_quantity=20 → 10                  (extra ticker for variety)

Tickers are upper-cased to match trader's lookup convention.
"""

from __future__ import annotations

from app.whop.page_settings import PageSettings, TickerConfig
from app.whop.registry import WhopRegistry

#: Stable URL the sim runner uses on every synthetic Message. Trader
#: branches on this to fake the broker.submit_order call (see
#: ``app.broker.trader``).
SIM_PAGE_URL = "sim://scenarios"


def _sim_settings() -> PageSettings:
    return PageSettings(
        dedupe_processed_messages=False,
        price_deviation_tolerance=100.0,  # never trip on sim prices
        block_historical_messages=False,
        launch_headless=False,
        tickers={
            "CONL": TickerConfig(trade_quantity=20),
            "TSLL": TickerConfig(trade_quantity=200),
            "IREN": TickerConfig(trade_quantity=20),
            "AAPL": TickerConfig(trade_quantity=10),
        },
    )


def register_sim_page(registry: WhopRegistry) -> None:
    """(Re-)register the sim virtual page, replacing any prior entry.

    Always overwrites: the page config lives in code (this module) and we
    don't want a stale on-disk copy from an earlier release silently
    overriding it. Older builds also accidentally persisted a sim entry
    via the API path; clearing on every startup self-heals that.
    """
    # If a prior entry exists for this URL, drop it from the in-memory
    # index. We bypass remove_page() since that does FK / listener cleanup
    # we don't need for a virtual entry that never had either.
    canon = SIM_PAGE_URL  # _canonicalize matches the URL as-is for sim://
    stale_ids = [
        eid for eid, entry in registry._entries.items()
        if entry.url == canon
    ]
    for eid in stale_ids:
        del registry._entries[eid]
    registry.register_virtual_page(
        url=SIM_PAGE_URL,
        source="stock",
        name="Simulator (virtual)",
        settings=_sim_settings(),
    )
