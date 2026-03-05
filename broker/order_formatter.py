"""
订单输出格式化工具
提供彩色表格展示订单信息
"""
from typing import Dict, List, Optional, Tuple
from rich.console import Console, Group
from rich.columns import Columns
from rich.table import Table
from rich.text import Text
from rich.live import Live
from rich.spinner import Spinner
from rich import box
import re
from datetime import datetime

console = Console()


def _display_width(s: str) -> int:
    """终端显示宽度：ASCII=1，CJK=2。"""
    return len(s) + sum(1 for c in s if "\u4e00" <= c <= "\u9fff")


def _format_time_with_diff(timestamp_str: str, now: datetime) -> tuple:
    """返回 (显示时间，去掉 T 且毫秒 3 位；[+Nms] 的 rich 片段，<200ms 绿否则黄)。"""
    if not timestamp_str:
        return "", ""
    t = timestamp_str.replace("T", " ", 1).strip()
    if "." in t:
        idx = t.rfind(".")
        t = t[: idx + 4] if len(t) > idx + 4 else t
    try:
        s = (timestamp_str or "").replace("T ", "T").strip()[:23]
        if len(s) >= 19:
            parsed = datetime.fromisoformat(s)
            diff_ms = int((now - parsed).total_seconds() * 1000)
            sign = "+" if diff_ms >= 0 else ""
            ms_tag = f"[{sign}{diff_ms}ms]"
            if abs(diff_ms) < 1000:
                ms_rich = f"[green]{ms_tag}[/green]"
            else:
                ms_rich = f"[yellow]{ms_tag}[/yellow]"
        else:
            ms_rich = ""
    except Exception:
        ms_rich = ""
    return t, ms_rich


def print_order_submitting_display(order: Dict, multiplier: int = 100) -> None:
    """在调用 submit_order 之前展示「提交订单」阶段（时间点为即将提交），不包含 order_id。"""
    from utils.rich_logger import get_logger
    logger = get_logger()
    symbol = order.get("symbol", "")
    mode = order.get("mode", "paper")
    mode_str = "模拟" if mode in ("paper", "dry_run") else "真实"
    side = order.get("side", "")
    price = order.get("price")
    quantity = int(order.get("quantity") or 0)
    total = (float(price) if price else 0) * quantity * multiplier
    summary = f"[green]\\[{side}][/green] {symbol}"
    if price is not None:
        summary += f" ${price} × {quantity} = [bold green]${total:.2f}[/bold green]"
    logger.trade_stage("提交订单", rows=[("", summary)],
                       tag_suffix=f"\\[{mode_str}]", tag_style="bold green")


def print_order_push_submitted_display(order: Dict, multiplier: int = 100) -> None:
    """submit_order 返回后调用：注册 order_id 并更新「订单推送」行为已提交。"""
    from utils.rich_logger import get_logger
    logger = get_logger()
    order_id = order.get("order_id")
    if not order_id:
        return
    logger.trade_register_order(str(order_id))
    symbol = order.get("symbol", "")
    side = order.get("side", "")
    price = order.get("price")
    quantity = int(order.get("quantity") or 0)
    total = (float(price) if price else 0) * quantity * multiplier
    summary = f"[green]\\[{side}][/green] {symbol}"
    if price is not None:
        summary += f" ${price} × {quantity} = [bold green]${total:.2f}[/bold green]"
    logger.trade_push_update(
        str(order_id),
        rows=[("OrderID", f"[dim]{order_id}[/dim]"), ("", summary)],
        tag_suffix="[green]已提交[/green]",
        tag_style="bold white",
        terminal=False,
    )


def print_order_submitted_display(order: Dict, multiplier: int = 100) -> None:
    """按表格格式输出订单提交成功信息（股票等：提交后展示，含 order_id）。期权买入已改为提交前展示 + 订单推送已提交。"""
    from utils.rich_logger import get_logger
    logger = get_logger()
    symbol = order.get("symbol", "")
    mode = order.get("mode", "paper")
    mode_str = "模拟" if mode in ("paper", "dry_run") else "真实"
    side = order.get("side", "")
    price = order.get("price")
    quantity = int(order.get("quantity") or 0)
    total = (float(price) if price else 0) * quantity * multiplier
    order_id = order.get("order_id")
    rows = []
    if order_id:
        rows.append(("OrderID", f"[dim]{order_id}[/dim]"))
    summary = f"[green]\\[{side}][/green] {symbol}"
    if price is not None:
        summary += f" ${price} × {quantity} = [bold green]${total:.2f}[/bold green]"
    rows.append(("", summary))
    logger.trade_stage("提交订单", rows=rows,
                       tag_suffix=f"\\[{mode_str}]", tag_style="bold green")
    if order_id:
        logger.trade_register_order(str(order_id))


def _parse_detail_rows(lines: List[str], reject_reason: Optional[str] = None,
                       style: str = "dim") -> list:
    """将详情行列表解析为 (key, value[, style]) 行，供 trade_stage 使用。"""
    rows: list = []
    for line in (lines or []):
        if "：" in line:
            k, _, v = line.partition("：")
            rows.append((k.strip(), v.strip(), style) if style else (k.strip(), v.strip()))
        elif ": " in line:
            k, _, v = line.partition(": ")
            rows.append((k.strip(), v.strip(), style) if style else (k.strip(), v.strip()))
        else:
            rows.append(("", line, style) if style else ("", line))
    if reject_reason:
        rows.append(("", f"[bold red]{reject_reason}[/bold red]"))
    return rows


