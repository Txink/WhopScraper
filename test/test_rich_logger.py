"""
RichLogger 单元测试

验证 Tag追加模式、交易流程模式、单条日志等输出效果。
使用 rich Console 的 record 模式捕获输出进行断言。
"""
import re
import sys
import time
import threading
from pathlib import Path
from io import StringIO

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from rich.console import Console

from utils.rich_logger import RichLogger, get_logger, set_logger, reset_logger


def _strip_ansi(s: str) -> str:
    """去除 ANSI 转义码，返回纯文本"""
    return re.sub(r'\x1b\[[0-9;?]*[A-Za-z]', '', s)


@pytest.fixture(autouse=True)
def _reset():
    """每个测试后重置全局 logger"""
    yield
    reset_logger()


def _make_logger() -> tuple:
    """创建一个用 StringIO 捕获输出的 logger，返回 (logger, output_func)"""
    buf = StringIO()
    console = Console(file=buf, force_terminal=True, width=120)
    logger = RichLogger(console=console)

    def get_output() -> str:
        return _strip_ansi(buf.getvalue())

    return logger, get_output


# ================================================================
#  1. 单条日志 log()
# ================================================================

class TestLog:
    def test_log_basic(self):
        """基础 log：tag + header + 空行"""
        logger, output = _make_logger()
        logger.log("测试标签", "hello world")
        text = output()
        assert "[测试标签]" in text
        assert "hello world" in text

    def test_log_with_details(self):
        """log 带 details"""
        logger, output = _make_logger()
        logger.log("订单推送", "[BUY] symbol=AAPL",
                    details=["status=New", "price=1.5"],
                    tag_style="bold white")
        text = output()
        assert "[订单推送]" in text
        assert "symbol=AAPL" in text
        assert "status=New" in text
        assert "price=1.5" in text

    def test_log_with_header_extra(self):
        """log 带 header_extra"""
        logger, output = _make_logger()
        logger.log("订单校验", "",
                    details=["查询价格：市价=1.5"],
                    header_extra=["\\[BUY]", "symbol=TEST.US", "price=1.5"])
        text = output()
        assert "[订单校验]" in text
        assert "[BUY]" in text
        assert "symbol=TEST.US" in text

    def test_log_custom_detail_style(self):
        """detail_style 为空时，details 的 rich markup 原样渲染"""
        logger, output = _make_logger()
        logger.log("解析消息", "symbol = AAPL",
                    details=["[yellow]op[/yellow]: BUY"],
                    detail_style="")
        text = output()
        assert "op" in text
        assert "BUY" in text

    def test_separator(self):
        """separator 输出 80 个等号"""
        logger, output = _make_logger()
        logger.separator()
        text = output()
        assert "=" * 80 in text


# ================================================================
#  2. Tag Live 模式
# ================================================================

class TestTagLive:
    def test_tag_live_start_stop(self):
        """tag_live 启动和停止不抛异常"""
        logger, output = _make_logger()
        logger.tag_live_start("程序加载")
        logger.tag_live_append("程序加载", "初始化中...")
        logger.tag_live_stop("程序加载")
        # Live 停止后内容冻结在 console buffer
        text = output()
        assert "[程序加载]" in text
        assert "初始化中..." in text

    def test_tag_live_multiple_appends(self):
        """多次 append 都出现在输出中"""
        logger, output = _make_logger()
        logger.tag_live_start("加载")
        logger.tag_live_append("加载", "步骤1")
        logger.tag_live_append("加载", "步骤2")
        logger.tag_live_append("加载", "步骤3")
        logger.tag_live_stop("加载")
        text = output()
        assert "步骤1" in text
        assert "步骤2" in text
        assert "步骤3" in text

    def test_tag_live_nested_levels(self):
        """level>0 的行有额外缩进"""
        logger, output = _make_logger()
        logger.tag_live_start("数据")
        logger.tag_live_append("数据", "顶层项", level=0)
        logger.tag_live_append("数据", "子项A", level=1)
        logger.tag_live_append("数据", "子项B", level=1)
        logger.tag_live_stop("数据")
        text = output()
        assert "顶层项" in text
        assert "子项A" in text
        assert "子项B" in text

    def test_tag_live_append_after_stop_falls_back_to_log(self):
        """tag 已停止后再 append，回退为普通 log"""
        logger, output = _make_logger()
        logger.tag_live_start("测试")
        logger.tag_live_stop("测试")
        logger.tag_live_append("测试不存在", "fallback line")
        text = output()
        assert "fallback line" in text

    def test_tag_live_get_data(self):
        """tag_live_get_data 返回内部数据"""
        logger, _ = _make_logger()
        logger.tag_live_start("demo")
        logger.tag_live_append("demo", "line1")
        data = logger.tag_live_get_data("demo")
        assert data is not None
        assert len(data.lines) == 1
        assert data.lines[0][1] == "line1"
        logger.tag_live_stop("demo")


