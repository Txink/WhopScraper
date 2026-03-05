#!/usr/bin/env python3
"""
期权信号抓取器 - 主程序入口
实时监控 Whop 页面，解析期权和正股交易信号，自动执行交易
"""
import asyncio
import signal
import sys
import logging
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple

# 优先从项目根目录加载 .env，避免因工作目录不同导致长桥等配置未加载
_project_root = Path(__file__).resolve().parent
_env_path = _project_root / ".env"
if _env_path.is_file():
    from dotenv import load_dotenv
    load_dotenv(_env_path)

from config import Config
from scraper.browser import BrowserManager
from scraper.monitor import MessageMonitor, OrderPushMonitor
from models.instruction import OptionInstruction
from models.record import Record
from models.stock_instruction import StockInstruction

# 长桥交易模块
from broker import (
    load_longport_config,
    LongPortBroker,
    PositionManager,
)
from broker.auto_trader import AutoTrader
from broker.order_formatter import (
    web_listen_timestamp,
)
from utils.rich_logger import get_logger

# 确保日志目录存在
os.makedirs(Config.LOG_DIR, exist_ok=True)

# 配置日志
log_level = getattr(logging, Config.LOG_LEVEL.upper(), logging.INFO)
logging.basicConfig(
    level=log_level,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(f'{Config.LOG_DIR}/trading.log', encoding='utf-8')
    ]
)
logger = logging.getLogger(__name__)


