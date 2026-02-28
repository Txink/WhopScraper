"""
RichLogger 终端效果演示脚本
直接运行即可在终端查看各种输出效果。
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import time
from utils.rich_logger import RichLogger, get_logger


def demo_tag_live():
    """演示 1：Tag Live - 动态追加输出"""
    logger = RichLogger()
    print("\n" + "─" * 60)
    print("  演示 1：Tag Live（动态追加输出）")
    print("─" * 60 + "\n")

    logger.tag_live_start("程序加载")
    time.sleep(0.5)

    logger.tag_live_append("程序加载", "长桥交易接口初始化")
    time.sleep(0.3)

    logger.tag_live_append("程序加载", "浏览器连接建立")
    time.sleep(0.3)

    logger.tag_live_append("程序加载", "消息监听启动")
    time.sleep(0.3)

    logger.tag_live_stop("程序加载")


def demo_tag_live_nested():
    """演示 2：Tag Live - 嵌套结构"""
    logger = RichLogger()
    print("\n" + "─" * 60)
    print("  演示 2：Tag Live（嵌套结构）")
    print("─" * 60 + "\n")

    logger.tag_live_start("持仓更新")
    time.sleep(0.3)

    logger.tag_live_append("持仓更新", "当前持仓 3 个合约：", level=0)
    time.sleep(0.2)

    logger.tag_live_append("持仓更新", "AAPL260307C230000.US  x10  $3.50", level=1)
    time.sleep(0.2)

    logger.tag_live_append("持仓更新", "TSLA260307P250000.US  x5   $2.80", level=1)
    time.sleep(0.2)

    logger.tag_live_append("持仓更新", "NVDA260307C900000.US  x8   $5.20", level=1)
    time.sleep(0.3)

    logger.tag_live_stop("持仓更新")


def demo_config():
    """演示 3：配置信息"""
    logger = RichLogger()
    print("\n" + "─" * 60)
    print("  演示 3：配置信息（log_config）")
    print("─" * 60 + "\n")

    logger.log_config("配置更新", [
        "账户类型：模拟账户",
        "单次购买上限：$10,000.00",
        "价格偏差容忍：20%",
        "消息过期时间：120秒",
    ])


def demo_nested_data():
    """演示 4：嵌套数据"""
    logger = RichLogger()
    print("\n" + "─" * 60)
    print("  演示 4：嵌套数据（log_nested）")
    print("─" * 60 + "\n")

    logger.log_nested("订单推送", [
        {"key": "[BUY] symbol", "value": "CAH260227C227500.US"},
        {"key": "status", "value": "OrderStatus.New"},
        {"key": "submitted_quantity", "value": "36"},
        {"key": "submitted_price", "value": "2.75"},
        {"key": "time", "value": "2026-02-26 22:41:08"},
    ])

    logger.log_nested("订单推送", [
        {"key": "[BUY] symbol", "value": "CAH260227C227500.US"},
        {"key": "status", "value": "OrderStatus.Filled"},
        {"key": "submitted_quantity", "value": "36"},
        {"key": "submitted_price", "value": "2.75"},
        {"key": "time", "value": "2026-02-26 22:41:08"},
    ])

    logger.log("持仓更新", "买入成交后 CAH260227C227500.US",
               tag_style="bold magenta")


def demo_simple_log():
    """演示 5：静态日志"""
    logger = RichLogger()
    print("\n" + "─" * 60)
    print("  演示 5：静态日志")
    print("─" * 60 + "\n")

    logger.log("交易提醒", "价格已达止损线",
               details=["symbol: AAPL260307C230000.US",
                        "当前价: $2.10", "止损价: $2.00"],
               tag_style="bold red")


def demo_trade_flow():
    """演示 6：两个并行交易流程"""
    logger = RichLogger()
    print("\n" + "─" * 60)
    print("  演示 6：并行交易流程（多 domID 独立表格）")
    print("─" * 60 + "\n")

    logger.separator()

    dom_a = "post_1CYWrYVBybnBUBuM4auH4j"
    dom_b = "post_2ABCxyz123456789"

    logger.trade_start(dom_id=dom_a)
    logger.trade_stage("原始消息",
        tag_suffix="[yellow]\\[-8153ms][/yellow]",
        rows=[
            ("domID", dom_a),
            ("content", '[cyan]"CAH - $227.5 CALLS EXPIRATION THIS WEEK $2.70 彩票"[/cyan]'),
            ("position", "single", "dim"),
        ], tag_style="bold blue", dom_id=dom_a)
    time.sleep(0.5)

    logger.trade_start(dom_id=dom_b)
    logger.trade_stage("原始消息",
        tag_suffix="[yellow]\\[-3200ms][/yellow]",
        rows=[
            ("domID", dom_b),
            ("content", '[cyan]"NVDA - $130 PUTS 3/7 $1.50"[/cyan]'),
            ("position", "first", "dim"),
        ], tag_style="bold blue", dom_id=dom_b)
    time.sleep(0.8)

    logger.trade_stage("解析消息", rows=[
        ("", "[green]\\[BUY][/green] [bold blue]CAH260227C227500.US[/bold blue] $2.7"),
    ], tag_style="bold blue", dom_id=dom_a)
    time.sleep(0.5)

    logger.trade_stage("解析消息", rows=[
        ("", "[green]\\[BUY][/green] [bold blue]NVDA260307P130000.US[/bold blue] $1.5"),
    ], tag_style="bold blue", dom_id=dom_b)
    time.sleep(0.8)

    logger.trade_stage("订单校验", rows=[
        ("查询价格", "当前市场价=$2.75，指令价=$2.70，偏差=1.9%，使用价格=$2.75", "dim"),
        ("买入总价", "$2.75 × 36 = $9900.00"),
    ], tag_style="bold yellow", dom_id=dom_a)
    time.sleep(0.5)

    logger.trade_stage("订单校验", rows=[
        ("查询价格", "当前市场价=$1.55，指令价=$1.50，偏差=3.3%，使用价格=$1.55", "dim"),
        ("买入总价", "$1.55 × 64 = $9920.00"),
    ], tag_style="bold yellow", dom_id=dom_b)
    time.sleep(0.8)

    logger.trade_stage("提交订单", rows=[
        ("OrderID", "[dim]ORD_CAH_001[/dim]"),
        ("", "[green]\\[BUY][/green] CAH260227C227500.US $2.75 × 36 = [bold green]$9900.00[/bold green]"),
    ], tag_suffix="\\[模拟]", tag_style="bold green", dom_id=dom_a)
    logger.trade_register_order("ORD_CAH_001", dom_id=dom_a)
    logger.trade_end(dom_id=dom_a)
    time.sleep(0.5)

    logger.trade_stage("提交订单", rows=[
        ("OrderID", "[dim]ORD_NVDA_001[/dim]"),
        ("", "[green]\\[BUY][/green] NVDA260307P130000.US $1.55 × 64 = [bold green]$9920.00[/bold green]"),
    ], tag_suffix="\\[模拟]", tag_style="bold green", dom_id=dom_b)
    logger.trade_register_order("ORD_NVDA_001", dom_id=dom_b)
    logger.trade_end(dom_id=dom_b)
    time.sleep(1.0)

    logger.trade_push_update("ORD_CAH_001", rows=[
        ("Status", "[bold green]OrderStatus.Filled[/bold green]"),
    ], tag_style="bold green", terminal=True)
    time.sleep(1.0)

    logger.trade_push_update("ORD_NVDA_001", rows=[
        ("Status", "[bold green]OrderStatus.Filled[/bold green]"),
    ], tag_style="bold green", terminal=True)


def demo_position_table():
    """演示 7：账户持仓表格 + 订单成交后更新"""
    logger = RichLogger()
    print("\n" + "─" * 60)
    print("  演示 7：账户持仓表格 & 订单成交更新")
    print("─" * 60 + "\n")

    config = [
        "账户类型：模拟",
        "Dry Run 模式：关闭（将真实下单）",
        "单次购买期权总价上限：$10000.0",
        "单次购买期权数量上限：45张",
        "价差容忍度：10.0%",
        "容忍度内买入价：市价",
        "默认止损：开启，38%",
    ]
    account = {
        "available_cash": 32020.12,
        "cash": 35000.00,
        "total_assets": 116509.14,
        "is_paper": True,
    }
    positions = [
        {
            "symbol": "TSLL.US",
            "quantity": 4802,
            "unit": "股",
            "avg_cost": 14.845,
            "position_value": 71285.69,
            "pct": 61.2,
            "records": [
                {"submitted_at": "2026-01-30 19:59:07", "side": "SELL", "qty": 2500, "price": "16.78"},
                {"submitted_at": "2026-02-09 13:48:01", "side": "BUY", "qty": 1, "price": "15.77"},
                {"submitted_at": "2026-02-24 00:16:34", "side": "BUY", "qty": 800, "price": "14.38"},
                {"submitted_at": "2026-02-25 00:59:08", "side": "BUY", "qty": 800, "price": "14.92"},
                {"submitted_at": "2026-02-25 01:23:41", "side": "SELL", "qty": 400, "price": "14.58"},
            ],
        },
        {
            "symbol": "UUUU.US",
            "quantity": 2000,
            "unit": "股",
            "avg_cost": 6.500,
            "position_value": 13000.00,
            "pct": 11.2,
            "records": [],
        },
        {
            "symbol": "AAPL.US",
            "quantity": 100,
            "unit": "股",
            "avg_cost": 175.230,
            "position_value": 17523.00,
            "pct": 15.0,
            "records": [
                {"submitted_at": "2026-02-20 10:30:00", "side": "BUY", "qty": 100, "price": "175.23"},
            ],
        },
    ]
    logger.print_position_table(None, positions, account=account, config_lines=config)

    time.sleep(1.5)

    update_title = (
        "[grey70]2026-02-28 20:05:12.321[/grey70] "
        "[bold magenta]\\[持仓更新][/bold magenta] "
        "买入成交后 [bold]TSLL.US[/bold]"
    )
    updated_positions = [
        {
            "symbol": "TSLL.US",
            "quantity": 5602,
            "unit": "股",
            "avg_cost": 14.780,
            "position_value": 82797.56,
            "pct": 65.8,
            "records": [
                {"submitted_at": "2026-01-30 19:59:07", "side": "SELL", "qty": 2500, "price": "16.78"},
                {"submitted_at": "2026-02-09 13:48:01", "side": "BUY", "qty": 1, "price": "15.77"},
                {"submitted_at": "2026-02-24 00:16:34", "side": "BUY", "qty": 800, "price": "14.38"},
                {"submitted_at": "2026-02-25 00:59:08", "side": "BUY", "qty": 800, "price": "14.92"},
                {"submitted_at": "2026-02-25 01:23:41", "side": "SELL", "qty": 400, "price": "14.58"},
                {"submitted_at": "2026-02-28 20:05:12", "side": "BUY", "qty": 800, "price": "14.75"},
            ],
        },
    ]
    logger.print_position_table(update_title, updated_positions)


def main():
    print("\n" + "=" * 60)
    print("     RichLogger 终端效果演示")
    print("=" * 60)

    demo_tag_live()
    demo_tag_live_nested()
    demo_config()
    demo_nested_data()
    demo_simple_log()
    demo_trade_flow()
    demo_position_table()

    print("\n" + "=" * 60)
    print("     演示结束")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    main()