# ================================================================
#  3. 交易流程模式
# ================================================================

class TestTradeFlow:
    def test_trade_start_end(self):
        """交易流程启动和结束不抛异常"""
        logger, output = _make_logger()
        logger.trade_start()
        assert logger.in_trade_flow
        logger.trade_end()
        assert not logger.in_trade_flow

    def test_trade_stage_adds_to_panel(self):
        """交易流程活跃时，trade_stage() 添加到文本区块"""
        logger, output = _make_logger()
        logger.trade_start()
        logger.trade_stage("原始消息", rows=[
            ("domID", "post_abc"),
            ("content", '"BUY AAPL $5"'),
        ], tag_style="bold blue")
        logger.trade_stage("解析消息", rows=[
            ("", "\\[BUY] AAPL $5"),
        ], tag_style="bold blue")
        logger.trade_end()
        text = output()
        assert "原始消息" in text
        assert "BUY AAPL" in text
        assert "解析消息" in text

    def test_trade_stage_fallback_when_no_flow(self):
        """无活跃交易流程时，trade_stage 回退为静态日志"""
        logger, output = _make_logger()
        logger.trade_stage("解析消息", rows=[
            ("symbol", "AAPL"),
            ("operation", "BUY"),
        ], tag_style="bold blue")
        text = output()
        assert "解析消息" in text
        assert "symbol" in text
        assert "AAPL" in text

    def test_trade_flow_multiple_stages(self):
        """多个阶段都在文本区块中"""
        logger, output = _make_logger()
        logger.trade_start()
        logger.trade_stage("原始消息", rows=[
            ("content", '"CAH $227.5 CALLS"'),
        ], tag_style="bold blue")
        logger.trade_stage("解析消息", rows=[
            ("", "\\[BUY] CAH260227C227500.US $2.7"),
        ], tag_style="bold blue")
        logger.trade_stage("订单校验", rows=[
            ("查询价格", "市价=$2.75"),
            ("买入数量", "36张"),
            ("买入总价", "$2.75 × 36 = $9900.00"),
        ], tag_style="bold yellow")
        logger.trade_stage("提交订单", rows=[
            ("OrderID", "ORD_001"),
            ("", "\\[BUY] CAH260227C227500.US $2.75 × 36 = $9900.00"),
        ], tag_style="bold green")
        logger.trade_end()
        text = output()
        for tag in ["原始消息", "解析消息", "订单校验", "提交订单"]:
            assert tag in text
        assert "36张" in text
        assert "$9900.00" in text
        assert "─" * 40 in text

    def test_log_after_trade_end_prints_normally(self):
        """交易流程结束后，log() 恢复为直接打印"""
        logger, output = _make_logger()
        logger.trade_start()
        logger.trade_stage("原始消息", rows=[("content", "in flow")], tag_style="bold blue")
        logger.trade_end()
        logger.log("订单推送", "after flow", tag_style="bold white")
        text = output()
        assert "in flow" in text
        assert "after flow" in text

    def test_trade_flow_thread_safe(self):
        """多线程安全：主线程 trade_stage → 子线程 trade_stage → 主线程 trade_end"""
        logger, output = _make_logger()
        logger.trade_start()
        logger.trade_stage("原始消息", rows=[("content", "main thread")], tag_style="bold blue")

        def bg_stage():
            time.sleep(0.05)
            logger.trade_stage("订单推送", rows=[
                ("status", "Filled"),
            ], tag_style="bold white")

        t = threading.Thread(target=bg_stage)
        t.start()
        t.join()
        logger.trade_end()
        text = output()
        assert "main thread" in text
        assert "Filled" in text

    def test_trade_register_and_push_update(self):
        """注册订单后 trade_end 保持 Live，push_update 添加推送阶段"""
        logger, output = _make_logger()
        logger.trade_start()
        logger.trade_stage("原始消息", rows=[("content", "test")], tag_style="bold blue")
        logger.trade_stage("提交订单", rows=[("", "\\[BUY] TEST.US")],
                           tag_suffix="\\[模拟]", tag_style="bold green")
        logger.trade_register_order("ORD_123")
        assert logger.has_pending_order
        logger.trade_end()
        assert logger.in_trade_flow  # Live still active

        logger.trade_push_update("ORD_123", rows=[
            ("status", "OrderStatus.Filled"),
            ("quantity", "36"),
        ], tag_style="bold white", terminal=True)
        assert not logger.in_trade_flow
        text = output()
        assert "原始消息" in text
        assert "提交订单" in text
        assert "订单推送" in text
        assert "Filled" in text

    def test_trade_push_update_no_match_silent(self):
        """推送 order_id 不匹配时静默忽略"""
        logger, output = _make_logger()
        logger.trade_push_update("UNKNOWN_ID", rows=[
            ("status", "OrderStatus.New"),
        ], tag_style="bold white")
        text = output()
        assert text.strip() == ""

    def test_multi_flow_parallel(self):
        """多个交易流程并行存在，各自独立更新"""
        logger, output = _make_logger()
        logger.trade_start(dom_id="dom_A")
        logger.trade_stage("原始消息", rows=[("domID", "dom_A")],
                           tag_style="bold blue", dom_id="dom_A")

        logger.trade_start(dom_id="dom_B")
        logger.trade_stage("原始消息", rows=[("domID", "dom_B")],
                           tag_style="bold blue", dom_id="dom_B")

        logger.trade_stage("解析消息", rows=[("", "\\[BUY] AAPL $5")],
                           tag_style="bold blue", dom_id="dom_A")
        logger.trade_stage("解析消息", rows=[("", "\\[BUY] NVDA $3")],
                           tag_style="bold blue", dom_id="dom_B")

        logger.trade_end(dom_id="dom_A")
        logger.trade_end(dom_id="dom_B")
        text = output()
        assert "dom_A" in text
        assert "dom_B" in text
        assert "AAPL" in text
        assert "NVDA" in text

    def test_multi_flow_push_by_order_id(self):
        """多流程中根据 order_id 定位对应流程更新"""
        logger, output = _make_logger()
        logger.trade_start(dom_id="dom_X")
        logger.trade_stage("原始消息", rows=[("domID", "dom_X")],
                           tag_style="bold blue", dom_id="dom_X")
        logger.trade_stage("提交订单", rows=[("OrderID", "ORD_X")],
                           tag_style="bold green", dom_id="dom_X")
        logger.trade_register_order("ORD_X", dom_id="dom_X")
        logger.trade_end(dom_id="dom_X")

        logger.trade_push_update("ORD_X", rows=[
            ("Status", "Filled"),
        ], terminal=True)
        text = output()
        assert "dom_X" in text
        assert "ORD_X" in text
        assert "Filled" in text
        assert not logger.in_trade_flow
        assert not logger.has_pending_order


