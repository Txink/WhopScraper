"""Pydantic request/response schemas for Signal Station REST API (§7).

All *Out models are serializable via .model_dump(mode="json").
Converter functions translate app.domain.* dataclasses → Pydantic models.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from app.domain.instruction import Instruction
    from app.domain.message import Message
    from app.domain.push_event import PushEvent
    from app.domain.task import InstructionLabel, Task
    from app.storage.schema import TPairRow
    from app.whop.listener import WhopListener
    from app.whop.registry import WhopPageEntry


# ---------------------------------------------------------------------------
# Message
# ---------------------------------------------------------------------------


class MessageOut(BaseModel):
    id: str
    content: str
    raw_content: str
    author: str | None
    source: str
    posted_at: datetime
    received_at: datetime
    url: str | None = None
    quoted_message_id: str | None
    image_url: str | None = None


# ---------------------------------------------------------------------------
# Instruction (stock + option unified)
# ---------------------------------------------------------------------------


class InstructionOut(BaseModel):
    """Union serializer for Stock/Option — carries a discriminator field."""

    type: str = Field(..., description="stock | option")
    instruction_type: str
    price: float | None
    price_range: tuple[float, float] | None
    quantity: int | None
    position_size: str | None
    stop_loss_price: float | None
    take_profit_price: float | None
    context_source: str | None
    parser_notes: list[str]
    referenced_lot_price: float | None = None  # ← new
    # Stock-only
    ticker: str | None = None
    symbol: str | None = None
    sell_quantity: str | None = None
    # Option-only
    option_type: str | None = None  # CALL | PUT
    strike: float | None = None
    expiry: date | None = None


class CorrectedInstruction(BaseModel):
    """人工校正后的指令字段集合（纯标注，不参与交易）。"""
    type: Literal["stock", "option"]
    action: Literal["BUY", "SELL", "CLOSE", "MODIFY"]
    ticker: str | None = None
    price: float | None = None
    quantity: int | None = None
    strike: float | None = None
    expiry: str | None = None
    option_type: Literal["CALL", "PUT"] | None = None


class InstructionLabelOut(BaseModel):
    verdict: str  # "correct" | "corrected"
    corrected_payload: CorrectedInstruction | None = None
    updated_at: datetime


class InstructionLabelIn(BaseModel):
    verdict: Literal["correct", "corrected"]
    corrected_payload: CorrectedInstruction | None = None


# ---------------------------------------------------------------------------
# PushEvent
# ---------------------------------------------------------------------------


class PushEventOut(BaseModel):
    id: str
    task_id: str
    order_id: str
    state: str
    received_at: datetime
    delta_qty: int | None
    delta_price: float | None
    cumulative_qty: int | None
    cumulative_avg_price: float | None
    note: str | None
    submitted_price: float | None = None
    submitted_quantity: int | None = None


# ---------------------------------------------------------------------------
# Task (full detail)
# ---------------------------------------------------------------------------


class TaskOut(BaseModel):
    id: str
    type: str
    status: str
    order_id: str | None
    submit_order_type: str | None = None
    submit_order_context: str | None = None
    submit_quote_last_done: float | None = None
    submit_price: float | None = None
    stage_timings: dict[str, float]
    created_at: datetime
    updated_at: datetime
    reject_reason: str | None
    message: MessageOut
    instruction: InstructionOut | None
    push_events: list[PushEventOut]
    # Snapshot of the latest push event's broker-side state. Lets the
    # collapsed card render the actually-executed (or post-modify) values
    # instead of the original signal. All four are None when no pushes
    # have arrived yet (parse-only or sync-failed tasks).
    last_cum_qty: int | None = None
    last_cum_avg_price: float | None = None
    last_submitted_price: float | None = None
    last_submitted_qty: int | None = None
    label: InstructionLabelOut | None = None


# ---------------------------------------------------------------------------
# Task list (push_events intentionally omitted for performance)
# ---------------------------------------------------------------------------


class TaskSummaryOut(BaseModel):
    id: str
    type: str
    status: str
    order_id: str | None
    submit_order_type: str | None = None
    submit_order_context: str | None = None
    submit_quote_last_done: float | None = None
    submit_price: float | None = None
    stage_timings: dict[str, float]
    created_at: datetime
    updated_at: datetime
    reject_reason: str | None
    message: MessageOut
    instruction: InstructionOut | None
    # See TaskOut for semantics. Same shape so the WS bridge (which sends
    # task_to_out) and the HTTP list (which sends task_to_summary) populate
    # the same display fields the frontend reads.
    last_cum_qty: int | None = None
    last_cum_avg_price: float | None = None
    last_submitted_price: float | None = None
    last_submitted_qty: int | None = None
    label: InstructionLabelOut | None = None
    # push_events intentionally NOT included — call /api/tasks/{id} for full detail


class TaskListOut(BaseModel):
    tasks: list[TaskSummaryOut]
    next_cursor: datetime | None = None


class TaskCountOut(BaseModel):
    total_count: int


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------


class StatsTodayOut(BaseModel):
    msg_count: int
    parse_ok: int
    parse_rate: float
    orders: int
    filled: int
    rejected: int


# ---------------------------------------------------------------------------
# Positions
# ---------------------------------------------------------------------------


class PositionOut(BaseModel):
    symbol: str
    type: str  # stock | option
    ticker: str
    quantity: int
    avg_cost: float | None
    # Symbol display name from the broker. Critical for HK / A-share
    # positions whose ticker is numeric ("2228" → "罗欣药业") and useless
    # without the company name. Optional because legacy / sim brokers may
    # not surface it.
    name: str | None = None
    option_strike: float | None = None
    option_expiry: date | None = None
    option_type: str | None = None


class PositionsOut(BaseModel):
    stocks: list[PositionOut]
    options: list[PositionOut]


# ---------------------------------------------------------------------------
# T-pair (做T 配对)
# ---------------------------------------------------------------------------


class TPairAllocation(BaseModel):
    """One trade's allocation into a做T pair. ``qty`` may be less than the
    trade's filled quantity — a trade can be split across multiple pairs."""

    trade_id: str
    qty: int


