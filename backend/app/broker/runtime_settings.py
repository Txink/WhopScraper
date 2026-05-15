"""Runtime LongPort settings persisted outside .env.

Multi-account model (replaces the prior paper/real two-slot design): the
user can authorize an arbitrary number of LongBridge accounts. Each
account is identified by the OAuth ``client_id`` we registered for it (the
client_id is permanent until the user explicitly logs out — which scrubs
both the SDK token cache and our settings entry).

LongBridge OpenAPI does NOT differentiate paper/real at the protocol level
(Config.from_oauth has no paper-trading flag, and all SDK calls go to the
same live endpoint), so the prior paper/real toggle was misleading. The
real concept is "which Longbridge account are we connected to" — that's
what an account slot represents.

Old paper/real shape on disk is auto-migrated on first read.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from app.broker.oauth import is_authorized
from app.core.config import Settings

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_SETTINGS_FILE = _PROJECT_ROOT / "data" / "longport_settings.json"


@dataclass
class LongPortAccount:
    """One OAuth-authorized LongBridge account.

    ``account_id`` is the OAuth client_id we registered against the
    Longbridge OAuth endpoint — permanent for the lifetime of the
    registration. ``label`` is a user-chosen display name; defaults to
    "账户 1", "账户 2", … on add. ``authorized`` is derived from the SDK
    token cache: True iff ``~/.longbridge/openapi/tokens/<account_id>``
    exists.
    """

    account_id: str
    label: str = ""
    authorized: bool = False

    def reconcile(self) -> LongPortAccount:
        """Return a copy with authorized re-derived from the token cache."""
        return LongPortAccount(
            account_id=self.account_id,
            label=self.label,
            authorized=is_authorized(self.account_id),
        )


@dataclass
class LongPortRuntimeSettings:
    """Persistent settings: active account + the list of known accounts."""

    active_account_id: str | None = None
    accounts: list[LongPortAccount] = field(default_factory=list)
    auto_trade: bool = True
    region: str = "cn"
    dry_run: bool = True

    @property
    def active_account(self) -> LongPortAccount | None:
        if self.active_account_id is None:
            return None
        return next(
            (a for a in self.accounts if a.account_id == self.active_account_id),
            None,
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LongPortRuntimeSettings:
        # Auto-migrate the legacy paper/real two-slot shape. If we see
        # "paper" or "real" keys but no "accounts" key, convert each
        # non-empty slot into an account.
        if "accounts" not in data and ("paper" in data or "real" in data):
            return _migrate_legacy(data)

        raw_accounts = data.get("accounts") or []
        accounts: list[LongPortAccount] = []
        for entry in raw_accounts:
            if not isinstance(entry, dict):
                continue
            cid = str(entry.get("account_id", ""))
            if not cid:
                continue
            accounts.append(
                LongPortAccount(
                    account_id=cid,
                    label=str(entry.get("label", "")),
                    authorized=bool(entry.get("authorized", False)),
                ).reconcile()
            )
        active = data.get("active_account_id")
        active_id: str | None = str(active) if active else None
        # Drop an active pointer that no longer matches any account (e.g.
        # the previously-active account was logged out by hand).
        if active_id is not None and not any(a.account_id == active_id for a in accounts):
            active_id = None
        return cls(
            active_account_id=active_id,
            accounts=accounts,
            auto_trade=bool(data.get("auto_trade", True)),
            region=str(data.get("region", "cn")),
            dry_run=bool(data.get("dry_run", True)),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _migrate_legacy(data: dict[str, Any]) -> LongPortRuntimeSettings:
    """Convert old { paper: {...}, real: {...}, mode: ... } shape to the
    new multi-account form. Empty slots are dropped; the previously-active
    mode (if any) becomes the active_account_id."""
    accounts: list[LongPortAccount] = []
    for slot_name in ("paper", "real"):
        slot = data.get(slot_name) or {}
        cid = str(slot.get("client_id", ""))
        if not cid:
            continue
        accounts.append(
            LongPortAccount(
                account_id=cid,
                label=slot_name,
                authorized=bool(slot.get("authorized", False)),
            ).reconcile()
        )
    mode = str(data.get("mode", "")).lower()
    active_id: str | None = next(
        (a.account_id for a in accounts if a.label == mode),
        None,
    )
    return LongPortRuntimeSettings(
        active_account_id=active_id,
        accounts=accounts,
        auto_trade=bool(data.get("auto_trade", True)),
        region=str(data.get("region", "cn")),
        dry_run=bool(data.get("dry_run", True)),
    )


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

        DOES NOT write to disk — tests must not clobber the real settings
        file.
        """
        obj = cls.__new__(cls)
        obj._settings_file = _DEFAULT_SETTINGS_FILE  # cosmetic; never written
        obj._persist = False
        obj._value = LongPortRuntimeSettings(
            auto_trade=settings.longport_auto_trade,
            region=settings.longport_region,
            dry_run=settings.longport_dry_run,
        )
        return obj

    def get(self) -> LongPortRuntimeSettings:
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

    # ---- Account-list mutators ---------------------------------------- #

    def add_account(self, account_id: str, label: str = "") -> LongPortRuntimeSettings:
        """Insert an account (or update its label if already present).

        The first account added becomes the active one automatically — the
        common case is the user adding their first account and expecting
        the broker to start using it immediately.
        """
        current = self._value.to_dict()
        accounts = list(current.get("accounts") or [])
        # Update in place if present.
        replaced = False
        for entry in accounts:
            if isinstance(entry, dict) and entry.get("account_id") == account_id:
                if label:
                    entry["label"] = label
                replaced = True
                break
        if not replaced:
            accounts.append(
                {
                    "account_id": account_id,
                    "label": label or f"账户 {len(accounts) + 1}",
                    "authorized": True,
                }
            )
        current["accounts"] = accounts
        if not current.get("active_account_id"):
            current["active_account_id"] = account_id
        self._value = LongPortRuntimeSettings.from_dict(current)
        self._save()
        return self.get()

    def remove_account(self, account_id: str) -> LongPortRuntimeSettings:
        """Drop an account from the list. If it was the active one, fall
        back to the next available account (or None if the list is empty)."""
        current = self._value.to_dict()
        accounts = [
            e
            for e in (current.get("accounts") or [])
            if isinstance(e, dict) and e.get("account_id") != account_id
        ]
        current["accounts"] = accounts
        if current.get("active_account_id") == account_id:
            current["active_account_id"] = accounts[0]["account_id"] if accounts else None
        self._value = LongPortRuntimeSettings.from_dict(current)
        self._save()
        return self.get()

    def set_active(self, account_id: str) -> LongPortRuntimeSettings:
        current = self._value.to_dict()
        # Guard: only set active to an account that's actually in the list.
        if not any(
            isinstance(e, dict) and e.get("account_id") == account_id
            for e in (current.get("accounts") or [])
        ):
            raise ValueError(f"account_id {account_id!r} is not in the account list")
        current["active_account_id"] = account_id
        self._value = LongPortRuntimeSettings.from_dict(current)
        self._save()
        return self.get()

    def rename_account(self, account_id: str, label: str) -> LongPortRuntimeSettings:
        current = self._value.to_dict()
        for entry in current.get("accounts") or []:
            if isinstance(entry, dict) and entry.get("account_id") == account_id:
                entry["label"] = label
                break
        self._value = LongPortRuntimeSettings.from_dict(current)
        self._save()
        return self.get()

    # ---- Persistence -------------------------------------------------- #

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