# ================================================================
#  4. 静态 Tag 输出
# ================================================================

class TestStaticTags:
    def test_log_config(self):
        """log_config 输出配置块"""
        logger, output = _make_logger()
        logger.log_config("配置更新", [
            "账户类型：模拟",
            "Dry Run 模式：开启（不实际下单，仅打印）",
            "单次购买上限：$10000",
            "⚠️ 注意事项",
        ])
        text = output()
        assert "[配置更新]" in text
        assert "账户类型" in text
        assert "模拟" in text
        assert "Dry Run" in text
        assert "注意事项" in text

    def test_log_config_real_account(self):
        """log_config 真实账户高亮"""
        logger, output = _make_logger()
        logger.log_config("配置更新", ["账户类型：真实"])
        text = output()
        assert "真实" in text

    def test_log_nested(self):
        """log_nested 输出嵌套结构"""
        logger, output = _make_logger()
        logger.log_nested("长桥数据",
                          lines=[
                              "调用 account_balance：可用现金 $32000",
                              "调用 stock_positions：2 个持仓",
                          ],
                          sub_lines={
                              1: ["INTC260306C49500（45 张）", "UUUU260220C21000（20 张）"],
                          })
        text = output()
        assert "[长桥数据]" in text
        assert "account_balance" in text
        assert "INTC260306C49500" in text
        assert "UUUU260220C21000" in text

    def test_log_nested_with_title_suffix(self):
        """log_nested 带 title_suffix"""
        logger, output = _make_logger()
        logger.log_nested("账户持仓", title_suffix="可用=$32000 [模拟]",
                          lines=["AAPL: 100股"])
        text = output()
        assert "[账户持仓]" in text
        assert "可用=$32000" in text