class TPairOut(BaseModel):
    # Pair id is a SQLite autoincrement integer (table-wide unique, never
    # reused). UI labels it as "T-{id}".
    id: int
    ticker: str
    symbol: str | None = None
    buys: list[TPairAllocation]
    sells: list[TPairAllocation]
    # Realized做T profit on the matched portion; persisted on the pair row.
    profit: float = 0.0
    created_at: datetime
    updated_at: datetime


class PairAggregateOut(BaseModel):
    """Account+ticker scoped做T aggregates — driven by SQL SUM/COUNT
    over t_pairs so PairKPIs can render without pulling every pair into
    memory."""

    profit_total: float
    count: int
    win_count: int


class PendingTradeOut(BaseModel):
    """One row of "pending做T" trade — broker fill with remaining qty
    not yet allocated to any pair."""

    order_id: str
    ticker: str
    symbol: str
    side: str
    qty: int
    allocated_qty: int
    pending_qty: int
    price: float
    ts: datetime


class PendingExecutionsOut(BaseModel):
    """Aggregate + per-trade breakdown of unallocated qty."""

    pending_buy_qty: int
    pending_sell_qty: int
    trades: list[PendingTradeOut]


class ExecutionsSyncOut(BaseModel):
    """Response payload for ``POST /api/broker/executions/sync``.

    ``persisted`` is the upsert count returned by
    ``sync_broker_executions`` (new rows + updated rows). The frontend
    doesn't display it; the field exists for logging and test assertions.
    """

    persisted: int


class TPairsOut(BaseModel):
    pairs: list[TPairOut]
    # Total做T pair count matching the request's filters (account/ticker),
    # ignoring pagination. Defaults to ``len(pairs)`` so legacy
    # non-paginated callers see a sensible value.
    total_count: int = 0
    has_more: bool = False


class TPairCreate(BaseModel):
    """Client selection for a new做T pair. The server computes per-trade
    qty allocations using FIFO + min(BUY_avail, SELL_avail) and persists
    the result; partial / one-sided selections are accepted."""

    ticker: str
    symbol: str | None = None
    buy_trade_ids: list[str] = []
    sell_trade_ids: list[str] = []


class TPairExtendIn(BaseModel):
    """Add more trades to an existing pair. Same allocation rules apply,
    with the existing pair contents counted against trade availability."""

    buy_trade_ids: list[str] = []
    sell_trade_ids: list[str] = []


