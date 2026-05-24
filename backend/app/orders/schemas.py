"""Pydantic schemas for the /api/orders/* endpoints."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

OrderType = Literal["LIMIT", "MARKET"]
OrderSide = Literal["BUY", "SELL"]


class SubmitOrderRequest(BaseModel):
    symbol: str = Field(min_length=1)
    side: OrderSide
    qty: int = Field(gt=0)
    order_type: OrderType
    price: float | None = None
    time_in_force: Literal["Day"] = "Day"
    note: str | None = None


class ReplaceOrderRequest(BaseModel):
    price: float | None = None
    qty: int | None = Field(default=None, gt=0)


class OrderOut(BaseModel):
    order_id: str
    task_id: str | None
    ticker: str
    symbol: str
    side: OrderSide
    order_type: OrderType
    price: float | None
    qty: int
    filled_qty: int
    status: str
    source: Literal["signal", "manual", "external"]
    submitted_at: datetime | None
    last_replaced_at: datetime | None


class OrderListOut(BaseModel):
    orders: list[OrderOut]