# ================================================================
#  5. Singleton 管理
# ================================================================

class TestSingleton:
    def test_get_logger_returns_same_instance(self):
        """get_logger 返回同一实例"""
        a = get_logger()
        b = get_logger()
        assert a is b

    def test_set_logger_replaces_instance(self):
        """set_logger 替换全局实例"""
        custom = RichLogger()
        set_logger(custom)
        assert get_logger() is custom

    def test_reset_logger(self):
        """reset_logger 后 get_logger 创建新实例"""
        a = get_logger()
        reset_logger()
        b = get_logger()
        assert a is not b


# ================================================================
#  6. 集成测试：模拟完整交易流程
# ================================================================

class TestIntegration:
    def test_full_trade_pipeline(self):
        """模拟完整交易管道：separator → trade flow(原始→解析→校验→提交) → push"""
        logger, output = _make_logger()

        logger.separator()
        logger.trade_start()

        logger.trade_stage("原始消息",
            tag_suffix="[-8153ms]",
            rows=[
                ("domID", "post_abc123"),
                ("content", '"CAH - $227.5 CALLS $2.70 彩票"'),
                ("position", "single"),
            ], tag_style="bold blue")

        logger.trade_stage("解析消息", rows=[
            ("", "\\[BUY] CAH260227C227500.US $2.7"),
        ], tag_style="bold blue")

        logger.trade_stage("订单校验", rows=[
            ("查询价格", "当前市场价=$2.75，指令价=$2.70"),
            ("买入数量", "36张"),
            ("买入总价", "$9900.00"),
        ], tag_style="bold yellow")

        logger.trade_stage("提交订单", rows=[
            ("OrderID", "ORD_001"),
            ("", "\\[BUY] CAH260227C227500.US $2.75 × 36 = $9900.00"),
        ], tag_style="bold green")

        logger.trade_end()

        logger.log("订单推送", "",
                    details=[
                        "status=OrderStatus.New",
                        "submitted_quantity=36",
                        "submitted_price=2.75",
                    ],
                    tag_style="bold white",
                    header_extra=["\\[BUY]", "symbol=CAH260227C227500.US"])

        logger.log("持仓更新", "买入成交后 CAH260227C227500.US",
                    tag_style="bold magenta")

        text = output()
        assert "=" * 80 in text
        for tag in ["原始消息", "解析消息", "订单校验", "提交订单"]:
            assert tag in text
        assert "[订单推送]" in text
        assert "[持仓更新]" in text
        assert "CAH260227C227500.US" in text
        assert "$9900.00" in text

    def test_program_load_flow(self):
        """模拟程序加载流程：tag_live → append → stop → config"""
        logger, output = _make_logger()

        logger.tag_live_start("程序加载")
        logger.tag_live_append("程序加载", "长桥交易接口初始化")
        logger.tag_live_append("程序加载", "API接入点：cn")
        logger.tag_live_append("程序加载", "长桥交易接口初始化成功")
        logger.tag_live_append("程序加载", "自动交易模块初始化成功")
        logger.tag_live_append("程序加载", "订单推送监听器初始化成功")
        logger.tag_live_append("程序加载", "检查登录状态...")
        logger.tag_live_append("程序加载", "开始监控，轮询间隔: 0.2 秒")
        logger.tag_live_append("程序加载", "按 Ctrl+C 停止监控")
        logger.tag_live_stop("程序加载")

        logger.log_config("配置更新", [
            "账户类型：模拟",
            "Dry Run 模式：关闭（将真实下单）",
            "单次购买期权总价上限：$10000.0",
        ])

        text = output()
        assert "[程序加载]" in text
        assert "长桥交易接口初始化" in text
        assert "按 Ctrl+C 停止监控" in text
        assert "[配置更新]" in text
        assert "账户类型" in text


# ================================================================
#  7. 账户持仓表格
# ================================================================

