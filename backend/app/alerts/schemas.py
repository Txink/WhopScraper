"""Pydantic schemas for /api/alerts/* and internal repo I/O."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

ConditionType = Literal["price", "pct_change", "volume"]
Operator = Literal[">=", "<="]
Baseline = Literal["today_open", "prev_close"]
VolumeWindow = Literal["1min", "5min"]
RepeatMode = Literal["one_shot", "recurring"]


class AlertCreate(BaseModel):
    ticker: str = Field(min_length=1)
    symbol: str = Field(min_length=1)
    condition_type: ConditionType
    operator: Operator
    threshold: float
    pct_change_baseline: Baseline | None = None
    volume_window: VolumeWindow | None = None
    repeat_mode: RepeatMode = "one_shot"
    cooldown_seconds: int = Field(default=300, ge=0)
    note: str | None = None


class AlertUpdate(BaseModel):
    operator: Operator | None = None
    threshold: float | None = None
    pct_change_baseline: Baseline | None = None
    volume_window: VolumeWindow | None = None
    repeat_mode: RepeatMode | None = None
    cooldown_seconds: int | None = Field(default=None, ge=0)
    enabled: bool | None = None
    note: str | None = None


class AlertOut(BaseModel):
    id: int
    ticker: str
    symbol: str
    condition_type: ConditionType
    operator: Operator
    threshold: float
    pct_change_baseline: Baseline | None
    volume_window: VolumeWindow | None
    repeat_mode: RepeatMode
    cooldown_seconds: int
    enabled: bool
    note: str | None
    created_at: datetime
    last_triggered_at: datetime | None
    trigger_count: int


class AlertEventOut(BaseModel):
    id: int
    alert_id: int
    triggered_at: datetime
    ticker: str
    symbol: str
    snapshot_price: float
    snapshot_pct: float | None
    snapshot_volume: float | None
    message: str


class AlertListOut(BaseModel):
    alerts: list[AlertOut]


class AlertEventListOut(BaseModel):
    events: list[AlertEventOut]