class SignalScraper:
    """期权信号抓取器 + 自动交易系统"""
    
    def __init__(self, selected_page: Optional[Tuple[str, str, str]] = None, use_multi_page: bool = False):
        """
        初始化信号抓取器
        
        Args:
            selected_page: 本次要监控的单个页面 (url, type, name)，type 为 'option' 或 'stock'。若指定则仅监控该页。
            use_multi_page: 是否使用多页面监控（当未指定 selected_page 且配置了多页时使用）
        """
        self.browser: Optional[BrowserManager] = None
        self.monitor: Optional[MessageMonitor] = None
        self.selected_page = selected_page
        self.use_multi_page = use_multi_page
        self._shutdown_event = asyncio.Event()
        
        # 交易组件
        self.broker: Optional[LongPortBroker] = None
        self.position_manager: Optional[PositionManager] = None
        self.auto_trader: Optional[AutoTrader] = None
        self.order_push_monitor: Optional[OrderPushMonitor] = None
        self._warned_no_trader = False  # 仅对「交易组件未初始化」告警一次

        # [程序加载] 通过 RichLogger 的 tag_live 模式实现流式追加
        self._rlogger = get_logger()
        self._rlogger.tag_live_start("程序加载")

        # 兼容层：browser/monitor 等组件仍使用 (log_lines, log_refresh) 回调模式
        self._program_load_lines: list = []

        def _program_load_refresh(show_spinner: bool = True) -> None:
            tag_data = self._rlogger.tag_live_get_data("程序加载")
            if tag_data is not None:
                tag_data.show_spinner = show_spinner
            self._rlogger.tag_live_refresh("程序加载")

        self._program_load_refresh = _program_load_refresh

        # 初始化交易组件
        self._init_trading_components()

    def _create_broker_with_retry(self, config, retry_delay: int = 35):
        """
        创建 LongPortBroker，若因连接数达上限(connections limitation)失败则等待后重试一次。
        """
        try:
            return LongPortBroker(config)
        except Exception as e:
            err_msg = str(e).lower()
            if "connections limitation" in err_msg or "limit" in err_msg and "online" in err_msg:
                logger.warning(
                    "长桥连接数已达上限，请关闭其他使用同一账户的终端/程序。%s 秒后自动重试一次…",
                    retry_delay,
                )
                time.sleep(retry_delay)
                return LongPortBroker(config)
            raise

    def _init_trading_components(self):
        """初始化交易组件（长桥API、持仓管理、自动交易器），通过 logger tag_live 流式追加"""
        try:
            config = load_longport_config()
            region = os.getenv("LONGPORT_REGION", "cn")
            self._rlogger.tag_live_append("程序加载", "长桥交易接口初始化")
            self._rlogger.tag_live_append("程序加载", f"API接入点：{region}")

            self.broker = self._create_broker_with_retry(config)
            self._rlogger.tag_live_append("程序加载", "长桥交易接口初始化成功")

            if self.selected_page and self.selected_page[1] == "stock":
                position_file = "data/stock_positions.json"
                is_stock_mode = True
            else:
                position_file = "data/positions.json"
                is_stock_mode = False
            self.position_manager = PositionManager(storage_file=position_file, is_stock_mode=is_stock_mode)

            self.auto_trader = AutoTrader(broker=self.broker, position_manager=self.position_manager)
            self._rlogger.tag_live_append("程序加载", "自动交易模块初始化成功")

            try:
                _is_option_mode = not (self.selected_page and self.selected_page[1] == "stock")
                self.order_push_monitor = OrderPushMonitor(config=config, is_option_mode=_is_option_mode)
                self.order_push_monitor.on_order_changed(self._on_order_changed)
                self._rlogger.tag_live_append("程序加载", "订单推送监听器初始化成功")
            except Exception as e:
                logger.warning("订单推送监听未启用: %s", e)
                self.order_push_monitor = None

            _default_stop = os.getenv("ENABLE_DEFAULT_STOP_LOSS", "false").strip().lower() in ("true", "1", "yes")
            _default_stop_ratio = os.getenv("DEFAULT_STOP_LOSS_RATIO", "38").strip() or "38"
            _ctx_limit = os.getenv("CONTEXT_SEARCH_LIMIT", "10").strip() or "10"
            _is_paper = self.broker.is_paper
            _dry_run = self.broker.dry_run
            self._config_update_lines = [
                f"账户类型：{'模拟' if _is_paper else '真实'}",
                f"Dry Run 模式：{'开启（不实际下单，仅打印）' if _dry_run else '关闭（将真实下单）'}",
                f"单次购买期权总价上限：${self.auto_trader.max_option_total_price}",
                f"单次购买期权数量上限：{self.auto_trader.max_option_quantity}张",
                f"价差容忍度：{self.auto_trader.price_deviation_tolerance}%",
                f"容忍度内买入价：{'市价' if self.auto_trader.buy_use_market_when_within_tolerance else '指令价'}",
                f"默认止损：{'开启，' + _default_stop_ratio + '%' if _default_stop else '关闭'}",
                f"扫描历史消息数量分析上下文：前{_ctx_limit}条",
                f"下单是否需要确认：{str(self.auto_trader.require_confirmation).lower()}",
            ]
            if not _is_paper and not _dry_run:
                self._config_update_lines.append("⚠️ 当前为真实账户且 Dry Run 已关闭，下单将产生实际资金变动，请确认配置无误")
        except Exception as e:
            self._rlogger.tag_live_stop("程序加载")
            logger.exception("❌ 交易组件初始化失败（详见下方堆栈，请检查 .env 中长桥凭证与网络）: %s", e)
            logger.warning("程序将以监控模式运行（不执行交易）")
            self.broker = None
            self.position_manager = None
            self.auto_trader = None
            self.order_push_monitor = None
            self._config_update_lines = None

    def _on_order_changed(self, event):
        """长桥订单状态推送回调：更新本地持仓与交易记录，并处理未成交订单的止盈止损补偿任务"""
        if self.position_manager and self.broker:
            try:
                self.position_manager.on_order_push(event, self.broker)
            except Exception as e:
                logger.warning("订单推送更新持仓失败: %s", e)
        if self.auto_trader:
            try:
                self.auto_trader.on_order_push_for_pending_modify(event)
            except Exception as e:
                logger.warning("止盈止损补偿任务处理失败: %s", e)
        
    async def setup(self) -> bool:
        """
        设置浏览器和监控器
        
        Returns:
            是否设置成功
        """
        # 验证配置
        if not Config.validate():
            create_env_template()
            return False

        # 浏览器管理器仍使用 (log_lines, log_refresh) 回调；
        # 通过桥接列表将 browser 的 append 转发到 logger.tag_live_append
        class _BridgeList(list):
            """append 时同步到 RichLogger tag_live"""
            def __init__(self, rlogger, tag):
                super().__init__()
                self._rlogger = rlogger
                self._tag = tag
            def append(self, item):
                super().append(item)
                if isinstance(item, tuple) and len(item) == 2:
                    self._rlogger.tag_live_append(self._tag, item[1])

        bridge_lines = _BridgeList(self._rlogger, "程序加载")
        self._program_load_lines = bridge_lines

        self.browser = BrowserManager(
            headless=Config.HEADLESS,
            slow_mo=Config.SLOW_MO,
            storage_state_path=Config.STORAGE_STATE_PATH,
            log_lines=bridge_lines,
            log_refresh=self._program_load_refresh,
        )
        
        # 启动浏览器
        page = await self.browser.start()
        
        # 确定本次监控的页面：若指定了 selected_page 则仅监控该页，否则从配置取（可能多页）
        if self.selected_page:
            page_configs = [self.selected_page]
        else:
            page_configs = Config.get_all_pages()
        
        if not page_configs:
            self._rlogger.tag_live_stop("程序加载")
            print("错误: 没有配置任何监控页面")
            return False
        
        # 检查登录状态（使用第一个页面）
        first_url = page_configs[0][0]
        self._rlogger.tag_live_append("程序加载", "检查登录状态...")
        if not await self.browser.is_logged_in(first_url):
            print("需要登录...")
            success = await self.browser.login(
                Config.WHOP_EMAIL,
                Config.WHOP_PASSWORD,
                Config.LOGIN_URL
            )
            
            if not success:
                self._rlogger.tag_live_stop("程序加载")
                print("登录失败，请检查凭据是否正确")
                return False
        
        # 使用单页面监控（向后兼容）
        if not await self._setup_single_page_monitor(page, page_configs[0]):
            self._rlogger.tag_live_stop("程序加载")
            return False
        
        return True
    
    async def _setup_single_page_monitor(self, page, page_config):
        """
        设置单页面监控
        
        Args:
            page: 浏览器页面对象
            page_config: (url, page_type, name) 元组
        """
        url, page_type = page_config[0], page_config[1]
        
        # 导航到目标页面
        if not await self.browser.navigate(url):
            self._rlogger.tag_live_stop("程序加载")
            print(f"无法导航到目标页面: {url}")
            return False
        
        self._rlogger.tag_live_append("程序加载", f"使用轮询监控模式，间隔：{Config.POLL_INTERVAL} 秒")
        skip_initial = Config.SKIP_INITIAL_MESSAGES
        self._rlogger.tag_live_append("程序加载", "跳过首次历史消息：%s" % ("开启" if skip_initial else "关闭"))
        self.monitor = MessageMonitor(
            page=page,
            poll_interval=Config.POLL_INTERVAL,
            skip_initial_messages=skip_initial,
            page_type=page_type,
        )

        # 设置回调
        self.monitor.on_new_record(self._on_record)
        return True

    def _on_record(self, record: Record):
        """新指令回调 - 按期权/股票分支处理。"""
        inst = record.instruction
        if inst is None:
            return
        if isinstance(inst, OptionInstruction):
            self._handle_instruction(inst, "OPTION")
        elif isinstance(inst, StockInstruction):
            self._handle_stock_instruction(inst)
    
    def _handle_instruction(self, instruction: OptionInstruction, source: str):
        """
        处理交易指令（使用 AutoTrader）
        
        Args:
            instruction: 解析出的指令
            source: 信号来源
        """
        # 如果没有初始化交易组件，只记录信号（仅首次打 WARNING，避免刷屏）
        if not self.auto_trader or not self.broker:
            if not self._warned_no_trader:
                logger.warning("⚠️  交易组件未初始化，仅记录信号（请查看启动时「交易组件初始化失败」错误原因）")
                self._warned_no_trader = True
            else:
                logger.debug("交易组件未初始化，跳过执行")
            return
        
        # 检查自动交易是否启用
        if not self.broker.auto_trade:
            logger.info("ℹ️  自动交易未启用，仅记录信号")
            return
        
        try:
            # 使用 AutoTrader 执行指令
            result = self.auto_trader.execute_instruction(instruction)
            
            if result:
                # 如果是买入订单，更新持仓管理器（静默，不打印摘要）
                if instruction.instruction_type == "BUY" and self.position_manager:
                    from broker import create_position_from_order
                    
                    symbol = instruction.symbol
                    if symbol:
                        position = create_position_from_order(
                            symbol=symbol,
                            ticker=instruction.ticker,
                            option_type=instruction.option_type,
                            strike=instruction.strike,
                            expiry=instruction.expiry or "本周",
                            quantity=result.get('quantity', 1),
                            avg_cost=instruction.price or 0,
                            order_id=result.get('order_id', '')
                        )
                        self.position_manager.add_position(position)
            else:
                pass  # 指令执行失败或被跳过，不输出日志
        except Exception as e:
            logger.error(f"❌ 处理指令失败: {e}", exc_info=True)

    def _calc_stock_quantity(self, ticker: str, sell_quantity: Optional[str], position_size: Optional[str]) -> Optional[int]:
        """根据 watched_stocks 配置计算股数（与 generate_check_stock.py 逻辑一致）。"""
        from utils.watched_stocks import get_stock_position_shares, get_bucket_ratio
        position = get_stock_position_shares(ticker)
        if not position or position <= 0:
            return None
        bucket = get_bucket_ratio(ticker)
        base = position * bucket
        if sell_quantity:
            if sell_quantity == '1/2':
                return max(1, int(base * 0.5))
            if '/' in sell_quantity and sell_quantity not in ('小仓位', '全部'):
                try:
                    num, den = sell_quantity.split('/')
                    return max(1, int(base * int(num) / int(den)))
                except Exception:
                    pass
        if position_size and '一半' in position_size:
            return max(1, int(base * 0.5))
        return max(1, int(base))

    def _handle_stock_instruction(self, instruction: StockInstruction):
        """处理股票交易指令：校验、打印、下单。"""
        if not self.auto_trader or not self.broker:
            if not self._warned_no_trader:
                logger.warning("⚠️  交易组件未初始化，仅记录信号（请查看启动时「交易组件初始化失败」错误原因）")
                self._warned_no_trader = True
            return

        if not self.broker.auto_trade:
            logger.info("ℹ️  自动交易未启用，仅记录信号")
            return

        try:
            instruction.ensure_symbol()
            symbol = instruction.symbol
            if not symbol:
                logger.warning("⚠️  无法确定股票代码，跳过")
                return
            if instruction.instruction_type == "BUY":
                self._execute_stock_buy(instruction)
            elif instruction.instruction_type == "SELL":
                self._execute_stock_sell(instruction)
            else:
                logger.info("📈 [股票] 非买卖指令，仅记录: %s", instruction)
        except Exception as e:
            logger.error("❌ 股票指令执行失败: %s", e, exc_info=True)

    def _execute_stock_buy(self, instruction: StockInstruction):
        """执行股票买入：查行情 → 价格校验 → 计算数量 → 下单。"""
        from broker.order_formatter import print_order_validation_display
        symbol = instruction.symbol
        ticker = instruction.ticker or symbol.replace('.US', '')
        deviation_tolerance = float(os.getenv('STOCK_PRICE_DEVIATION_TOLERANCE', '1'))

        if instruction.price_range:
            instruction_price = (instruction.price_range[0] + instruction.price_range[1]) / 2
        elif instruction.price is not None:
            instruction_price = instruction.price
        else:
            logger.warning("⚠️  股票买入指令缺少价格，跳过")
            return

        price = instruction_price
        price_line = ""
        reject_reason = None

        try:
            quotes = self.broker.get_stock_quote([symbol])
            if quotes:
                market_price = quotes[0].get("last_done", 0)
                if market_price > 0:
                    deviation_pct = (market_price - instruction_price) / instruction_price * 100
                    if deviation_pct > deviation_tolerance:
                        reject_reason = (
                            f"当前市价 ${market_price:.2f} 高于指令价 ${instruction_price:.2f} "
                            f"超过 {deviation_tolerance}%，未提交订单"
                        )
                        price_line = f"查询价格：市场价=${market_price:.2f}，指令价=${instruction_price:.2f}，偏差={deviation_pct:.1f}%"
                    else:
                        raw_price = market_price if market_price < instruction_price else instruction_price
                        price = round(raw_price, 2)
                        price_line = (
                            f"查询价格：市场价=${market_price:.2f}，指令价=${instruction_price:.2f}，"
                            f"偏差={abs(deviation_pct):.1f}%，使用价格=${price:.2f}"
                        )
                else:
                    price_line = "查询价格：市场价格无效，使用指令价格"
            else:
                price_line = "查询价格：无法获取报价，使用指令价格"
        except Exception as e:
            price_line = f"查询价格：获取报价异常（{e}），使用指令价格=${price:.2f}"

        quantity = instruction.quantity
        if not quantity:
            quantity = self._calc_stock_quantity(ticker, None, instruction.position_size)
        if not quantity or quantity <= 0:
            reject_reason = reject_reason or f"无法计算买入数量（{ticker} 未在 watched_stocks 配置），未提交订单"
            quantity = 0

        total_price = (quantity or 0) * price
        quantity_line = f"买入数量：{quantity} 股（position_size={instruction.position_size or '默认'}）"
        total_line = f"买入总价：${total_price:.2f}"

        print_order_validation_display(
            side="BUY",
            symbol=symbol,
            price=price,
            price_line=price_line,
            quantity_line=quantity_line,
            total_line=total_line,
            instruction_timestamp=instruction.timestamp,
            reject_reason=reject_reason,
        )
        if reject_reason or not quantity:
            return

        try:
            self.broker.submit_stock_order(
                symbol=symbol,
                side="BUY",
                quantity=quantity,
                price=price,
                order_type="LIMIT",
                remark=f"Auto stock buy: {(instruction.raw_message or '')[:50]}",
            )
        except Exception as e:
            err_msg = str(e)
            logger.error("股票买入下单失败: %s", err_msg)
            print_order_validation_display(
                side="BUY",
                symbol=symbol,
                price=price,
                price_line="",
                quantity_line=f"下单数量：{quantity} 股",
                total_line="",
                instruction_timestamp=instruction.timestamp,
                reject_reason=f"下单失败：{err_msg}",
            )

    def _execute_stock_sell(self, instruction: StockInstruction):
        """执行股票卖出：计算数量 → 查行情 → 下单。"""
        from broker.order_formatter import print_sell_validation_display
        symbol = instruction.symbol
        ticker = instruction.ticker or symbol.replace('.US', '')

        if instruction.price_range:
            instruction_price = round((instruction.price_range[0] + instruction.price_range[1]) / 2, 2)
        elif instruction.price is not None:
            instruction_price = round(instruction.price, 2)
        else:
            instruction_price = None

        quantity = instruction.quantity
        if not quantity:
            quantity = self._calc_stock_quantity(ticker, instruction.sell_quantity, None)

        reject_reason = None
        if not quantity or quantity <= 0:
            reject_reason = f"无法计算卖出数量（{ticker} 未在 watched_stocks 配置），未提交订单"
            quantity = 0

        detail_lines = [
            f"卖出比例/数量标注：{instruction.sell_quantity or '全部'}",
            f"计算股数：{quantity} 股",
        ]
        if instruction_price:
            detail_lines.append(f"目标价格：${instruction_price:.2f}")
        if instruction.sell_reference_label:
            detail_lines.append(f"参考买入：{instruction.sell_reference_label}")

        print_sell_validation_display(
            symbol=symbol,
            quantity=quantity,
            instruction_timestamp=instruction.timestamp,
            detail_lines=detail_lines,
            reject_reason=reject_reason,
        )
        if reject_reason or not quantity:
            return

        try:
            self.broker.submit_stock_order(
                symbol=symbol,
                side="SELL",
                quantity=quantity,
                price=instruction_price,
                order_type="LIMIT" if instruction_price else "MARKET",
                remark=f"Auto stock sell: {(instruction.raw_message or '')[:50]}",
            )
        except Exception as e:
            from broker.order_formatter import print_sell_validation_display as _psv
            err_msg = str(e)
            logger.error("股票卖出下单失败: %s", err_msg)
            _psv(
                symbol=symbol,
                quantity=quantity,
                instruction_timestamp=instruction.timestamp,
                detail_lines=[f"卖出价格：${instruction_price:.2f}" if instruction_price else "市价单"],
                reject_reason=f"下单失败：{err_msg}",
            )

    async def run(self):
        """运行抓取器"""
        if not await self.setup():
            return

        self._rlogger.tag_live_append("程序加载", f"开始监控，轮询间隔: {Config.POLL_INTERVAL} 秒")
        self._rlogger.tag_live_append("程序加载", "按 Ctrl+C 停止监控")

        if self.order_push_monitor:
            self.order_push_monitor.start(
                log_lines=self._program_load_lines,
                log_refresh=self._program_load_refresh,
            )
            time.sleep(1)

        if self.monitor:
            await self.monitor.scan_once()

        self._rlogger.tag_live_stop("程序加载")
        print()

        if self.position_manager and self.broker:
            try:
                is_stock = bool(self.selected_page and self.selected_page[1] == "stock")
                self.position_manager.sync_from_broker(
                    self.broker, full_refresh=is_stock,
                    config_lines=self._config_update_lines,
                )
            except Exception as e:
                logger.warning("启动时同步账户/持仓失败: %s", e)

        try:
            if self.monitor:
                await self.monitor.start(skip_start_message=True)
            else:
                print("错误: 没有可用的监控器")
        except KeyboardInterrupt:
            print("\n收到停止信号...")
        finally:
            await self.cleanup()
    
    async def cleanup(self):
        """清理资源"""
        logger.info("正在清理资源...")
        
        # 保存持仓
        if self.position_manager:
            self.position_manager.print_summary()
            logger.info("持仓已保存")
        
        if self.monitor:
            self.monitor.stop()
            logger.info("页面监控已停止")

        if self.order_push_monitor:
            self.order_push_monitor.stop()
            logger.info("订单推送监听已停止")

        if self.broker:
            try:
                self.broker.close()
                logger.info("长桥连接已释放")
            except Exception as e:
                logger.debug("释放长桥连接时忽略: %s", e)

        # 关闭浏览器
        if self.browser:
            await self.browser.close()
            logger.info("浏览器已关闭")
        
        logger.info("✅ 程序已安全退出")


