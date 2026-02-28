"""
统一 Rich 终端日志管理器

支持三种输出模式：
1. Tag追加模式：标题行 + 动态追加子行（Live），支持嵌套缩进（sub-tag）
2. 交易流程模式：多阶段表格动态更新（Live），各阶段作为表格区段展示
3. 静态日志：单条日志直接打印

使用方式：
    from utils.rich_logger import get_logger

    logger = get_logger()

    # 1. Tag Live（动态追加）
    logger.tag_live_start("程序加载")
    logger.tag_live_append("程序加载", "长桥交易接口初始化")
    logger.tag_live_stop("程序加载")

    # 2. 静态日志
    logger.log("订单推送", "[BUY] symbol=...",
               details=["status=...", "price=..."])

    # 3. 交易流程（表格）
    logger.trade_start()
    logger.trade_stage("原始消息", rows=[("time", "..."), ("content", "...")])
    logger.trade_stage("解析消息", rows=[("symbol", "CAH...")])
    logger.trade_end()
"""
import threading
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Callable, Tuple

from rich import box
from rich.console import Console, Group
from rich.columns import Columns
from rich.live import Live
from rich.panel import Panel
from rich.spinner import Spinner
from rich.table import Table
from rich.text import Text

_TS_STYLE = "grey70"


def _display_width(s: str) -> int:
    """终端显示宽度：ASCII=1，CJK=2"""
    return len(s) + sum(1 for c in s if "\u4e00" <= c <= "\u9fff")


def _now_ts() -> str:
    now = datetime.now()
    return now.strftime("%Y-%m-%d %H:%M:%S") + f".{now.microsecond // 1000:03d}"


class _TagData:
    """Live tag 内部状态"""
    __slots__ = ("ts", "style", "lines", "show_spinner")

    def __init__(self, ts: str, style: str, show_spinner: bool):
        self.ts = ts
        self.style = style
        self.lines: List[tuple] = []  # (timestamp, content, level)
        self.show_spinner = show_spinner


class _TradeTableStage:
    """交易流程表格中一个阶段的数据"""
    __slots__ = ("tag", "rows", "tag_suffix", "tag_style", "diff_ms")

    def __init__(self, tag: str, rows: list, tag_suffix: str,
                 tag_style: str, diff_ms: int):
        self.tag = tag
        self.rows = rows
        self.tag_suffix = tag_suffix
        self.tag_style = tag_style
        self.diff_ms = diff_ms


class TradeLogFlow:
    """单个交易流程，由 dom_id 唯一标识"""
    __slots__ = ("dom_id", "base_time", "stages", "order_id")

    def __init__(self, dom_id: str, base_time: datetime):
        self.dom_id = dom_id
        self.base_time = base_time
        self.stages: List[_TradeTableStage] = []
        self.order_id: Optional[str] = None