def print_order_validation_display(
    side: str,
    symbol: str,
    price: float,
    price_line: str,
    quantity_line: str,
    total_line: str,
    instruction_timestamp: Optional[str] = None,
    reject_reason: Optional[str] = None,
    stop_loss_line: Optional[str] = None,
    expiry_fallback_time: bool = False,
) -> None:
    """提交订单前校验结束后统一输出。"""
    from utils.rich_logger import get_logger
    logger = get_logger()

    rows: List[Tuple[str, str]] = []
    if expiry_fallback_time:
        rows.append(("", "[bold yellow]注意：消息未获取到时间，使用当前时间计算到期日[/bold yellow]"))

    detail_lines = [price_line, quantity_line, total_line]
    if stop_loss_line:
        detail_lines.append(stop_loss_line)
    rows.extend(_parse_detail_rows(detail_lines, reject_reason))
    logger.trade_stage("订单校验", rows=rows, tag_style="bold yellow")


def print_timing_breakdown_display(
    quote_ms: float,
    balance_ms: float,
    submit_total_ms: float,
    submit_api_ms: Optional[float] = None,
) -> None:
    """在提交订单后输出耗时分析阶段，便于优化。"""
    from utils.rich_logger import get_logger
    logger = get_logger()

    rows: List[Tuple[str, str]] = [
        ("查询报价", f"[dim]{quote_ms:.0f}ms[/dim]"),
        ("账户余额", f"[dim]{balance_ms:.0f}ms[/dim]"),
    ]
    if submit_api_ms is not None:
        # 发单到长桥并收到响应的耗时（含网络 RTT + 券商处理）
        rows.append(("提交API(发单→券商→响应)", f"[dim]{submit_api_ms:.0f}ms[/dim]"))
        other_ms = submit_total_ms - submit_api_ms
        if other_ms > 0:
            rows.append(("提交后处理", f"[dim]{other_ms:.0f}ms[/dim]"))
    rows.append(("提交总耗时", f"[bold]{submit_total_ms:.0f}ms[/bold]"))
    total_ms = quote_ms + balance_ms + submit_total_ms
    rows.append(("合计", f"[bold]{total_ms:.0f}ms[/bold]"))
    logger.trade_stage("耗时分析", rows=rows, tag_style="dim")


def print_position_update_display(message: str) -> None:
    """持仓更新展示：[持仓更新] 紫色加粗。"""
    from utils.rich_logger import get_logger
    logger = get_logger()
    logger.log("持仓更新", message, tag_style="bold magenta")


def print_program_load_display(lines: List[str]) -> None:
    """
    程序加载展示，与 print_order_validation_display 同风格：
    {时间} [程序加载]
        - {时间} 长桥交易接口初始化
        - ...
    """
    now = datetime.now()
    ts = now.strftime("%Y-%m-%d %H:%M:%S") + f".{now.microsecond // 1000:03d}"
    console.print(
        f"[{_TS_STYLE}]{ts}[/{_TS_STYLE}]",
        "[bold yellow][程序加载][/bold yellow]",
    )
    for line in lines:
        console.print(f"    - [{_TS_STYLE}]{ts}[/{_TS_STYLE}] [dim white]{line}[/dim white]")
    console.print()


def print_config_update_display(lines: List[str]) -> None:
    """配置更新展示。"""
    from utils.rich_logger import get_logger
    logger = get_logger()
    logger.log_config("配置更新", lines)


def print_longbridge_data_display(lines: List[str]) -> None:
    """长桥 API 数据同步展示，支持两级缩进。"""
    if not lines:
        return
    from utils.rich_logger import get_logger
    logger = get_logger()

    top_lines = []
    sub_map: Dict[int, List[str]] = {}
    idx = -1
    for line in lines:
        if line.startswith("  - "):
            sub_map.setdefault(idx, []).append(line[4:])
        else:
            idx += 1
            top_lines.append(line)

    logger.log_nested("长桥数据", lines=top_lines, sub_lines=sub_map,
                      tag_style="bold cyan")


def web_listen_timestamp() -> str:
    """当前时间戳，用于程序加载/网页监听每条子条目（与 block 标题同格式）。"""
    now = datetime.now()
    return now.strftime("%Y-%m-%d %H:%M:%S") + f".{now.microsecond // 1000:03d}"


# 时间戳样式：用 grey70 显式灰色，避免在部分终端里 [dim] 显示为白色
_TS_STYLE = "grey70"


def _render_live_block(
    lines: List[Tuple[str, str]],
    block_ts: str,
    title: str,
    show_spinner: bool = False,
):
    """供 rich.Live 使用的可刷新块：标题行 block_ts + title，每条子条目 (ts, line)。"""
    header = Text.from_markup(f"[{_TS_STYLE}]{block_ts}[/{_TS_STYLE}] [bold yellow]{title}[/bold yellow]")
    if show_spinner:
        header = Columns([header, Spinner("dots")], expand=False)
    parts = [header]
    for ts, line in lines:
        parts.append(Text.from_markup(f"    - [{_TS_STYLE}]{ts}[/{_TS_STYLE}] [dim white]{line}[/dim white]"))
    return Group(*parts)