# ---------------------------------------------------------------------------
# Quote / candlestick
# ---------------------------------------------------------------------------


class QuoteOut(BaseModel):
    symbol: str
    last_done: float
    # Yesterday's RTH close. Used as the change% reference during
    # 盘前 / 盘中 sessions.
    prev_close: float
    # TODAY's RTH close — only populated during 盘后 / 夜盘 (when the
    # SDK has frozen ``SecurityQuote.last_done`` at the close). Acts as
    # the change% reference during those sessions. ``None`` otherwise.
    today_close: float | None = None
    open: float
    high: float
    low: float
    volume: int
    turnover: float
    change: float
    change_pct: float
    # Current market state for the symbol (determined from the wall clock
    # in the market's local timezone, not from which quote tier has the
    # freshest tick). Stock cards render this as a 盘中 / 盘前 / 盘后 /
    # 夜盘 / 休市 chip. "closed" means the market is outside any session
    # window (weekend, lunch break, post-close) and the surfaced
    # ``last_done`` is yesterday's close.
    trade_session: Literal["regular", "pre", "post", "overnight", "closed"] = "regular"
    # ET (or HKT / CST) calendar date that ``last_done`` belongs to,
    # as ISO ``YYYY-MM-DD``. Resolved server-side from the broker's
    # trading-days calendar so weekends + holidays are handled. The
    # frontend uses this to filter "today's executions" for Day P/L
    # without needing its own holiday calendar. ``None`` when the
    # broker calendar cache is cold (frontend falls back to wall clock).
    trading_day: str | None = None


class QuotesOut(BaseModel):
    quotes: list[QuoteOut]


class QuoteWatchIn(BaseModel):
    """Request body for ``POST /api/quotes/watch``.

    Replaces the active quote-push watch set with ``symbols``. Backend
    diffs vs. the prior set and issues subscribe/unsubscribe calls to the
    broker. Empty list clears all subscriptions (e.g. on dashboard close).
    """

    symbols: list[str]


class QuoteWatchOut(BaseModel):
    """Response body for ``POST /api/quotes/watch`` — observability fields
    so the UI / log can confirm the diff actually took effect."""

    added: int
    removed: int
    total: int


class CandlestickOut(BaseModel):
    timestamp: str | None
    open: float
    high: float
    low: float
    close: float
    volume: int
    turnover: float


class CandlesticksOut(BaseModel):
    symbol: str
    period: str  # "today" | "5" | "7" | "30" | "day" | "week" | "month" | "year"
    bars: list[CandlestickOut]


# ---------------------------------------------------------------------------
# Trade aggregation (flat fill list per ticker for做T binding)
# ---------------------------------------------------------------------------


class TradeOut(BaseModel):
    """A single fully-executed (or partial) trade, suitable as a做T
    pair member. ``id`` matches the originating task id."""

    id: str
    ticker: str
    # Full symbol from the originating instruction (e.g. "TSLA.US" for a
    # stock fill, "RXRX260618C7000" for an option contract fill). Needed
    # to distinguish trades on the same ticker but different option
    # contracts when computing per-contract day P/L on the option card.
    symbol: str | None = None
    side: str  # BUY | SELL
    qty: int
    price: float
    ts: datetime
    source: str | None = None  # signal channel / author
    tag: str | None = None     # parser-extracted note ("做T 加仓" etc.)


class TradesOut(BaseModel):
    ticker: str
    trades: list[TradeOut]


class ExecutionOut(BaseModel):
    """One broker-side ORDER (with partial fills aggregated). The unit
    of做T binding + day-PL accounting.

    ``order_id`` is the unique key. ``task_id`` (nullable) links back to
    the signal-station ``tasks`` row that submitted this order — present
    only for orders that went through the trader pipeline; manual fills
    placed via the LongBridge app / web have ``task_id = null``.

    ``t_pair_tags`` is the server-denormalised做T allocation list:
    ``[[pair_id, allocated_qty], ...]``. Lets the trade-list frontend
    paint做T chips without a separate /api/pairs round-trip, AND
    survives across page reloads — without it on the wire, a re-fetch
    after detail-pane re-open silently dropped the chips. Defaults to
    ``[]`` for fills that aren't bound to any pair.
    """

    order_id: str
    task_id: str | None = None
    symbol: str
    ticker: str
    side: Literal["BUY", "SELL"]
    qty: int
    price: float
    ts: datetime
    t_pair_tags: list[tuple[int, int]] = []