async def main(args=None):
    """主函数"""
    # 命令行参数覆盖 .env 中的账户模式
    if args is not None:
        if args.mode:
            os.environ["LONGPORT_MODE"] = args.mode
        if args.dry_run is not None:
            os.environ["LONGPORT_DRY_RUN"] = "true" if args.dry_run else "false"

    _mode = os.getenv("LONGPORT_MODE", "paper")
    _dry_run = os.getenv("LONGPORT_DRY_RUN", "true").lower() in ("true", "1", "yes")
    _mode_label = "🧪 模拟账户" if _mode == "paper" else "💰 真实账户"
    _dry_label = " | Dry Run 开启" if _dry_run else ""

    print(f"""
╔══════════════════════════════════════════════════════════╗
║           期权信号抓取器 + 自动交易系统 v2.1              ║
║           Option Signal Scraper & Auto Trading           ║
╚══════════════════════════════════════════════════════════╝
    """)
    print(f"账户模式：{_mode_label}{_dry_label}\n")

    selected = Config.load()
    if selected is None:
        return
    scraper = SignalScraper(selected_page=selected)
    
    # 设置信号处理
    loop = asyncio.get_event_loop()
    
    def signal_handler():
        print("\n收到终止信号，正在退出...")
        for task in asyncio.all_tasks(loop):
            task.cancel()
    
    try:
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, signal_handler)
    except NotImplementedError:
        pass
    
    try:
        await scraper.run()
    except asyncio.CancelledError:
        pass
    finally:
        await scraper.cleanup()