def render_program_load_live(
    lines: List[Tuple[str, str]],
    block_ts: str,
    show_spinner: bool = False,
):
    """[程序加载] 流式块，含交易初始化与网页监听等全部子条目。"""
    return _render_live_block(lines, block_ts, "[程序加载]", show_spinner)


def render_web_listen_live(
    lines: List[Tuple[str, str]],
    block_ts: str,
    show_spinner: bool = False,
):
    """
    供 rich.Live 使用的 [网页监听] 可刷新渲染体。
    标题行显示 block_ts + [网页监听]；每条子条目为 (ts, line)，显示该条发生时间。
    """
    return _render_live_block(lines, block_ts, "[网页监听]", show_spinner)


def print_web_listen_display(lines: List[Tuple[str, str]]) -> None:
    """
    网页监听展示。lines 为 (ts, line) 列表，每条显示该条发生时间。
    """
    block_ts = web_listen_timestamp() if not lines else lines[0][0]
    console.print(
        f"[{_TS_STYLE}]{block_ts}[/{_TS_STYLE}]",
        "[bold yellow][网页监听][/bold yellow]",
    )
    for ts, line in lines:
        console.print(f"    - [{_TS_STYLE}]{ts}[/{_TS_STYLE}] [dim white]{line}[/dim white]")
    console.print()


def print_sell_validation_display(
    symbol: str,
    quantity: int,
    instruction_timestamp: Optional[str] = None,
    detail_lines: Optional[List[str]] = None,
    reject_reason: Optional[str] = None,
) -> None:
    """卖出订单校验展示。"""
    from utils.rich_logger import get_logger
    logger = get_logger()

    rows = _parse_detail_rows(detail_lines or [], reject_reason)
    logger.trade_stage("订单校验", rows=rows, tag_style="bold yellow")


def print_modify_validation_display(
    symbol: str,
    instruction_timestamp: Optional[str] = None,
    detail_lines: Optional[List[str]] = None,
    reject_reason: Optional[str] = None,
) -> None:
    """修改指令（止盈止损）校验展示。"""
    from utils.rich_logger import get_logger
    logger = get_logger()

    rows = _parse_detail_rows(detail_lines or [], reject_reason)
    logger.trade_stage("订单校验", rows=rows, tag_style="bold yellow")


def print_close_validation_display(
    symbol: str,
    quantity: int,
    instruction_timestamp: Optional[str] = None,
    detail_lines: Optional[List[str]] = None,
    reject_reason: Optional[str] = None,
) -> None:
    """清仓订单校验展示。"""
    from utils.rich_logger import get_logger
    logger = get_logger()

    rows = _parse_detail_rows(detail_lines or [], reject_reason)
    logger.trade_stage("订单校验", rows=rows, tag_style="bold yellow")


def parse_option_symbol(symbol: str) -> str:
    """
    解析期权代码为语义化名称
    
    格式：TICKER + YYMMDD + C/P + 价格.US，价格为行权价×1000 不补零
    
    Args:
        symbol: 期权代码，如 "EOSE260109C13500.US" 或 "AAPL260207C250000.US"
    
    Returns:
        语义化名称，如 "EOS 260109 $13.5 CALL"
    """
    # 如果不是期权格式，直接返回原名称
    if not symbol or len(symbol) < 12:
        return symbol
    
    # 匹配期权代码格式：TICKER + YYMMDD + C/P + PRICE（行权价×1000，不补零）.US
    pattern = r'^([A-Z]+)(\d{6})([CP])(\d+)'
    match = re.match(pattern, symbol)
    
    if not match:
        return symbol
    
    ticker = match.group(1)      # AAPL
    date_str = match.group(2)    # 260207
    option_type = match.group(3) # C or P
    price_str = match.group(4)   # 行权价×1000，如 13500、250000
    
    # 解析日期（保持原格式 YYMMDD）
    formatted_date = date_str
    
    # 解析价格（除以1000）
    try:
        price = int(price_str) / 1000
        # 如果是整数，不显示小数点
        if price == int(price):
            formatted_price = f"${int(price)}"
        else:
            formatted_price = f"${price:.2f}".rstrip('0').rstrip('.')
    except:
        formatted_price = f"${price_str}"
    
    # 期权类型
    option_type_name = "CALL" if option_type == "C" else "PUT"
    
    return f"{ticker} {formatted_date} {formatted_price} {option_type_name}"


def format_side(side: str) -> Text:
    """
    格式化操作方向
    
    Args:
        side: BUY/SELL/CANCEL/SEARCH
    
    Returns:
        带颜色的 Text 对象
    """
    side_upper = side.upper()
    if side_upper == "BUY":
        return Text(side_upper, style="bold green")
    elif side_upper == "SELL":
        return Text(side_upper, style="bold red")
    elif side_upper == "CANCEL":
        return Text(side_upper, style="bold yellow")
    elif side_upper == "SEARCH":
        return Text(side_upper, style="bold blue")
    else:
        return Text(side_upper, style="white")


def format_price(price: Optional[float], market_text: str = "市价单") -> str:
    """
    格式化期权价格显示（仅单价）
    
    Args:
        price: 单价
        market_text: 市价单的显示文本（默认"市价单"）
    
    Returns:
        格式化的价格字符串，如 "$5.00" 或 "市价单"
    """
    if price is None or price == 0:
        return market_text
    
    return f"${price:.2f}"