class ExecutionsOut(BaseModel):
    executions: list[ExecutionOut]
    # Wall-clock moment of the most recent broker→DB sync write for this
    # slice. Detail pane renders it as "上次更新：xxx". Null when no
    # row has been synced yet (first-ever open).
    last_synced_at: datetime | None = None
    # Total rows matching the request's filters (account/ticker/window),
    # ignoring pagination. Lets the UI render "N 笔 (已加载 M)" and decide
    # whether to show 加载更多. Defaults to ``len(executions)`` for callers
    # that don't paginate.
    total_count: int = 0
    has_more: bool = False


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


class HealthOut(BaseModel):
    whop: str  # up | down
    longport: str  # up | down
    # OAuth account label that the broker is currently bound to. Empty
    # string when no account is active yet. Replaces the prior paper/real
    # ``mode`` field, which has no meaning in the multi-account era.
    account_label: str = ""
    dry_run: bool


class LongPortAccountOut(BaseModel):
    """One OAuth-authorized LongBridge account slot in the settings list.

    ``account_id`` is the registered Longbridge OAuth client_id (stable
    per Longbridge account). ``label`` is a user-chosen display name.
    ``authorized`` reflects whether the SDK token cache holds a valid
    token for that account.
    """

    account_id: str
    label: str
    authorized: bool


class LongPortSettingsOut(BaseModel):
    active_account_id: str | None
    accounts: list[LongPortAccountOut]
    auto_trade: bool
    region: str
    dry_run: bool


class LongPortSettingsPatch(BaseModel):
    """Mutable subset of LongPort settings. Account list is managed via the
    OAuth + account endpoints and cannot be patched here.
    """

    auto_trade: bool | None = None
    region: str | None = None
    dry_run: bool | None = None


class LongPortOAuthStartOut(BaseModel):
    """Returned by POST /oauth/start — the URL is opened in a new tab and
    the session_id is polled by /oauth/status until completion. The new
    account_id is added to the settings list only after success."""

    session_id: str
    auth_url: str
    account_id: str


class LongPortOAuthStatusOut(BaseModel):
    state: Literal["awaiting_url", "ready", "success", "error", "cancelled"]
    error: str | None = None
    account_id: str | None = None


class LongPortAccountActivateIn(BaseModel):
    account_id: str


class LongPortAccountLogoutIn(BaseModel):
    account_id: str


class LongPortAccountRenameIn(BaseModel):
    account_id: str
    label: str


class BrokerStatusOut(BaseModel):
    """Snapshot of the running broker — whether it's a live LongPortClient
    or fell back to NoopBrokerClient, plus the last init error if any.
    """

    is_real: bool
    # User-chosen label of the currently active account (empty when noop
    # or no account configured). Replaces the prior paper/real mode field.
    account_label: str = ""
    dry_run: bool
    last_init_error: str | None = None


# ---------------------------------------------------------------------------
# Cancel
# ---------------------------------------------------------------------------


class CancelOk(BaseModel):
    ok: bool = True


# ---------------------------------------------------------------------------
# Per-page Whop settings
# ---------------------------------------------------------------------------


class TickerConfigOut(BaseModel):
    trade_quantity: int


class WhopPageSettingsOut(BaseModel):
    dedupe_processed_messages: bool
    price_deviation_tolerance: float
    block_historical_messages: bool
    launch_headless: bool
    parser_version: Literal["v1", "v2"] = "v1"
    tickers: dict[str, TickerConfigOut] | None = None  # None = option page
    option_buy_quantity_enabled: bool | None = None
    option_buy_quantity: int | None = None
    option_total_price_limit_enabled: bool | None = None
    option_total_price_limit: float | None = None
    watched_senders: list[str] = Field(default_factory=list)
    chat_card_max_msgs: int = 5