class TestPositionTable:
    def test_basic_position_table(self):
        """基本持仓表格输出"""
        logger, output = _make_logger()
        title = "[bold red]\\[账户持仓][/bold red]"
        positions = [
            {
                "symbol": "TSLL.US",
                "quantity": 4802,
                "unit": "股",
                "avg_cost": 14.845,
                "position_value": 71285.69,
                "pct": 61.2,
                "records": [],
            },
        ]
        logger.print_position_table(title, positions)
        text = output()
        assert "账户持仓" in text
        assert "TSLL.US" in text
        assert "4802股" in text
        assert "$14.845" in text
        assert "61.2%" in text

    def test_position_table_with_account(self):
        """含账户信息区域"""
        logger, output = _make_logger()
        account = {
            "available_cash": 32020.12,
            "cash": 35000.00,
            "total_assets": 116509.14,
            "is_paper": True,
        }
        positions = [
            {
                "symbol": "TSLL.US",
                "quantity": 100,
                "unit": "股",
                "avg_cost": 14.845,
                "position_value": 1484.50,
                "pct": 50.0,
                "records": [],
            },
        ]
        logger.print_position_table("\\[账户持仓]", positions, account=account)
        text = output()
        assert "账户持仓" in text
        assert "可用现金" in text
        assert "$32,020.12" in text
        assert "总资产" in text
        assert "$116,509.14" in text
        assert "模拟" in text
        assert "股票仓位" in text
        assert "TSLL.US" in text

    def test_position_table_with_records(self):
        """持仓表格含交易记录"""
        logger, output = _make_logger()
        positions = [
            {
                "symbol": "AAPL.US",
                "quantity": 100,
                "unit": "股",
                "avg_cost": 175.230,
                "position_value": 17523.00,
                "pct": 15.0,
                "records": [
                    {"submitted_at": "2026-02-20 10:30:00", "side": "BUY", "qty": 100, "price": "175.23"},
                    {"submitted_at": "2026-02-25 14:00:00", "side": "SELL", "qty": 50, "price": "180.00"},
                ],
            },
        ]
        logger.print_position_table("\\[持仓]", positions)
        text = output()
        assert "AAPL.US" in text
        assert "100股" in text
        assert "BUY" in text
        assert "SELL" in text
        assert "175.23" in text

    def test_position_table_multiple_symbols(self):
        """多个持仓行"""
        logger, output = _make_logger()
        positions = [
            {
                "symbol": "TSLL.US",
                "quantity": 4802,
                "unit": "股",
                "avg_cost": 14.845,
                "position_value": 71285.69,
                "pct": 61.2,
                "records": [],
            },
            {
                "symbol": "AAPL.US",
                "quantity": 100,
                "unit": "股",
                "avg_cost": 175.230,
                "position_value": 17523.00,
                "pct": 15.0,
                "records": [],
            },
        ]
        logger.print_position_table("\\[账户持仓]", positions)
        text = output()
        assert "TSLL.US" in text
        assert "AAPL.US" in text
        assert "61.2%" in text
        assert "15.0%" in text

    def test_position_table_empty(self):
        """无持仓时表格仍能正常输出"""
        logger, output = _make_logger()
        logger.print_position_table("\\[账户持仓] 无持仓", [])
        text = output()
        assert "账户持仓" in text
        assert "股票" in text

    def test_position_update_after_fill(self):
        """模拟订单成交后更新持仓表格"""
        logger, output = _make_logger()

        logger.print_position_table(
            "\\[账户持仓] 总资产=$100,000",
            [{
                "symbol": "TSLL.US",
                "quantity": 4802,
                "unit": "股",
                "avg_cost": 14.845,
                "position_value": 71285.69,
                "pct": 71.3,
                "records": [
                    {"submitted_at": "2026-02-24 00:16:34", "side": "BUY", "qty": 800, "price": "14.38"},
                ],
            }],
        )

        logger.print_position_table(
            "\\[持仓更新] 买入成交后 TSLL.US",
            [{
                "symbol": "TSLL.US",
                "quantity": 5602,
                "unit": "股",
                "avg_cost": 14.780,
                "position_value": 82797.56,
                "pct": 75.0,
                "records": [
                    {"submitted_at": "2026-02-24 00:16:34", "side": "BUY", "qty": 800, "price": "14.38"},
                    {"submitted_at": "2026-02-28 20:05:12", "side": "BUY", "qty": 800, "price": "14.75"},
                ],
            }],
        )

        text = output()
        assert "4802股" in text
        assert "5602股" in text
        assert "持仓更新" in text
        assert "14.75" in text

    def test_position_table_with_stop_loss(self):
        """持仓表格含止损价"""
        logger, output = _make_logger()
        positions = [
            {
                "symbol": "TSLL.US",
                "quantity": 100,
                "unit": "股",
                "avg_cost": 14.845,
                "position_value": 1484.50,
                "pct": 50.0,
                "stop_loss": 13.5,
                "records": [],
            },
        ]
        logger.print_position_table("\\[持仓]", positions)
        text = output()
        assert "止损=$13.5" in text


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