def format_total_value(price: Optional[float], quantity: int = 1, multiplier: int = 100, style: str = "bold cyan") -> Text:
    """
    格式化期权合约总价值（单价 x 数量 x 合约乘数）
    
    Args:
        price: 单价
        quantity: 数量（默认 1）
        multiplier: 合约乘数（默认 100）
        style: 文本样式（默认 "bold cyan" 蓝色粗体）
    
    Returns:
        带颜色的 Text 对象，如 "$500.00" (蓝色)
    """
    if price is None or price == 0:
        return Text("-", style="white")
    
    # 转换为 float 以避免 Decimal 类型问题
    total = float(price) * float(quantity) * multiplier
    return Text(f"${total:.2f}", style=style)


def format_change(old_value, new_value, show_change: bool = True) -> Text:
    """
    格式化变更值（如价格、数量的修改）
    
    Args:
        old_value: 原值
        new_value: 新值
        show_change: 是否显示变更箭头
    
    Returns:
        带颜色的 Text 对象
    """
    if show_change and old_value != new_value:
        return Text(f"{old_value} → {new_value}", style="bold yellow")
    else:
        return Text(str(new_value), style="white")


def format_strategy(
    trigger_price: Optional[float] = None,
    trailing_percent: Optional[float] = None,
    trailing_amount: Optional[float] = None
) -> str:
    """
    格式化止盈止损策略
    
    Args:
        trigger_price: 触发价格
        trailing_percent: 跟踪止损百分比
        trailing_amount: 跟踪止损金额
    
    Returns:
        策略描述字符串
    """
    strategies = []
    
    if trigger_price:
        strategies.append(f"止损: ${trigger_price:.2f}")
    
    if trailing_percent:
        strategies.append(f"跟踪止损: {trailing_percent:.1f}%")
    
    if trailing_amount:
        strategies.append(f"跟踪金额: ${trailing_amount:.2f}")
    
    return " | ".join(strategies) if strategies else "-"


def print_order_table(order: Dict, title: str = "订单信息"):
    """
    以表格形式打印单个订单（单列展示，无字段名）
    
    Args:
        order: 订单信息字典
        title: 表格标题
    """
    # 获取期权语义化名称
    symbol = order.get('symbol', '-')
    semantic_name = parse_option_symbol(symbol)
    
    # 根据订单类型设置边框颜色
    side = order.get('side', '').upper()
    if side == 'BUY':
        border_style = "bold blue"
    elif side == 'SELL':
        border_style = "bold green"
    else:
        border_style = "bold white"
    
    # 创建表格，使用语义化名称作为标题，带粗体彩色边框
    table = Table(title=f"[bold cyan]{semantic_name}[/bold cyan]", show_header=False, show_edge=True, padding=(0, 1), border_style=border_style, box=box.HEAVY)
    
    # 添加两列
    table.add_column(justify="left", style="cyan", width=12)
    table.add_column(justify="left", style="white", width=40)
    
    # 订单ID
    order_id = order.get('order_id', '-')
    table.add_row("订单ID", order_id)
    
    # 期权名称（语义化）
    table.add_row("期权", semantic_name)
    
    # 操作方向（彩色）
    side_text = format_side(order.get('side', '-'))
    table.add_row("操作方向", side_text)
    
    # 数量
    quantity = order.get('quantity', 0)
    table.add_row("数量", str(quantity))
    
    # 价格（仅单价）
    price = order.get('price')
    price_str = format_price(price)
    table.add_row("价格", price_str)
    
    # 总价（蓝色显示）
    total_value = format_total_value(price, quantity)
    table.add_row("总价", total_value)
    
    # 策略
    strategy = format_strategy(
        order.get('trigger_price'),
        order.get('trailing_percent'),
        order.get('trailing_amount')
    )
    table.add_row("策略", strategy)
    
    # 状态
    status = order.get('status', '-')
    table.add_row("状态", status)
    
    # 账户模式
    mode = order.get('mode', '-')
    mode_display = "🧪 模拟账户" if mode == "paper" else "💰 真实账户"
    table.add_row("账户模式", mode_display)
    
    # 备注
    remark = order.get('remark')
    if remark:
        table.add_row("备注", remark)
    
    console.print(table)


def print_order_failed_table(order: Dict, error_msg: str, title: str = "订单失败"):
    """
    以红色边框表格形式打印失败的订单
    
    Args:
        order: 订单信息字典
        error_msg: 错误信息
        title: 表格标题
    """
    # 获取期权语义化名称
    symbol = order.get('symbol', '-')
    semantic_name = parse_option_symbol(symbol)
    
    # 创建表格，使用语义化名称作为标题，红色边框
    table = Table(
        title=f"[bold red]{semantic_name} - ❌ 订单失败[/bold red]", 
        show_header=False, 
        show_edge=True, 
        padding=(0, 1), 
        border_style="bold red",  # 红色边框
        box=box.HEAVY
    )
    
    # 添加两列
    table.add_column(justify="left", style="cyan", width=12)
    table.add_column(justify="left", style="white", width=40)
    
    # 期权名称（语义化）
    table.add_row("期权", semantic_name)
    
    # 操作方向（彩色）
    side_text = format_side(order.get('side', '-'))
    table.add_row("操作方向", side_text)
    
    # 数量
    quantity = order.get('quantity', 0)
    table.add_row("数量", str(quantity))
    
    # 价格（仅单价）
    price = order.get('price')
    price_str = format_price(price)
    table.add_row("价格", price_str)
    
    # 总价（蓝色显示）
    total_value = format_total_value(price, quantity)
    table.add_row("总价", total_value)
    
    # 失败原因（红色高亮）
    table.add_row("失败原因", Text(error_msg, style="bold red"))
    
    # 账户模式
    mode = order.get('mode', '-')
    mode_display = "🧪 模拟账户" if mode == "paper" else "💰 真实账户"
    table.add_row("账户模式", mode_display)
    
    # 备注
    remark = order.get('remark')
    if remark:
        table.add_row("备注", remark)
    
    console.print(table)