class WhopPageSettingsPatch(BaseModel):
    """Local update; any unspecified field = unchanged."""

    dedupe_processed_messages: bool | None = None
    price_deviation_tolerance: float | None = Field(default=None, ge=0)
    block_historical_messages: bool | None = None
    launch_headless: bool | None = None
    parser_version: Literal["v1", "v2"] | None = None
    tickers: dict[str, TickerConfigOut] | None = None
    option_buy_quantity_enabled: bool | None = None
    option_buy_quantity: int | None = Field(default=None, ge=1)
    option_total_price_limit_enabled: bool | None = None
    option_total_price_limit: float | None = Field(default=None, gt=0)
    watched_senders: list[str] | None = None
    chat_card_max_msgs: int | None = Field(default=None, ge=1, le=50)


# ---------------------------------------------------------------------------
# Whop monitoring management
# ---------------------------------------------------------------------------


class WhopPageOut(BaseModel):
    id: str
    url: str
    source: str
    name: str
    added_at: datetime
    settings: WhopPageSettingsOut
    # Live status (None when listener absent)
    running: bool
    started_at: datetime | None
    last_poll_at: datetime | None
    messages_published: int
    last_error: str | None
    parent_chat_id: str | None = None


class WhopPagesOut(BaseModel):
    pages: list[WhopPageOut]


class WhopPageCreate(BaseModel):
    url: str
    source: Literal["stock", "option", "chat"]
    name: str | None = None
    parent_chat_id: str | None = None


class WhopCookieStatusOut(BaseModel):
    exists: bool
    path: str
    last_modified: datetime | None = None
    age_seconds: float | None = None


class OrphanCleanupRequest(BaseModel):
    url: str | None = None  # None → 清理 legacy NULL-url tasks
    force: bool = False  # True → 允许清理活跃 page 的 url（用于"清空本页历史"）


class OrphanCleanupResponse(BaseModel):
    deleted_count: int


# ---------------------------------------------------------------------------
# Chat monitor panel — GET /api/whop/pages/{page_id}/chat-messages
# ---------------------------------------------------------------------------


class QuotedRefOut(BaseModel):
    """Nested representation of a quoted parent message.

    All four fields are denormalized into ``chat_messages`` columns at write
    time, so the row renders correctly even if the parent message is missing
    (different week, never scraped, non-watched sender). ``message_id`` and
    ``posted_at`` may be ``None`` when the scrape only captured the visible
    quote bubble without a stable id / timestamp.
    """

    message_id: str | None = None
    author: str
    content: str
    posted_at: datetime | None = None


class ChatMessageOut(BaseModel):
    id: str
    page_id: str
    author: str
    content: str
    posted_at: datetime
    quoted: QuotedRefOut | None = None
    image_url: str | None = None


class ChatAuthorOut(BaseModel):
    name: str
    count: int


class ChatDayWindowOut(BaseModel):
    """北京日历日的半开 UTC 区间 ``[start, end)``。"""

    start: datetime
    end: datetime


class ChatMessagesOut(BaseModel):
    messages: list[ChatMessageOut]
    authors: list[ChatAuthorOut]
    day: ChatDayWindowOut


class ChatMessageCountsOut(BaseModel):
    """按北京日历日聚合的当月消息计数。``counts`` 仅包含 ``count > 0`` 的天。"""

    month: str  # "YYYY-MM"
    counts: dict[str, int]  # {"YYYY-MM-DD": count}


# ---------------------------------------------------------------------------
# Converters: domain dataclasses → Pydantic Out models
# ---------------------------------------------------------------------------


def message_to_out(msg: Message) -> MessageOut:
    """Convert a domain Message to MessageOut (quoted → quoted_message_id only)."""
    return MessageOut(
        id=msg.id,
        content=msg.content,
        raw_content=msg.raw_content,
        author=msg.author,
        source=msg.source,
        posted_at=msg.posted_at,
        received_at=msg.received_at,
        url=msg.url,
        quoted_message_id=msg.quoted.id if msg.quoted is not None else None,
        image_url=(
            f"/api/messages/{msg.id}/image" if msg.image_filename else None
        ),
    )