class RichLogger:
    """
    统一 Rich 终端日志管理器

    线程安全：所有公开方法通过 RLock 保护，
    push 线程可安全调用 log() 向交易流程追加阶段。
    """

    def __init__(self, console: Optional[Console] = None):
        self._console = console or Console()
        self._lock = threading.RLock()

        # Tag Live 状态
        self._live: Optional[Live] = None
        self._live_tag: Optional[str] = None
        self._tags: Dict[str, _TagData] = {}

        # Trade flow 状态（支持多流程并行）
        self._trade_flows: Dict[str, TradeLogFlow] = {}
        self._order_to_dom: Dict[str, str] = {}
        self._current_dom_id: Optional[str] = None
        self._trade_live: Optional[Live] = None

    @property
    def console(self) -> Console:
        return self._console

    @staticmethod
    def timestamp() -> str:
        """当前时间戳 YYYY-MM-DD HH:MM:SS.mmm"""
        return _now_ts()

    # ================================================================
    #  Tag Live 模式（2.1 tag追加输出）
    # ================================================================

    def tag_live_start(self, tag: str, style: str = "bold yellow",
                       show_spinner: bool = True) -> None:
        """
        开始一个 Live tag 区域，在终端显示标题行 + spinner。
        后续通过 tag_live_append 追加子行，实时刷新。
        """
        with self._lock:
            ts = _now_ts()
            data = _TagData(ts=ts, style=style, show_spinner=show_spinner)
            self._tags[tag] = data
            self._live_tag = tag
            self._live = Live(
                self._render_tag(tag),
                refresh_per_second=6,
                console=self._console,
            )
            self._live.start()

    def tag_live_append(self, tag: str, content: str, level: int = 0) -> None:
        """
        向 Live tag 追加一行。

        Args:
            tag: 标签名
            content: 行内容（支持 rich markup）
            level: 缩进级别。0=一级（- timestamp content），1=二级（  - content）
        """
        with self._lock:
            data = self._tags.get(tag)
            if not data:
                self.log(tag, content)
                return
            ts = _now_ts()
            data.lines.append((ts, content, level))
            if self._live and self._live_tag == tag:
                self._live.update(self._render_tag(tag))

    def tag_live_stop(self, tag: str) -> None:
        """停止 Live tag，内容冻结在终端"""
        with self._lock:
            data = self._tags.get(tag)
            if data:
                data.show_spinner = False
            if self._live and self._live_tag == tag:
                if data:
                    self._live.update(self._render_tag(tag))
                self._live.stop()
                self._live = None
                self._live_tag = None

    def tag_live_get_data(self, tag: str) -> Optional[_TagData]:
        """获取 Live tag 的内部数据（供外部组件用于兼容 log_lines/log_refresh 模式）"""
        return self._tags.get(tag)

    def tag_live_refresh(self, tag: str) -> None:
        """手动刷新 Live tag（供外部组件用于兼容 log_refresh 回调模式）"""
        with self._lock:
            if self._live and self._live_tag == tag:
                self._live.update(self._render_tag(tag))

    def _render_tag(self, tag: str) -> Group:
        """渲染 Live tag 的 renderable"""
        data = self._tags[tag]
        header = Text.from_markup(
            f"[{_TS_STYLE}]{data.ts}[/{_TS_STYLE}] [{data.style}]\\[{tag}][/{data.style}]"
        )
        if data.show_spinner:
            header = Columns([header, Spinner("dots")], expand=False)
        parts = [header]
        for ts, line, level in data.lines:
            prefix = "    " + "  " * level + "- "
            if ts and level == 0:
                parts.append(Text.from_markup(
                    f"{prefix}[{_TS_STYLE}]{ts}[/{_TS_STYLE}] [dim white]{line}[/dim white]"
                ))
            else:
                parts.append(Text.from_markup(
                    f"{prefix}[dim white]{line}[/dim white]"
                ))
        return Group(*parts)

    # ================================================================
    #  静态日志输出
    # ================================================================

    def log(self, tag: str, header: str = "",
            details: Optional[List[str]] = None,
            tag_style: str = "bold yellow",
            detail_style: str = "dim white",
            header_extra: Optional[List[str]] = None) -> None:
        """
        输出一条静态日志（不参与交易流程表格）。
        交易流程中请使用 trade_stage() 添加阶段到表格。

        格式：
            timestamp [tag] header header_extra[0] header_extra[1] ...
                             detail1
                             detail2

        Args:
            tag: 标签名，如 "订单推送", "持仓更新"
            header: 标签后的主内容
            details: 缩进详情行列表
            tag_style: 标签的 rich style
            detail_style: 详情行的 rich style；空字符串表示行自带 markup
            header_extra: 标题行额外元素（追加在 header 后面，空格分隔）
        """
        with self._lock:
            self._print_log(tag, header, details, tag_style, detail_style, header_extra)

    def _print_log(self, tag: str, header: str,
                   details: Optional[List[str]],
                   tag_style: str, detail_style: str,
                   header_extra: Optional[List[str]] = None) -> None:
        """直接打印一条日志到终端（无 Live）"""
        ts = _now_ts()
        tag_display = f"[{tag}]"
        indent = " " * (len(ts) + 1 + _display_width(tag_display) + 1)

        parts = [
            f"[{_TS_STYLE}]{ts}[/{_TS_STYLE}]",
            f"[{tag_style}]\\[{tag}][/{tag_style}]",
        ]
        if header:
            parts.append(header)
        for extra in (header_extra or []):
            if extra:
                parts.append(extra)
        self._console.print(*parts)

        for line in (details or []):
            if detail_style:
                self._console.print(f"{indent}[{detail_style}]{line}[/{detail_style}]")
            else:
                self._console.print(f"{indent}{line}")
        self._console.print()

    def log_nested(self, tag: str, title_suffix: str = "",
                   lines: Optional[List[str]] = None,
                   sub_lines: Optional[Dict[int, List[str]]] = None,
                   tag_style: str = "bold cyan",
                   line_formatter: Optional[Callable[[str], str]] = None) -> None:
        """
        输出带嵌套子项的 tag 区块（如 [长桥数据]、[账户持仓]）。

        Args:
            tag: 标签名
            title_suffix: 标题行后附加文字
            lines: 一级行列表
            sub_lines: {行索引: [子行列表]} 的嵌套关系
            tag_style: 标签样式
            line_formatter: 自定义行格式化函数
        """
        ts = _now_ts()
        suffix = f" {title_suffix}" if title_suffix else ""
        self._console.print(
            f"[{_TS_STYLE}]{ts}[/{_TS_STYLE}]",
            f"[{tag_style}]\\[{tag}][/{tag_style}]",
            suffix if suffix.strip() else "",
        )
        sub_lines = sub_lines or {}
        for i, line in enumerate(lines or []):
            if line_formatter:
                self._console.print(line_formatter(line))
            else:
                self._format_kv_line(line, prefix="    - ")
            for sub in sub_lines.get(i, []):
                self._format_kv_line(sub, prefix="      - ")
        self._console.print()

    def _format_kv_line(self, line: str, prefix: str = "    - ") -> None:
        """格式化键值对行：key：value 或 key: value"""
        sep = "：" if "：" in line else (":" if ":" in line else "")
        if sep:
            key, _, value = line.partition(sep)
            self._console.print(
                f"{prefix}[yellow]{key}{sep}[/yellow][blue]{value}[/blue]"
            )
        else:
            self._console.print(f"{prefix}[dim white]{line}[/dim white]")

    def log_config(self, tag: str, lines: List[str],
                   tag_style: str = "bold yellow") -> None:
        """
        输出配置类 tag 区块（如 [配置更新]），支持键值对高亮和特殊行样式。
        """
        ts = _now_ts()
        self._console.print(
            f"[{_TS_STYLE}]{ts}[/{_TS_STYLE}]",
            f"[{tag_style}]\\[{tag}][/{tag_style}]",
        )
        for line in lines:
            if line.strip().startswith("⚠️"):
                self._console.print(f"    [bold red]{line}[/bold red]")
            elif "：" in line:
                key, _, value = line.partition("：")
                ks = key.strip()
                vs = value.strip()
                if ks == "账户类型" and vs == "真实":
                    self._console.print(
                        f"    - [yellow]{key}：[/yellow][bold red]{value}[/bold red]"
                    )
                elif ks == "Dry Run 模式":
                    if "开启" in vs:
                        self._console.print(
                            f"    - [yellow]{key}：[/yellow]"
                            f"[bold yellow]{value}[/bold yellow] "
                            f"[dim](不实际下单)[/dim]"
                        )
                    else:
                        self._console.print(
                            f"    - [yellow]{key}：[/yellow][bold red]{value}[/bold red]"
                        )
                else:
                    self._console.print(
                        f"    - [yellow]{key}：[/yellow][blue]{value}[/blue]"
                    )
            elif ":" in line:
                key, _, value = line.partition(":")
                self._console.print(
                    f"    - [yellow]{key}:[/yellow][blue]{value}[/blue]"
                )
            else:
                self._console.print(f"    - [dim white]{line}[/dim white]")
        self._console.print()

    def separator(self) -> None:
        """输出分隔线"""
        self._console.print("=" * 80)

    # ================================================================
    #  交易流程模式（2.2 交易输出 - 表格）
    # ================================================================

    def _ensure_trade_live(self) -> None:
        """确保共享 Live 实例已启动"""
        if self._trade_live is None:
            self._trade_live = Live(
                Text(""),
                refresh_per_second=10,
                console=self._console,
            )
            self._trade_live.start()

    def _update_trade_display(self) -> None:
        """用所有活跃流程更新 Live 显示"""
        if self._trade_live:
            panels = [self._render_trade_panel(f) for f in self._trade_flows.values()]
            self._trade_live.update(Group(*panels) if panels else Text(""))

    def _maybe_stop_trade_live(self) -> None:
        """如果没有活跃流程则关闭 Live"""
        if not self._trade_flows and self._trade_live:
            self._trade_live.stop()
            self._trade_live = None
            self._console.print()

    def trade_start(self, dom_id: Optional[str] = None) -> None:
        """
        开始一个新的交易流程。
        dom_id 为流程唯一标识（通常为消息 domID），若省略则自动生成。
        多个流程可并行存在，共享同一个 Live 实例。
        """
        with self._lock:
            if dom_id is None:
                dom_id = f"_auto_{id(self)}_{len(self._trade_flows)}"

            if dom_id in self._trade_flows:
                old = self._trade_flows[dom_id]
                if old.order_id and old.order_id in self._order_to_dom:
                    del self._order_to_dom[old.order_id]

            flow = TradeLogFlow(dom_id=dom_id, base_time=datetime.now())
            self._trade_flows[dom_id] = flow
            self._current_dom_id = dom_id
            self._ensure_trade_live()
            self._update_trade_display()

    def trade_stage(self, tag: str,
                    rows: Optional[List[Tuple[str, str]]] = None,
                    tag_suffix: str = "",
                    tag_style: str = "bold cyan",
                    dom_id: Optional[str] = None) -> None:
        """
        添加交易流程阶段。无活跃交易流程时回退为静态日志。

        Args:
            tag: 阶段名称（如 "原始消息", "解析消息"）
            rows: 键值对列表 [(key, value), ...]，支持 3-tuple (key, value, style)
            tag_suffix: 标签后缀（如 "[模拟]"）
            tag_style: 标签 rich 样式
            dom_id: 目标流程 ID，省略则使用当前活跃流程
        """
        with self._lock:
            target_id = dom_id or self._current_dom_id
            flow = self._trade_flows.get(target_id) if target_id else None

            if flow is None:
                details = []
                for row in (rows or []):
                    k, v = row[0], row[1]
                    if k:
                        details.append(f"[yellow]{k}[/yellow]: {v}")
                    else:
                        details.append(str(v))
                self._print_log(tag, tag_suffix, details, tag_style, "", None)
                return

            now = datetime.now()
            diff_ms = int((now - flow.base_time).total_seconds() * 1000)

            stage = _TradeTableStage(
                tag=tag, rows=rows or [], tag_suffix=tag_suffix,
                tag_style=tag_style, diff_ms=diff_ms,
            )
            flow.stages.append(stage)
            self._update_trade_display()

    def trade_end(self, dom_id: Optional[str] = None) -> None:
        """结束交易流程。若已注册 order_id 则保持 Live 等待推送更新。"""
        with self._lock:
            target_id = dom_id or self._current_dom_id
            flow = self._trade_flows.get(target_id) if target_id else None
            if flow is None:
                return

            self._update_trade_display()

            if flow.order_id:
                if target_id == self._current_dom_id:
                    self._current_dom_id = None
                return

            panel = self._render_trade_panel(flow)

            if flow.order_id and flow.order_id in self._order_to_dom:
                del self._order_to_dom[flow.order_id]
            del self._trade_flows[target_id]
            if target_id == self._current_dom_id:
                self._current_dom_id = None

            if not self._trade_flows:
                self._maybe_stop_trade_live()
            else:
                self._console.print(panel)
                self._update_trade_display()

    def trade_register_order(self, order_id: str, dom_id: Optional[str] = None) -> None:
        """注册订单 ID 到指定流程，trade_end() 时保持 Live 活跃。"""
        with self._lock:
            target_id = dom_id or self._current_dom_id
            flow = self._trade_flows.get(target_id) if target_id else None
            if flow:
                flow.order_id = order_id
                self._order_to_dom[order_id] = flow.dom_id

    def trade_push_update(self, order_id: str,
                          rows: Optional[List[Tuple[str, str]]] = None,
                          tag_style: str = "bold white",
                          terminal: bool = False) -> None:
        """
        根据 order_id 找到对应交易流程并追加订单推送阶段。

        Args:
            order_id: 订单 ID
            rows: 推送详情键值对
            tag_style: 标签样式
            terminal: 是否为终态（Filled/Rejected），True 时结束 Live
        """
        with self._lock:
            target_id = self._order_to_dom.get(order_id)
            flow = self._trade_flows.get(target_id) if target_id else None

            if flow is None or self._trade_live is None:
                return

            now = datetime.now()
            diff_ms = int((now - flow.base_time).total_seconds() * 1000)

            stage = _TradeTableStage(
                tag="订单推送", rows=rows or [], tag_suffix="",
                tag_style=tag_style, diff_ms=diff_ms,
            )
            existing_idx = next(
                (i for i in range(len(flow.stages) - 1, -1, -1)
                 if flow.stages[i].tag == "订单推送"),
                -1,
            )
            if existing_idx >= 0:
                flow.stages[existing_idx] = stage
            else:
                flow.stages.append(stage)
            self._update_trade_display()

            if terminal:
                panel = self._render_trade_panel(flow)
                del self._order_to_dom[order_id]
                del self._trade_flows[target_id]
                if not self._trade_flows:
                    self._maybe_stop_trade_live()
                else:
                    self._console.print(panel)
                    self._update_trade_display()

    @property
    def in_trade_flow(self) -> bool:
        """是否有活跃交易流程"""
        return bool(self._trade_flows)

    @property
    def has_pending_order(self) -> bool:
        """是否有等待推送的订单"""
        return bool(self._order_to_dom)

    # ================================================================
    #  账户持仓表格
    # ================================================================

    def print_position_table(self, title: Optional[str],
                             positions: List[dict],
                             account: Optional[dict] = None,
                             config_lines: Optional[List[str]] = None) -> None:
        """
        输出账户持仓表格（单列外层嵌套内层表格，标题行全宽显示）。

        Args:
            title: 可选表格标题（支持 rich markup）
            positions: 持仓数据列表，每项包含:
                - symbol, quantity, unit, avg_cost, position_value, pct
                - stop_loss: Optional[float]
                - records: list[dict] 交易记录
            account: 可选账户摘要 dict (available_cash, cash, total_assets, is_paper)
            config_lines: 可选配置信息列表（键值对字符串，如 "账户类型：模拟"）
        """
        with self._lock:
            outer = Table(
                title=title,
                title_style="" if title else None,
                show_header=False,
                box=box.ROUNDED,
                border_style="dim",
                expand=False,
                padding=(0, 1),
            )
            outer.add_column()

            if config_lines:
                cfg_header = Text.from_markup("[bold blue]配置信息[/bold blue]")
                cfg_header.justify = "center"
                outer.add_row(cfg_header)
                outer.add_section()

                cfg = Table(
                    show_header=False, box=None,
                    padding=0, pad_edge=False, expand=True,
                )
                cfg.add_column(style="yellow", no_wrap=True)
                cfg.add_column()
                for line in config_lines:
                    sep = "：" if "：" in line else (":" if ":" in line else "")
                    if sep:
                        key, _, value = line.partition(sep)
                        if key.strip() == "账户类型" and "真实" in value:
                            cfg.add_row(key, Text.from_markup(f"[bold red]{value}[/bold red]"))
                        elif key.strip() == "Dry Run 模式" and "开启" in value:
                            cfg.add_row(key, Text.from_markup(
                                f"[bold yellow]{value}[/bold yellow] [dim](不实际下单)[/dim]"
                            ))
                        elif key.strip() == "Dry Run 模式":
                            cfg.add_row(key, Text.from_markup(f"[bold red]{value}[/bold red]"))
                        else:
                            cfg.add_row(key, value)
                    elif line.strip().startswith("⚠️"):
                        cfg.add_row(Text.from_markup(f"[bold red]{line}[/bold red]"), "")
                    else:
                        cfg.add_row(line, "")
                outer.add_row(cfg)
                outer.add_section()

            if account is not None:
                is_paper = account.get("is_paper", True)
                mode_label = "\\[模拟]" if is_paper else "\\[真实]"
                mode_style = "bold grey70" if is_paper else "bold green"
                header_text = Text.from_markup(
                    f"[bold blue]账户持仓[/bold blue] [{mode_style}]{mode_label}[/{mode_style}]"
                )
                header_text.justify = "center"
                outer.add_row(header_text)
                outer.add_section()

                acct = Table(
                    show_header=False, box=None,
                    padding=0, pad_edge=False, expand=True,
                )
                acct.add_column(style="yellow", no_wrap=True)
                acct.add_column(justify="right")
                acct.add_row(
                    "总资产",
                    Text.from_markup(f"[bold]${account.get('total_assets', 0):,.2f}[/bold]"),
                )
                acct.add_row("可用现金", f"${account.get('available_cash', 0):,.2f}")
                acct.add_row("现金", f"${account.get('cash', 0):,.2f}")
                outer.add_row(acct)
                outer.add_section()

            pos_header = Text.from_markup("[bold blue]股票仓位[/bold blue]")
            pos_header.justify = "center"
            outer.add_row(pos_header)
            outer.add_section()

            pos_table = Table(
                show_header=True, box=box.HORIZONTALS,
                padding=(0, 1), pad_edge=False, expand=True,
                header_style="bold",
                show_edge=False,
                border_style="dim",
            )
            pos_table.add_column("股票", no_wrap=True, style="bold")
            pos_table.add_column("仓位", justify="right", style="bold")
            pos_table.add_column("价格", justify="right", style="bold")
            pos_table.add_column("总价", justify="right", style="bold")
            pos_table.add_column("占比", justify="right", style="bold")

            for i, pos in enumerate(positions):
                sym = pos["symbol"]
                qty = pos["quantity"]
                unit = pos.get("unit", "股")
                cost = pos["avg_cost"]
                value = pos["position_value"]
                pct = pos["pct"]
                sl = pos.get("stop_loss")

                sl_str = f" 止损=${sl}" if sl else ""
                pos_table.add_row(
                    sym,
                    f"{qty}{unit}",
                    f"${cost:.3f}",
                    f"${value:,.2f}",
                    f"{pct:.1f}%{sl_str}",
                )

                for rec in pos.get("records", []):
                    rec_ts = rec.get("submitted_at", "")
                    if isinstance(rec_ts, str) and len(rec_ts) >= 10:
                        rec_ts = rec_ts[5:10]
                    side = rec.get("side", "BUY")
                    side_pad = side.ljust(4)[:4]
                    side_tag = f"[{side_pad}]"
                    side_rich = (f"[green]{side_tag}[/green]"
                                 if side == "BUY"
                                 else f"[yellow]{side_tag}[/yellow]")
                    r_qty = rec.get("qty", 0)
                    r_price = rec.get("price", "-")
                    pos_table.add_row(
                        Text.from_markup(
                            f"[dim]  {rec_ts} {side_rich} {r_qty} @{r_price}[/dim]"
                        ),
                        "", "", "", "",
                    )

                if i < len(positions) - 1:
                    pos_table.add_section()

            outer.add_row(pos_table)
            self._console.print(outer)
            self._console.print()

    def _render_trade_panel(self, flow: TradeLogFlow) -> Table:
        """渲染单个交易流程为带边框的单列表格"""
        outer = Table(
            show_header=False, box=box.ROUNDED, border_style="dim",
            expand=False, padding=(0, 1),
        )
        outer.add_column()

        for i, stage in enumerate(flow.stages):
            stage_parts: list = []

            stage_ts = ""
            if flow.base_time:
                st = flow.base_time + timedelta(milliseconds=stage.diff_ms)
                stage_ts = st.strftime("%Y-%m-%d %H:%M:%S") + f".{st.microsecond // 1000:03d}"

            header_elems: list = []
            if stage_ts:
                header_elems.append(f"[{_TS_STYLE}]{stage_ts}[/{_TS_STYLE}]")

            if stage.diff_ms > 0:
                if stage.diff_ms < 1000:
                    header_elems.append(f"[green]\\[+{stage.diff_ms}ms][/green]")
                elif stage.diff_ms < 3000:
                    header_elems.append(f"[yellow]\\[+{stage.diff_ms}ms][/yellow]")
                else:
                    header_elems.append(f"[bold yellow]\\[+{stage.diff_ms}ms][/bold yellow]")
            elif stage.tag_suffix:
                header_elems.append(stage.tag_suffix)

            header_elems.append(f"[bold blue]{stage.tag}[/bold blue]")

            if stage.diff_ms > 0 and stage.tag_suffix:
                header_elems.append(f"[dim]{stage.tag_suffix}[/dim]")

            stage_parts.append(Text.from_markup(f"[bold]{' '.join(header_elems)}[/bold]"))

            if stage.rows:
                current_detail: Optional[Table] = None

                def _flush_detail():
                    nonlocal current_detail
                    if current_detail is not None:
                        stage_parts.append(current_detail)
                        current_detail = None

                def _ensure_detail():
                    nonlocal current_detail
                    if current_detail is None:
                        current_detail = Table(
                            show_header=False, box=None,
                            padding=0, pad_edge=False, expand=True,
                        )
                        current_detail.add_column(no_wrap=True)
                        current_detail.add_column(ratio=1, overflow="fold")

                for row in stage.rows:
                    key, value = row[0], row[1]
                    row_style = row[2] if len(row) > 2 else ""

                    if key:
                        _ensure_detail()
                        if row_style == "dim":
                            current_detail.add_row(
                                Text.from_markup(f"[dim]  - {key}:[/dim]"),
                                Text.from_markup(f"[dim] {value}[/dim]"),
                            )
                        else:
                            current_detail.add_row(
                                Text.from_markup(f"  - [yellow]{key}[/yellow]:"),
                                Text.from_markup(f" {value}"),
                            )
                    else:
                        _flush_detail()
                        if row_style == "dim":
                            stage_parts.append(Text.from_markup(f"[dim]  - {value}[/dim]"))
                        else:
                            stage_parts.append(Text.from_markup(f"  - {value}"))

                _flush_detail()

            outer.add_row(Group(*stage_parts))
            if i < len(flow.stages) - 1:
                outer.add_section()

        return outer


# ================================================================
#  Singleton
# ================================================================

_logger_instance: Optional[RichLogger] = None


def get_logger() -> RichLogger:
    """获取全局 RichLogger 单例"""
    global _logger_instance
    if _logger_instance is None:
        _logger_instance = RichLogger()
    return _logger_instance


def set_logger(logger: RichLogger) -> None:
    """替换全局 RichLogger 单例（测试用）"""
    global _logger_instance
    _logger_instance = logger


def reset_logger() -> None:
    """重置全局 logger（测试用）"""
    global _logger_instance
    _logger_instance = None