def print_order_search_table(order: Dict, title: str = "订单查询"):
    """
    以表格形式打印查询到的订单（纵向两列展示，无列标题）
    
    Args:
        order: 订单信息字典
        title: 表格标题（如果订单包含期权信息，会自动使用期权语义化名称）
    """
    # 获取期权语义化名称
    symbol = order.get('symbol', '-')
    semantic_name = parse_option_symbol(symbol)
    
    # 根据订单类型设置边框颜色
    side = order.get('side', '').upper()
    if side == 'BUY':
        border_style = "bold blue"
    elif side == 'SELL':
        border_style = "bold green"
    else:
        border_style = "bold white"
    
    # 创建表格，使用语义化名称作为标题，带粗体彩色边框
    table = Table(title=f"[bold cyan]{semantic_name}[/bold cyan]", show_header=False, show_edge=True, padding=(0, 1), border_style=border_style, box=box.HEAVY)
    
    # 添加两列
    table.add_column(justify="left", style="cyan", width=12)
    table.add_column(justify="left", style="white", width=40)
    
    # 订单ID
    order_id = order.get('order_id', '-')
    table.add_row("订单ID", order_id)
    
    # 期权名称（原始代码）
    table.add_row("期权名称", symbol)
    
    # 操作方向（彩色）
    side_text = format_side(order.get('side', '-'))
    table.add_row("操作方向", side_text)
    
    # 数量（包含已成交）
    quantity = order.get('quantity', 0)
    executed_quantity = order.get('executed_quantity', 0)
    if executed_quantity:
        quantity_str = f"{executed_quantity}/{quantity}"
    else:
        quantity_str = str(quantity)
    table.add_row("数量", quantity_str)
    
    # 价格（仅单价）
    price = order.get('price')
    price_str = format_price(price, market_text="市价")
    table.add_row("价格", price_str)
    
    # 总价（蓝色显示）
    total_value = format_total_value(price, quantity)
    table.add_row("总价", total_value)
    
    # 策略
    strategy = format_strategy(
        order.get('trigger_price'),
        order.get('trailing_percent'),
        order.get('trailing_amount')
    )
    table.add_row("策略", strategy)
    
    # 状态
    status = order.get('status', '-')
    table.add_row("状态", status)
    
    # 提交时间
    submitted_at = order.get('submitted_at', '-')
    table.add_row("提交时间", submitted_at)
    
    # 备注
    remark = order.get('remark')
    if remark:
        table.add_row("备注", remark)
    
    console.print(table)


def print_order_modify_table(
    order_id: str,
    old_order: Dict,
    new_values: Dict,
    title: str = "订单修改"
):
    """
    以表格形式打印订单修改信息（只显示变更项，黄色高亮）
    
    Args:
        order_id: 订单ID
        old_order: 原订单信息
        new_values: 新值
        title: 表格标题
    """
    # 获取期权语义化名称
    symbol = old_order.get('symbol', '-')
    semantic_name = parse_option_symbol(symbol)
    
    # 创建表格，使用语义化名称作为标题，黄色粗体边框（表示修改操作）
    table = Table(title=f"[bold cyan]{semantic_name}[/bold cyan]", 
                  show_header=False, 
                  border_style="bold yellow",
                  box=box.HEAVY)
    
    table.add_column("字段", style="cyan", width=12)
    table.add_column("原值", style="white", width=20)
    table.add_column("新值", style="bold yellow", width=20)
    
    # 统计变更项数量
    changes_count = 0
    
    # 订单ID（总是显示）
    table.add_row("订单ID", order_id, order_id)
    
    # 期权名称（总是显示）
    table.add_row("期权名称", symbol, symbol)
    
    # 数量（只在有变更时显示）
    old_qty = old_order.get('quantity', '-')
    new_qty = new_values.get('quantity', old_qty)
    if old_qty != new_qty:
        table.add_row(
            "数量",
            str(old_qty),
            Text(f"{old_qty} → {new_qty}", style="bold yellow")
        )
        changes_count += 1
    
    # 价格（只在有变更时显示）
    old_price = old_order.get('price')
    new_price = new_values.get('price', old_price)
    
    if old_price != new_price:
        old_price_str = format_price(old_price)
        new_price_str = format_price(new_price)
        table.add_row(
            "价格",
            old_price_str,
            Text(f"{old_price_str} → {new_price_str}", style="bold yellow")
        )
        changes_count += 1
    
    # 总价（当价格或数量变更时显示，黄色高亮变更）
    if old_price != new_price or old_qty != new_qty:
        # 计算原总价和新总价（转换为 float 以避免 Decimal 类型问题）
        old_total = float(old_price) * float(old_qty) * 100 if old_price else 0
        new_total = float(new_price) * float(new_qty) * 100 if new_price else 0
        
        old_total_str = f"${old_total:.2f}" if old_total else "-"
        new_total_str = f"${new_total:.2f}" if new_total else "-"
        
        if old_total != new_total:
            table.add_row(
                "总价",
                old_total_str,
                Text(f"{old_total_str} → {new_total_str}", style="bold yellow")
            )
        else:
            # 总价未变化，但相关字段变了（理论上不会出现，但为了完整性）
            table.add_row(
                "总价",
                old_total_str,
                Text(new_total_str, style="bold cyan")
            )
    
    # 策略（只在有变更时显示）
    old_strategy = format_strategy(
        old_order.get('trigger_price'),
        old_order.get('trailing_percent'),
        old_order.get('trailing_amount')
    )
    new_strategy = format_strategy(
        new_values.get('trigger_price', old_order.get('trigger_price')),
        new_values.get('trailing_percent', old_order.get('trailing_percent')),
        new_values.get('trailing_amount', old_order.get('trailing_amount'))
    )
    
    if old_strategy != new_strategy:
        table.add_row(
            "策略",
            old_strategy,
            Text(new_strategy, style="bold yellow")
        )
        changes_count += 1
    
    # 显示表格
    console.print(table)
    
    # 显示变更总结
    if changes_count > 0:
        console.print(f"[bold cyan]ℹ️  共修改 {changes_count} 个字段[/bold cyan]")
    else:
        console.print(f"[bold yellow]⚠️  未检测到变更[/bold yellow]")