def push_event_to_out(evt: PushEvent) -> PushEventOut:
    """Convert a domain PushEvent to PushEventOut."""
    return PushEventOut(
        id=evt.id,
        task_id=evt.task_id,
        order_id=evt.order_id,
        state=str(evt.state),
        received_at=evt.received_at,
        delta_qty=evt.delta_qty,
        delta_price=evt.delta_price,
        cumulative_qty=evt.cumulative_qty,
        cumulative_avg_price=evt.cumulative_avg_price,
        note=evt.note,
        submitted_price=evt.submitted_price,
        submitted_quantity=evt.submitted_quantity,
    )


def instruction_to_out(inst: Instruction) -> InstructionOut:
    """Convert a StockInstruction or OptionInstruction to InstructionOut.

    Imports deferred to avoid circular imports at module load time.
    """
    from app.domain.instruction import OptionInstruction, StockInstruction

    if isinstance(inst, OptionInstruction):
        return InstructionOut(
            type="option",
            instruction_type=str(inst.instruction_type),
            price=inst.price,
            price_range=inst.price_range,
            quantity=inst.quantity,
            position_size=inst.position_size,
            stop_loss_price=inst.stop_loss_price,
            take_profit_price=inst.take_profit_price,
            context_source=inst.context_source,
            parser_notes=list(inst.parser_notes),
            referenced_lot_price=inst.referenced_lot_price,  # ← new
            ticker=inst.ticker,
            symbol=inst.symbol,
            sell_quantity=None,
            option_type=str(inst.option_type),
            strike=inst.strike,
            expiry=inst.expiry,
        )
    elif isinstance(inst, StockInstruction):
        return InstructionOut(
            type="stock",
            instruction_type=str(inst.instruction_type),
            price=inst.price,
            price_range=inst.price_range,
            quantity=inst.quantity,
            position_size=inst.position_size,
            stop_loss_price=inst.stop_loss_price,
            take_profit_price=inst.take_profit_price,
            context_source=inst.context_source,
            parser_notes=list(inst.parser_notes),
            referenced_lot_price=inst.referenced_lot_price,  # ← new
            ticker=inst.ticker,
            symbol=inst.symbol,
            sell_quantity=inst.sell_quantity,
            option_type=None,
            strike=None,
            expiry=None,
        )
    else:
        # Fallback for plain Instruction base (should rarely be used directly)
        return InstructionOut(
            type="unknown",
            instruction_type=str(inst.instruction_type),
            price=inst.price,
            price_range=inst.price_range,
            quantity=inst.quantity,
            position_size=inst.position_size,
            stop_loss_price=inst.stop_loss_price,
            take_profit_price=inst.take_profit_price,
            context_source=inst.context_source,
            parser_notes=list(inst.parser_notes),
            referenced_lot_price=inst.referenced_lot_price,  # ← new
        )


def _last_push_summary(events: list[PushEvent]) -> dict[str, Any]:
    """Snapshot the latest push event for the collapsed-card display.

    Caller must pass events ordered ASC by received_at (load_task and
    list_tasks both guarantee this). The latest cumulative/submitted
    values are what the broker last reported, so the card can show
    "really filled X@avg" or "post-modify Y×Z" instead of the original
    signal price/qty.
    """
    if not events:
        return {
            "last_cum_qty": None,
            "last_cum_avg_price": None,
            "last_submitted_price": None,
            "last_submitted_qty": None,
        }
    latest = events[-1]
    return {
        "last_cum_qty": latest.cumulative_qty,
        "last_cum_avg_price": latest.cumulative_avg_price,
        "last_submitted_price": latest.submitted_price,
        "last_submitted_qty": latest.submitted_quantity,
    }


def label_to_out(label: InstructionLabel) -> InstructionLabelOut:
    return InstructionLabelOut(
        verdict=label.verdict,
        corrected_payload=(
            CorrectedInstruction(**label.corrected_payload)
            if label.corrected_payload is not None
            else None
        ),
        updated_at=label.updated_at,
    )


