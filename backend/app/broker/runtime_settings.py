"""Runtime LongPort settings persisted outside .env."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

from app.core.config import Settings

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_SETTINGS_FILE = _PROJECT_ROOT / "data" / "longport_settings.json"


@dataclass
class LongPortCredentialSet:
    app_key: str = ""
    app_secret: str = ""
    access_token: str = ""


@dataclass
class LongPortRuntimeSettings:
    mode: Literal["paper", "real"] = "paper"
    paper: LongPortCredentialSet = field(default_factory=LongPortCredentialSet)
    real: LongPortCredentialSet = field(default_factory=LongPortCredentialSet)
    auto_trade: bool = True
    region: str = "cn"
    dry_run: bool = True

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LongPortRuntimeSettings:
        mode_raw = str(data.get("mode", "paper")).lower()
        mode: Literal["paper", "real"] = "real" if mode_raw == "real" else "paper"
        paper_raw = data.get("paper") or {}
        real_raw = data.get("real") or {}
        return cls(
            mode=mode,
            paper=LongPortCredentialSet(
                app_key=str(paper_raw.get("app_key", "")),
                app_secret=str(paper_raw.get("app_secret", "")),
                access_token=str(paper_raw.get("access_token", "")),
            ),
            real=LongPortCredentialSet(
                app_key=str(real_raw.get("app_key", "")),
                app_secret=str(real_raw.get("app_secret", "")),
                access_token=str(real_raw.get("access_token", "")),
            ),
            auto_trade=bool(data.get("auto_trade", True)),
            region=str(data.get("region", "cn")),
            dry_run=bool(data.get("dry_run", True)),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class LongPortRuntimeStore:
    """Persistent runtime settings for LongPort, independent from .env."""

    def __init__(
        self,
        *,
        settings_file: Path | None = None,
        persist: bool = True,
    ) -> None:
        self._settings_file = settings_file or _DEFAULT_SETTINGS_FILE
        self._persist = persist
        self._value = self._load_or_default()

    @classmethod
    def from_settings_defaults(cls, settings: Settings) -> LongPortRuntimeStore:
        """In-memory fallback used when build_http_router is invoked without
        a real store (test fixtures, isolated subapps).

        DOES NOT write to disk — earlier this method tagged the global default
        file path, so any test that PATCHed /api/longport/settings silently
        clobbered the user's real ``data/longport_settings.json``. Now updates
        stay in-memory; the prod file is only ever touched by the real store
        explicitly wired in main.py's lifespan.
        """
        obj = cls.__new__(cls)
        obj._settings_file = _DEFAULT_SETTINGS_FILE  # cosmetic; never written
        obj._persist = False
        mode_raw = settings.longport_mode.lower()
        mode: Literal["paper", "real"] = "real" if mode_raw == "real" else "paper"
        obj._value = LongPortRuntimeSettings(
            mode=mode,
            paper=LongPortCredentialSet(
                app_key=settings.longport_paper_app_key,
                app_secret=settings.longport_paper_app_secret,
                access_token=settings.longport_paper_access_token,
            ),
            real=LongPortCredentialSet(
                app_key=settings.longport_real_app_key,
                app_secret=settings.longport_real_app_secret,
                access_token=settings.longport_real_access_token,
            ),
            auto_trade=settings.longport_auto_trade,
            region=settings.longport_region,
            dry_run=settings.longport_dry_run,
        )
        return obj

    def get(self) -> LongPortRuntimeSettings:
        # Return a copy so callers can't mutate state without update().
        return LongPortRuntimeSettings.from_dict(self._value.to_dict())

    def set(self, value: LongPortRuntimeSettings) -> LongPortRuntimeSettings:
        self._value = LongPortRuntimeSettings.from_dict(value.to_dict())
        self._save()
        return self.get()

    def update(self, patch: dict[str, Any]) -> LongPortRuntimeSettings:
        current = self._value.to_dict()
        current.update(patch)
        self._value = LongPortRuntimeSettings.from_dict(current)
        self._save()
        return self.get()

    def _load_or_default(self) -> LongPortRuntimeSettings:
        if not self._settings_file.is_file():
            return LongPortRuntimeSettings()
        try:
            raw = json.loads(self._settings_file.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                return LongPortRuntimeSettings.from_dict(raw)
        except (OSError, json.JSONDecodeError):
            pass
        return LongPortRuntimeSettings()

    def _save(self) -> None:
        if not self._persist:
            return
        self._settings_file.parent.mkdir(parents=True, exist_ok=True)
        self._settings_file.write_text(
            json.dumps(self._value.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
