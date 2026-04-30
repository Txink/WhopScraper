"""Scripted simulator scenarios.

Each scenario combines:
  * ``message_text`` — natural-language signal text the parser will run on
  * ``push_steps``  — optional list of broker push events to feed sequentially
                      through ``PushListener._handle_raw_push`` after the
                      task reaches ``INSTRUCTION_READY`` and is "submitted"
                      with a synthetic order_id

Push delays are *compressed* relative to real broker timing (the recorded
``modify_price`` scenario took 78s end-to-end; here we make it ~6s) so a
demo run finishes in a watchable window.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


@dataclass(frozen=True)
class PushStep:
    """One broker push event to inject during simulation.

    ``status`` matches LongPort SDK ``OrderStatus`` labels exactly
    (``WaitToNew``, ``New``, ``Replaced``, ``PartialFilled``, ``Filled``,
    ``Canceled``, ``Rejected``, ...). ``PushListener._map_sdk_status``
    accepts the plain-string form, so the simulator does not need access
    to the SDK enum types.
    """

    delay_s: float
    status: str
    sub_px: float | None = None
    sub_qty: int | None = None
    exec_qty: int = 0
    exec_px: float | None = None
    msg: str = ""


@dataclass(frozen=True)
class Scenario:
    """A scripted end-to-end pipeline run.

    ``submit_failure`` (when set) makes the sim runner take the
    SUBMIT_FAILED path instead of mark_submitted: the parse completes,
    the trader's broker call would have raised, and we land in
    SUBMIT_FAILED with the supplied reason on ``task.reject_reason``.
    Mutually exclusive with ``push_steps`` — sync failure means no
    order_id ever existed, so no pushes can follow.
    """

    name: str
    label: str  # Chinese display name
    description: str
    source: Literal["stock", "option"]
    message_text: str
    push_steps: list[PushStep] | None = field(default=None)
    submit_failure: str | None = None


@dataclass(frozen=True)
class ScenarioOverview:
    """JSON-friendly summary returned by ``GET /api/sim/scenarios``."""

    name: str
    label: str
    description: str
    source: str
    message_text: str
    push_step_count: int  # 0 for parse-only scenarios


# ---------------------------------------------------------------------------
# Scenario registry
# ---------------------------------------------------------------------------


SCENARIOS: dict[str, Scenario] = {
    # ---- Happy paths -------------------------------------------------------
    "normal_buy_fill": Scenario(
        name="normal_buy_fill",
        label="正常买入并成交",
        description="解析 → 提交 → WaitToNew → New → Filled (~250ms)",
        source="stock",
        message_text="8.52加回CONL常规仓的一半",
        push_steps=[
            PushStep(0.0, "WaitToNew", sub_px=8.52, sub_qty=10),
            PushStep(0.05, "New", sub_px=8.52, sub_qty=10),
            PushStep(0.20, "Filled", sub_px=8.52, sub_qty=10, exec_qty=10, exec_px=8.52),
        ],
    ),
    "partial_then_full": Scenario(
        name="partial_then_full",
        label="部分成交后全部成交",
        description="WaitToNew → New → PartialFilled(3/10) → Filled(10/10)",
        source="stock",
        message_text="8.52加回CONL常规仓的一半",
        push_steps=[
            PushStep(0.0, "WaitToNew", sub_px=8.52, sub_qty=10),
            PushStep(0.05, "New", sub_px=8.52, sub_qty=10),
            PushStep(0.6, "PartialFilled", sub_px=8.52, sub_qty=10, exec_qty=3, exec_px=8.51),
            PushStep(0.6, "Filled", sub_px=8.52, sub_qty=10, exec_qty=10, exec_px=8.515),
        ],
    ),

    # ---- Modify scenarios (the bug-uncovered cases) ------------------------
    "modify_price_then_fill": Scenario(
        name="modify_price_then_fill",
        label="改价后成交",
        description="改价两次后成交 — 验证 New→Replaced 重标 + Filled 显示成交价",
        source="stock",
        message_text="8.52加回CONL常规仓的一半",
        push_steps=[
            PushStep(0.0, "WaitToNew", sub_px=8.52, sub_qty=10),
            PushStep(0.05, "New", sub_px=8.52, sub_qty=10),
            PushStep(1.0, "New", sub_px=8.50, sub_qty=10),  # → Replaced
            PushStep(1.0, "New", sub_px=8.48, sub_qty=10),  # → Replaced
            PushStep(0.5, "Filled", sub_px=8.48, sub_qty=10, exec_qty=10, exec_px=8.48),
        ],
    ),
    "modify_price_qty_then_cancel": Scenario(
        name="modify_price_qty_then_cancel",
        label="改价改量后撤单",
        description="重现录制的 modify_price 场景：改价 ×3 + 改量 → 撤单（时间压缩）",
        source="stock",
        message_text="7.31加回CONL常规仓的一半",
        push_steps=[
            PushStep(0.0, "WaitToNew", sub_px=7.31, sub_qty=1),
            PushStep(0.05, "New", sub_px=7.31, sub_qty=1),
            PushStep(1.0, "New", sub_px=7.32, sub_qty=1),  # → Replaced (price)
            PushStep(1.0, "New", sub_px=7.30, sub_qty=1),  # → Replaced (price)
            PushStep(1.0, "New", sub_px=7.30, sub_qty=2),  # → Replaced (qty only!)
            PushStep(1.0, "Canceled", sub_px=7.30, sub_qty=2),
        ],
    ),
    "modify_qty_only_then_fill": Scenario(
        name="modify_qty_only_then_fill",
        label="只改数量后成交",
        description="提交 → 仅改数量（1→2）→ 成交，验证仅量变也能正确显示",
        source="stock",
        message_text="8.52加回CONL常规仓的一半",
        push_steps=[
            PushStep(0.0, "WaitToNew", sub_px=8.52, sub_qty=1),
            PushStep(0.05, "New", sub_px=8.52, sub_qty=1),
            PushStep(1.0, "New", sub_px=8.52, sub_qty=2),  # → Replaced (qty only)
            PushStep(0.5, "Filled", sub_px=8.52, sub_qty=2, exec_qty=2, exec_px=8.52),
        ],
    ),

    # ---- Failure paths -----------------------------------------------------
    "broker_reject_push": Scenario(
        name="broker_reject_push",
        label="Broker 异步拒单",
        description="WaitToNew → Rejected (broker msg)",
        source="stock",
        message_text="8.52加回CONL常规仓的一半",
        push_steps=[
            PushStep(0.0, "WaitToNew", sub_px=8.52, sub_qty=10),
            PushStep(0.3, "Rejected", sub_px=8.52, sub_qty=10, msg="订单金额超出最大购买力"),
        ],
    ),
    "expired": Scenario(
        name="expired",
        label="挂单到期未成交",
        description="WaitToNew → New → Expired（端外日终未成交）",
        source="stock",
        message_text="8.52加回CONL常规仓的一半",
        push_steps=[
            PushStep(0.0, "WaitToNew", sub_px=8.52, sub_qty=10),
            PushStep(0.05, "New", sub_px=8.52, sub_qty=10),
            PushStep(1.5, "Expired", sub_px=8.52, sub_qty=10),
        ],
    ),
    "partial_then_cancel": Scenario(
        name="partial_then_cancel",
        label="部分成交后撤单",
        description="PartialFilled(3/10) → 用户撤单 → PartialWithdrawal",
        source="stock",
        message_text="8.52加回CONL常规仓的一半",
        push_steps=[
            PushStep(0.0, "WaitToNew", sub_px=8.52, sub_qty=10),
            PushStep(0.05, "New", sub_px=8.52, sub_qty=10),
            PushStep(0.5, "PartialFilled", sub_px=8.52, sub_qty=10, exec_qty=3, exec_px=8.51),
            PushStep(1.5, "PartialWithdrawal", sub_px=8.52, sub_qty=10, exec_qty=3, exec_px=8.51),
        ],
    ),
    "multi_partial_fill": Scenario(
        name="multi_partial_fill",
        label="多次部分成交后全部成交",
        description="WaitToNew → New → PartialFilled ×3 (1/10, 4/10, 7/10) → Filled(10/10)",
        source="stock",
        message_text="8.52加回CONL常规仓的一半",
        push_steps=[
            PushStep(0.0, "WaitToNew", sub_px=8.52, sub_qty=10),
            PushStep(0.05, "New", sub_px=8.52, sub_qty=10),
            PushStep(0.5, "PartialFilled", sub_px=8.52, sub_qty=10, exec_qty=1, exec_px=8.520),
            PushStep(0.6, "PartialFilled", sub_px=8.52, sub_qty=10, exec_qty=4, exec_px=8.515),
            PushStep(0.6, "PartialFilled", sub_px=8.52, sub_qty=10, exec_qty=7, exec_px=8.512),
            PushStep(0.6, "Filled", sub_px=8.52, sub_qty=10, exec_qty=10, exec_px=8.510),
        ],
    ),
    "partial_then_modify_price": Scenario(
        name="partial_then_modify_price",
        label="部分成交后改价 → 全部成交",
        description="PartialFilled(3/10) → 改价 8.52→8.50（剩余 7 股按新价挂）→ Filled(10/10)",
        source="stock",
        message_text="8.52加回CONL常规仓的一半",
        push_steps=[
            PushStep(0.0, "WaitToNew", sub_px=8.52, sub_qty=10),
            PushStep(0.05, "New", sub_px=8.52, sub_qty=10),
            PushStep(0.6, "PartialFilled", sub_px=8.52, sub_qty=10, exec_qty=3, exec_px=8.520),
            PushStep(0.8, "New", sub_px=8.50, sub_qty=10, exec_qty=3, exec_px=8.520),  # → Replaced (price)
            PushStep(0.6, "Filled", sub_px=8.50, sub_qty=10, exec_qty=10, exec_px=8.514),
        ],
    ),
    "partial_then_cancel_with_wait": Scenario(
        name="partial_then_cancel_with_wait",
        label="部分成交后撤单（含 WaitToCancel）",
        description="PartialFilled(4/10) → WaitToCancel → PartialWithdrawal(剩余 6 股撤回)",
        source="stock",
        message_text="8.52加回CONL常规仓的一半",
        push_steps=[
            PushStep(0.0, "WaitToNew", sub_px=8.52, sub_qty=10),
            PushStep(0.05, "New", sub_px=8.52, sub_qty=10),
            PushStep(0.5, "PartialFilled", sub_px=8.52, sub_qty=10, exec_qty=2, exec_px=8.520),
            PushStep(0.6, "PartialFilled", sub_px=8.52, sub_qty=10, exec_qty=4, exec_px=8.518),
            PushStep(0.8, "WaitToCancel", sub_px=8.52, sub_qty=10, exec_qty=4, exec_px=8.518),
            PushStep(0.4, "PartialWithdrawal", sub_px=8.52, sub_qty=10, exec_qty=4, exec_px=8.518),
        ],
    ),
    "reject_after_live": Scenario(
        name="reject_after_live",
        label="挂单上交所后被拒",
        description="WaitToNew → New（已上交所）→ Rejected（broker msg）",
        source="stock",
        message_text="8.52加回CONL常规仓的一半",
        push_steps=[
            PushStep(0.0, "WaitToNew", sub_px=8.52, sub_qty=10),
            PushStep(0.05, "New", sub_px=8.52, sub_qty=10),
            PushStep(0.8, "Rejected", sub_px=8.52, sub_qty=10, msg="价格偏离涨跌停限制"),
        ],
    ),
    "reject_unknown_status": Scenario(
        name="reject_unknown_status",
        label="未知 SDK 状态 → FAILED",
        description="WaitToNew → 收到 SDK 没见过的状态 → 内部 FAILED 标记",
        source="stock",
        message_text="8.52加回CONL常规仓的一半",
        push_steps=[
            PushStep(0.0, "WaitToNew", sub_px=8.52, sub_qty=10),
            PushStep(0.3, "TotallyMadeUpStatus", sub_px=8.52, sub_qty=10, msg="SDK 升级后新增的状态"),
        ],
    ),

    # ---- SELL scenarios (mirror the recorded normal_sell case) -----------
    # NOTE on sell qty: parser maps "20.91出TSLL一半" to sell_quantity="全部"
    # (position_size stays None), so trader's _qty_for_whitelisted_stock takes
    # the default path: trade_quantity(200) × position_size_to_fraction(None)=1.0
    # → submit qty=200. Push events below mirror that resolved size.
    "sell_normal_fill": Scenario(
        name="sell_normal_fill",
        label="卖出 - 改价后成交（实录回放）",
        description="录制的 normal_sell：WaitToNew(20.91) → New → New(改价 20.88) → Filled",
        source="stock",
        message_text="20.91出TSLL一半",
        push_steps=[
            PushStep(0.0, "WaitToNew", sub_px=20.91, sub_qty=200),
            PushStep(0.05, "New", sub_px=20.91, sub_qty=200),
            PushStep(0.8, "New", sub_px=20.88, sub_qty=200),  # → Replaced (price down to chase bid)
            PushStep(0.5, "Filled", sub_px=20.88, sub_qty=200, exec_qty=200, exec_px=20.88),
        ],
    ),
    "sell_partial_then_full": Scenario(
        name="sell_partial_then_full",
        label="卖出 - 多次部分成交后全成",
        description="WaitToNew → New → PartialFilled ×2 (80/200, 160/200) → Filled(200)",
        source="stock",
        message_text="20.91出TSLL一半",
        push_steps=[
            PushStep(0.0, "WaitToNew", sub_px=20.91, sub_qty=200),
            PushStep(0.05, "New", sub_px=20.91, sub_qty=200),
            PushStep(0.5, "PartialFilled", sub_px=20.91, sub_qty=200, exec_qty=80, exec_px=20.910),
            PushStep(0.6, "PartialFilled", sub_px=20.91, sub_qty=200, exec_qty=160, exec_px=20.905),
            PushStep(0.6, "Filled", sub_px=20.91, sub_qty=200, exec_qty=200, exec_px=20.902),
        ],
    ),
    "sell_modify_then_cancel": Scenario(
        name="sell_modify_then_cancel",
        label="卖出 - 改价改量后撤单",
        description="改价 20.91→20.88→20.95 + 改量 200→100 → 撤单",
        source="stock",
        message_text="20.91出TSLL一半",
        push_steps=[
            PushStep(0.0, "WaitToNew", sub_px=20.91, sub_qty=200),
            PushStep(0.05, "New", sub_px=20.91, sub_qty=200),
            PushStep(1.0, "New", sub_px=20.88, sub_qty=200),  # → Replaced (price)
            PushStep(1.0, "New", sub_px=20.95, sub_qty=200),  # → Replaced (price)
            PushStep(1.0, "New", sub_px=20.95, sub_qty=100),  # → Replaced (qty)
            PushStep(1.0, "Canceled", sub_px=20.95, sub_qty=100),
        ],
    ),
    "sell_partial_then_cancel": Scenario(
        name="sell_partial_then_cancel",
        label="卖出 - 部分成交后撤单",
        description="PartialFilled(80/200) → WaitToCancel → PartialWithdrawal（剩余 120 股撤回）",
        source="stock",
        message_text="20.91出TSLL一半",
        push_steps=[
            PushStep(0.0, "WaitToNew", sub_px=20.91, sub_qty=200),
            PushStep(0.05, "New", sub_px=20.91, sub_qty=200),
            PushStep(0.5, "PartialFilled", sub_px=20.91, sub_qty=200, exec_qty=40, exec_px=20.910),
            PushStep(0.6, "PartialFilled", sub_px=20.91, sub_qty=200, exec_qty=80, exec_px=20.905),
            PushStep(0.8, "WaitToCancel", sub_px=20.91, sub_qty=200, exec_qty=80, exec_px=20.905),
            PushStep(0.4, "PartialWithdrawal", sub_px=20.91, sub_qty=200, exec_qty=80, exec_px=20.905),
        ],
    ),

    # ---- Synchronous submit failures (no order_id ever issued) ------------
    "submit_failed_short_unsupported": Scenario(
        name="submit_failed_short_unsupported",
        label="同步拒单 - 不支持卖空",
        description="Broker 同步抛异常（trader 在 mark_submit_failed 路径）— 无 order_id",
        source="stock",
        message_text="清空CONL",  # SELL signal
        push_steps=None,
        submit_failure="broker [603301] The symbol currently does not support short selling.",
    ),
    "submit_failed_insufficient_funds": Scenario(
        name="submit_failed_insufficient_funds",
        label="同步拒单 - 资金不足",
        description="Broker 同步报余额不足，task 落 SUBMIT_FAILED",
        source="stock",
        message_text="8.52加回CONL常规仓的一半",
        push_steps=None,
        submit_failure="broker [602012] 账户可用资金不足以完成本次委托",
    ),

    # ---- Parse failures (no push steps; pipeline halts at PARSE_ERROR) ----
    "parse_error_chatter": Scenario(
        name="parse_error_chatter",
        label="解析异常 - 闲聊",
        description="不是交易指令的消息 — 预期 PARSE_ERROR 或 SKIPPED",
        source="stock",
        message_text="今天大盘表现真不错，明天看看",
        push_steps=None,
    ),
    "parse_error_no_ticker": Scenario(
        name="parse_error_no_ticker",
        label="解析异常 - 缺 ticker",
        description="价格量都有但没股票代码 — 触发 context resolver 兜底失败",
        source="stock",
        message_text="买100股 价格50",
        push_steps=None,
    ),
    "parse_ok_no_push": Scenario(
        name="parse_ok_no_push",
        label="解析成功但无后续推送",
        description="任务停在 INSTRUCTION_READY（auto_trade=off 或 broker 不可用模拟）",
        source="stock",
        message_text="8.52加回CONL常规仓的一半",
        push_steps=[],  # empty list (vs None) → submit phase runs, but no pushes
    ),
}


def list_scenarios() -> list[ScenarioOverview]:
    """Public summary list for the REST API."""
    return [
        ScenarioOverview(
            name=s.name,
            label=s.label,
            description=s.description,
            source=s.source,
            message_text=s.message_text,
            push_step_count=len(s.push_steps) if s.push_steps is not None else 0,
        )
        for s in SCENARIOS.values()
    ]