def task_to_out(task: Task) -> TaskOut:
    """Convert a domain Task (with push events) to TaskOut.

    Field-drift guard: ``test_task_to_out_forwards_every_field`` walks
    ``TaskOut.model_fields`` and asserts every field round-trips —
    when adding a field here, also extend that test's exhaustive
    fixture so the contract stays locked.
    """
    return TaskOut(
        id=task.id,
        type=task.type,
        status=str(task.status),
        order_id=task.order_id,
        submit_order_type=task.submit_order_type,
        submit_order_context=task.submit_order_context,
        submit_quote_last_done=task.submit_quote_last_done,
        submit_price=task.submit_price,
        stage_timings=dict(task.stage_timings),
        created_at=task.created_at,
        updated_at=task.updated_at,
        reject_reason=task.reject_reason,
        message=message_to_out(task.message),
        instruction=instruction_to_out(task.instruction) if task.instruction is not None else None,
        push_events=[push_event_to_out(e) for e in task.push_events],
        **_last_push_summary(task.push_events),
        label=label_to_out(task.label) if task.label is not None else None,
    )


def task_to_summary(task: Task) -> TaskSummaryOut:
    """Convert a domain Task to TaskSummaryOut (push_events excluded).

    The four ``last_*`` summary fields ARE included — they're tiny scalars
    derived from the most recent push event, and the collapsed card needs
    them to show real fill/modify state without a per-card detail fetch.
    Callers from /api/tasks (list endpoint) populate ``task.push_events``
    with just the latest event so this serializer can read it.
    """
    return TaskSummaryOut(
        id=task.id,
        type=task.type,
        status=str(task.status),
        order_id=task.order_id,
        submit_order_type=task.submit_order_type,
        submit_order_context=task.submit_order_context,
        submit_quote_last_done=task.submit_quote_last_done,
        submit_price=task.submit_price,
        stage_timings=dict(task.stage_timings),
        created_at=task.created_at,
        updated_at=task.updated_at,
        reject_reason=task.reject_reason,
        message=message_to_out(task.message),
        instruction=instruction_to_out(task.instruction) if task.instruction is not None else None,
        **_last_push_summary(task.push_events),
        label=label_to_out(task.label) if task.label is not None else None,
    )


def whop_page_to_out(
    entry: WhopPageEntry,
    listener: WhopListener | None,
) -> WhopPageOut:
    """Build WhopPageOut from a (entry, listener) pair from registry.list_pages()."""
    settings_out = WhopPageSettingsOut(
        dedupe_processed_messages=entry.settings.dedupe_processed_messages,
        price_deviation_tolerance=entry.settings.price_deviation_tolerance,
        block_historical_messages=entry.settings.block_historical_messages,
        launch_headless=entry.settings.launch_headless,
        parser_version=entry.settings.parser_version,
        option_buy_quantity_enabled=entry.settings.option_buy_quantity_enabled,
        option_buy_quantity=entry.settings.option_buy_quantity,
        option_total_price_limit_enabled=entry.settings.option_total_price_limit_enabled,
        option_total_price_limit=entry.settings.option_total_price_limit,
        watched_senders=list(entry.settings.watched_senders),
        chat_card_max_msgs=entry.settings.chat_card_max_msgs,
        tickers=(
            {
                k: TickerConfigOut(trade_quantity=v.trade_quantity)
                for k, v in entry.settings.tickers.items()
            }
            if entry.settings.tickers is not None
            else None
        ),
    )
    if listener is not None:
        return WhopPageOut(
            id=entry.id,
            url=entry.url,
            source=entry.source,
            name=entry.name,
            added_at=entry.added_at,
            settings=settings_out,
            running=listener.running,
            started_at=listener.started_at,
            last_poll_at=listener.last_poll_at,
            messages_published=listener.messages_published,
            last_error=listener.last_error,
            parent_chat_id=entry.parent_chat_id,
        )
    return WhopPageOut(
        id=entry.id,
        url=entry.url,
        source=entry.source,
        name=entry.name,
        added_at=entry.added_at,
        settings=settings_out,
        running=False,
        started_at=None,
        last_poll_at=None,
        messages_published=0,
        last_error=None,
        parent_chat_id=entry.parent_chat_id,
    )


def tpair_row_to_out(row: TPairRow) -> TPairOut:
    """Convert a TPairRow into the API response model."""
    return TPairOut(
        id=row.id,
        ticker=row.ticker,
        symbol=row.symbol,
        buys=[TPairAllocation(**a) for a in (row.buys_json or [])],
        sells=[TPairAllocation(**a) for a in (row.sells_json or [])],
        profit=row.profit,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )
