"""Application settings loaded from environment / .env file.

Uses pydantic-settings; the .env file is expected at the project root,
one level above the ``backend/`` directory.
"""
from __future__ import annotations

import functools

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        # Resolved relative to where Python is invoked from.  In practice:
        #   • pytest runs from backend/  → "../.env" walks up to project root
        #   • uvicorn runs from backend/ → same
        env_file="../.env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ------------------------------------------------------------------ #
    # General                                                              #
    # ------------------------------------------------------------------ #
    app_token: str = "change-me-to-a-random-32-char-string"

    # ------------------------------------------------------------------ #
    # Whop scraper                                                         #
    # ------------------------------------------------------------------ #
    whop_stock_url: str = ""
    whop_option_url: str = ""
    whop_poll_interval: float = 2.0
    whop_headless: bool = False

    # ------------------------------------------------------------------ #
    # LongPort broker                                                      #
    # ------------------------------------------------------------------ #
    longport_mode: str = "paper"
    longport_paper_app_key: str = ""
    longport_paper_app_secret: str = ""
    longport_paper_access_token: str = ""
    longport_real_app_key: str = ""
    longport_real_app_secret: str = ""
    longport_real_access_token: str = ""
    longport_region: str = "cn"
    longport_auto_trade: bool = True
    longport_dry_run: bool = True

    # ------------------------------------------------------------------ #
    # Risk controls                                                        #
    # ------------------------------------------------------------------ #
    max_option_total_price: float = 500.0
    max_option_quantity: int = 3
    price_deviation_tolerance: float = 5.0
    stock_price_deviation_tolerance: float = 1.0

    # ------------------------------------------------------------------ #
    # Database                                                             #
    # ------------------------------------------------------------------ #
    database_url: str = "sqlite+aiosqlite:///./data/signals.db"

    # ------------------------------------------------------------------ #
    # HTTP server                                                          #
    # ------------------------------------------------------------------ #
    http_host: str = "127.0.0.1"
    http_port: int = 8000

    # ------------------------------------------------------------------ #
    # Logging                                                              #
    # ------------------------------------------------------------------ #
    log_level: str = "INFO"


@functools.lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached singleton Settings instance.

    Call ``get_settings.cache_clear()`` to force re-loading (useful in tests
    when env vars are patched via ``monkeypatch``).

    Signature must take no params: FastAPI introspects this function when
    used via ``Depends(get_settings)``, and any extra param (including
    ``**kwargs``) becomes a required query parameter.
    """
    return Settings()