def print_order_cancel_table(order: Dict, title: str = "订单撤销"):
    """
    以表格形式打印订单撤销信息（垂直两列展示：字段-值）
    
    Args:
        order: 订单信息字典
        title: 表格标题
    """
    # 获取期权语义化名称
    symbol = order.get('symbol', '-')
    semantic_name = parse_option_symbol(symbol)
    
    # 创建表格，使用语义化名称作为标题，极浅灰色边框（表示撤销操作）
    table = Table(title=f"[bold cyan]{semantic_name}[/bold cyan]", 
                  show_header=False,
                  border_style="dim white",  # 极浅灰色边框
                  box=box.HEAVY)
    
    # 两列：字段和值
    table.add_column("字段", style="cyan", width=12)
    table.add_column("值", style="white", width=25)
    
    # 订单ID
    order_id = order.get('order_id', '-')
    table.add_row("订单ID", order_id)
    
    # 期权名称（原始代码）
    table.add_row("期权名称", symbol)
    
    # 操作
    cancel_text = Text("CANCEL", style="bold yellow")
    table.add_row("操作", cancel_text)
    
    # 数量
    quantity = order.get('quantity', 0)
    table.add_row("数量", str(quantity))
    
    # 价格（仅单价）
    price = order.get('price')
    price_str = format_price(price, market_text="市价")
    table.add_row("价格", price_str)
    
    # 总价（蓝色显示）
    total_value = format_total_value(price, quantity)
    table.add_row("总价", total_value)
    
    # 状态
    table.add_row("状态", "已撤销")
    
    # 撤销时间
    cancelled_at = order.get('cancelled_at', '-')
    table.add_row("撤销时间", cancelled_at)
    
    console.print(table)


def print_orders_summary_table(orders: List[Dict], title: str = "订单列表"):
    """
    以表格形式打印多个订单的摘要
    
    Args:
        orders: 订单列表
        title: 表格标题
    """
    if not orders:
        console.print(f"[yellow]{title}: 无订单[/yellow]")
        return
    
    table = Table(title=f"{title} (共 {len(orders)} 个)", show_header=True, header_style="bold magenta", box=box.HEAVY)
    
    table.add_column("期权", style="cyan", width=25)
    table.add_column("方向", style="white", width=6)
    table.add_column("数量", style="white", width=6)
    table.add_column("价格", style="white", width=10)
    table.add_column("总价", style="bold cyan", width=12)
    table.add_column("状态", style="white", width=20)
    
    for order in orders:
        # 期权名称（语义化）
        symbol = parse_option_symbol(order.get('symbol', '-'))
        
        # 操作方向（彩色）
        side_text = format_side(order.get('side', '-'))
        
        # 数量（包含已成交数量）
        quantity = order.get('quantity', 0)
        executed_quantity = order.get('executed_quantity')
        if executed_quantity and executed_quantity > 0:
            quantity_str = f"{executed_quantity}/{quantity}"
        else:
            quantity_str = str(quantity)
        
        # 价格（仅单价）
        price = order.get('price')
        price_str = format_price(price, market_text="市价")
        
        # 总价（蓝色显示）
        total_value = format_total_value(price, quantity)
        
        # 状态（移除"OrderStatus."前缀，使其更简洁）
        status = str(order.get('status', '-'))
        status_display = status.replace('OrderStatus.', '')
        
        table.add_row(
            symbol,
            side_text,
            quantity_str,
            price_str,
            total_value,
            status_display
        )
    
    console.print(table)