def parse_arguments():
    """解析命令行参数"""
    import argparse

    parser = argparse.ArgumentParser(
        description="期权信号抓取器 + 自动交易系统",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例用法:
  python3 main.py              # 使用 .env 中配置的账户模式
  python3 main.py --paper      # 强制使用模拟账户
  python3 main.py --real       # 强制使用真实账户
  python3 main.py --real --dry-run    # 真实账户 + 不实际下单（调试）
  python3 main.py --real --no-dry-run # 真实账户 + 实际下单
        """
    )
    parser.add_argument(
        '--version',
        action='version',
        version='期权信号抓取器 v2.1'
    )

    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument(
        '--paper',
        dest='mode',
        action='store_const',
        const='paper',
        help='使用模拟账户（覆盖 .env 中的 LONGPORT_MODE）'
    )
    mode_group.add_argument(
        '--real',
        dest='mode',
        action='store_const',
        const='real',
        help='使用真实账户（覆盖 .env 中的 LONGPORT_MODE）'
    )

    dry_run_group = parser.add_mutually_exclusive_group()
    dry_run_group.add_argument(
        '--dry-run',
        dest='dry_run',
        action='store_true',
        default=None,
        help='启用 Dry Run（不实际下单，仅打印）'
    )
    dry_run_group.add_argument(
        '--no-dry-run',
        dest='dry_run',
        action='store_false',
        help='关闭 Dry Run（将实际下单）'
    )

    return parser.parse_args()


if __name__ == "__main__":
    _args = parse_arguments()
    asyncio.run(main(_args))