def print_account_info_table(account_info: Dict, title: str = "账户信息"):
    """
    以表格形式打印账户信息（垂直两列展示：字段-值）
    
    Args:
        account_info: 账户信息字典
        title: 表格标题
    """
    table = Table(title=title, show_header=True, header_style="bold magenta", box=box.HEAVY)
    
    # 两列：字段和值
    table.add_column("字段", style="cyan", width=12)
    table.add_column("值", style="white", width=20)
    
    # 获取数据
    total_cash = account_info.get('total_cash', 0)
    available_cash = account_info.get('available_cash', 0)
    frozen_cash = total_cash - available_cash if total_cash and available_cash else 0
    position_value = account_info.get('position_value', 0)
    
    # 计算现金比例
    total_value = total_cash + position_value if total_cash and position_value else total_cash
    cash_ratio = (total_cash / total_value * 100) if total_value > 0 else 0
    
    # 添加数据行
    table.add_row("总资产", f"${total_cash:,.2f}")
    table.add_row("可用资金", f"${available_cash:,.2f}")
    table.add_row("冻结资金", f"${frozen_cash:,.2f}")
    table.add_row("持仓市值", f"${position_value:,.2f}")
    table.add_row("现金比例", f"{cash_ratio:.1f}%")
    
    console.print(table)


def print_positions_table(positions: List[Dict], title: str = "持仓信息"):
    """
    以表格形式打印持仓信息（横向多列展示汇总列表）
    
    Args:
        positions: 持仓列表
        title: 表格标题
    """
    if not positions:
        console.print(f"[yellow]{title}: 无持仓[/yellow]")
        return
    
    table = Table(title=f"{title} (共 {len(positions)} 个)", show_header=True, header_style="bold magenta", box=box.HEAVY)
    
    table.add_column("期权", style="cyan", width=30)
    table.add_column("持仓数量", style="white", width=12)
    table.add_column("可用数量", style="green", width=12)
    table.add_column("成本价", style="white", width=12)
    table.add_column("当前价", style="white", width=12)
    table.add_column("盈亏", style="white", width=15)
    table.add_column("盈亏率", style="white", width=10)
    
    for pos in positions:
        # 期权名称（语义化）
        symbol = parse_option_symbol(pos.get('symbol', '-'))
        
        # 持仓数量
        quantity = pos.get('quantity', 0)
        quantity_str = f"{quantity:,.0f}" if quantity else "-"
        
        # 可用数量
        available_quantity = pos.get('available_quantity', 0)
        available_str = f"{available_quantity:,.0f}" if available_quantity else "-"
        
        # 成本价
        cost_price = pos.get('cost_price', 0)
        cost_str = f"${cost_price:,.2f}" if cost_price else "-"
        
        # 当前价
        current_price = pos.get('current_price', 0)
        current_str = f"${current_price:,.2f}" if current_price else "-"
        
        # 盈亏
        pnl = 0
        pnl_percent = 0
        pnl_style = "white"
        
        if cost_price and current_price and quantity:
            pnl = (current_price - cost_price) * quantity
            pnl_percent = ((current_price - cost_price) / cost_price * 100) if cost_price > 0 else 0
            pnl_style = "bold green" if pnl >= 0 else "bold red"
        
        pnl_str = f"${pnl:+,.2f}" if pnl else "-"
        pnl_percent_str = f"{pnl_percent:+.2f}%" if pnl_percent else "-"
        
        table.add_row(
            symbol,
            quantity_str,
            available_str,
            cost_str,
            current_str,
            Text(pnl_str, style=pnl_style),
            Text(pnl_percent_str, style=pnl_style)
        )
    
    console.print(table)


def print_success_message(message: str):
    """打印成功消息"""
    console.print(f"[bold green]✅ {message}[/bold green]")


def print_error_message(message: str):
    """打印错误消息"""
    console.print(f"[bold red]❌ {message}[/bold red]")


def print_warning_message(message: str):
    """打印警告消息"""
    console.print(f"[bold yellow]⚠️  {message}[/bold yellow]")


def print_info_message(message: str):
    """打印信息消息"""
    console.print(f"[bold cyan]ℹ️  {message}[/bold cyan]")


def print_account_info_table(account_info: Dict, title: str = "账户信息"):
    """
    打印账户信息表格
    
    Args:
        account_info: 账户信息字典
        title: 表格标题
    """
    table = Table(title=title, show_header=True, header_style="bold magenta", box=box.HEAVY)
    
    table.add_column("项目", style="cyan", width=20)
    table.add_column("金额", justify="right", style="white", width=20)
    
    # 总资产
    total_cash = account_info.get('total_cash', 0)
    table.add_row("总资产", Text(f"${total_cash:,.2f}", style="bold green"))
    
    # 可用资金
    available_cash = account_info.get('available_cash', 0)
    table.add_row("可用资金", f"${available_cash:,.2f}")
    
    # 持仓市值
    position_value = account_info.get('position_value', 0)
    table.add_row("持仓市值", f"${position_value:,.2f}")
    
    # 冻结资金
    frozen_cash = total_cash - available_cash
    table.add_row("冻结资金", f"${frozen_cash:,.2f}")
    
    # 币种
    currency = account_info.get('currency', 'USD')
    table.add_row("币种", currency)
    
    # 账户模式
    mode = account_info.get('mode', '-')
    mode_display = "🧪 模拟账户" if mode == "paper" else "💰 真实账户"
    table.add_row("账户模式", mode_display)
    
    console.print(table)


def print_positions_table(positions: List[Dict], title: str = "持仓列表"):
    """
    打印持仓信息表格
    
    Args:
        positions: 持仓信息列表
        title: 表格标题
    """
    if not positions:
        print_warning_message("暂无持仓")
        return
    
    table = Table(title=f"{title} (共 {len(positions)} 个)", show_header=True, header_style="bold magenta", box=box.HEAVY)
    
    table.add_column("代码/期权", style="cyan", width=30)
    table.add_column("数量", justify="right", width=10)
    table.add_column("成本价", justify="right", width=14)
    table.add_column("市值", justify="right", width=16)
    table.add_column("市场", justify="center", width=8)
    
    for pos in positions:
        # 解析期权名称
        symbol = pos.get('symbol', '-')
        semantic_name = parse_option_symbol(symbol)
        
        # 数量
        quantity = pos.get('quantity', 0)
        
        # 成本价
        cost_price = pos.get('cost_price', 0)
        cost_str = f"${cost_price:.2f}"
        
        # 市值（根据是否为期权判断乘数）
        # 如果symbol包含期权特征（如 C/P），则使用100乘数，否则为正股
        if 'C' in symbol or 'P' in symbol:
            market_value = quantity * cost_price * 100  # 期权合约乘数100
        else:
            market_value = quantity * cost_price  # 正股
        market_str = f"${market_value:,.2f}"
        
        # 市场（简化显示，去掉 "Market." 前缀）
        market = pos.get('market', '-')
        market_display = str(market).replace('Market.', '') if market else '-'
        
        table.add_row(
            semantic_name,
            str(int(quantity)),
            cost_str,
            market_str,
            market_display
        )
    
    console.print(table)


def print_stock_quotes_table(quotes: List[Dict], title: str = "股票报价"):
    """
    打印股票报价表格
    
    Args:
        quotes: 股票报价列表
        title: 表格标题
    """
    if not quotes:
        print_warning_message("无报价数据")
        return
    
    table = Table(title=f"{title} (共 {len(quotes)} 个)", show_header=True, header_style="bold magenta", box=box.HEAVY)
    
    table.add_column("代码", style="cyan", width=12)
    table.add_column("最新价", justify="right", width=11)
    table.add_column("涨跌幅", justify="right", width=13)
    table.add_column("开盘", justify="right", width=11)
    table.add_column("最高", justify="right", width=11)
    table.add_column("最低", justify="right", width=11)
    table.add_column("成交量", justify="right", width=13)
    table.add_column("成交额(M)", justify="right", width=11)
    
    for quote in quotes:
        symbol = quote.get('symbol', '-')
        last_done = quote.get('last_done', 0)
        prev_close = quote.get('prev_close', 0)
        open_price = quote.get('open', 0)
        high = quote.get('high', 0)
        low = quote.get('low', 0)
        volume = quote.get('volume', 0)
        turnover = quote.get('turnover', 0)
        
        # 计算涨跌幅
        change_pct = ((last_done - prev_close) / prev_close * 100) if prev_close > 0 else 0
        change_style = "bold green" if change_pct >= 0 else "bold red"
        change_icon = "🟢" if change_pct >= 0 else "🔴"
        change_str = f"{change_icon} {change_pct:+.2f}%"
        
        # 成交额转换为百万显示
        turnover_m = turnover / 1_000_000 if turnover else 0
        
        table.add_row(
            symbol,
            f"${last_done:.2f}",
            Text(change_str, style=change_style),
            f"${open_price:.2f}",
            f"${high:.2f}",
            f"${low:.2f}",
            f"{volume:,}",
            f"${turnover_m:,.1f}M"
        )
    
    console.print(table)


def print_today_orders_table(orders: List[Dict], title: str = "当日订单"):
    """
    打印当日订单表格
    
    Args:
        orders: 订单列表
        title: 表格标题
    """
    if not orders:
        print_warning_message("今日暂无订单")
        return
    
    table = Table(title=f"{title} (共 {len(orders)} 个)", show_header=True, header_style="bold magenta", box=box.HEAVY)
    
    table.add_column("期权", style="cyan", width=25)
    table.add_column("方向", justify="center", width=6)
    table.add_column("数量", justify="right", width=6)
    table.add_column("价格", justify="right", width=10)
    table.add_column("状态", justify="center", width=15)
    table.add_column("提交时间", justify="center", width=10)
    
    for order in orders:
        # 解析期权名称
        symbol = order.get('symbol', '-')
        semantic_name = parse_option_symbol(symbol)
        
        # 操作方向
        side = order.get('side', '-')
        side_text = format_side(side)
        
        # 数量
        quantity = order.get('quantity', 0)
        executed_quantity = order.get('executed_quantity', 0)
        quantity_str = f"{int(executed_quantity)}/{int(quantity)}" if executed_quantity > 0 else str(int(quantity))
        
        # 价格
        price = order.get('price')
        price_str = format_price(price, "市价")
        
        # 状态
        status = order.get('status', '-')
        # 简化状态显示
        status_short = status.replace('OrderStatus.', '')
        
        # 提交时间
        submitted_at = order.get('submitted_at', '-')
        if submitted_at != '-' and 'T' in submitted_at:
            # 只显示时间部分
            time_part = submitted_at.split('T')[1][:8]
        else:
            time_part = '-'
        
        table.add_row(
            semantic_name,
            side_text,
            quantity_str,
            price_str,
            status_short,
            time_part
        )
    
    console.print(table)
