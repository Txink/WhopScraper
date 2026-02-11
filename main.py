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

# 长桥交易模块
from broker import (
    load_longport_config,
    LongPortBroker,
    PositionManager,
)
from broker.auto_trader import AutoTrader
from broker.order_formatter import (
    print_config_update_display,
    render_program_load_live,
    web_listen_timestamp,
)
from rich.live import Live

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

        # [程序加载] 流式块：先显示标题+小菊花，交易初始化与网页监听子条目逐行追加
        self._program_load_lines = []
        now = datetime.now()
        self._program_load_ts = now.strftime("%Y-%m-%d %H:%M:%S") + f".{now.microsecond // 1000:03d}"
        self._program_load_live = Live(
            render_program_load_live(
                self._program_load_lines, self._program_load_ts, show_spinner=True
            ),
            refresh_per_second=6,
        )
        self._program_load_live.start()

        def _program_load_refresh(show_spinner: bool = True) -> None:
            self._program_load_live.update(
                render_program_load_live(
                    self._program_load_lines,
                    self._program_load_ts,
                    show_spinner=show_spinner,
                )
            )

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
        """初始化交易组件（长桥API、持仓管理、自动交易器），[程序加载] 流式逐行追加"""
        try:
            # 1. 加载长桥配置
            config = load_longport_config()
            region = os.getenv("LONGPORT_REGION", "cn")
            self._program_load_lines.append((web_listen_timestamp(), "长桥交易接口初始化"))
            self._program_load_lines.append(
                (web_listen_timestamp(), f"API接入点：{region}")
            )
            self._program_load_refresh()

            # 2. 创建交易接口（连接数达上限时重试一次）
            self.broker = self._create_broker_with_retry(config)
            self._program_load_lines.append(
                (web_listen_timestamp(), "长桥交易接口初始化成功")
            )
            self._program_load_refresh()

            # 3. 创建持仓管理器（启动后由 sync_from_broker 统一输出账户持仓摘要，此处不再重复打日志）
            self.position_manager = PositionManager(storage_file="data/positions.json")

            # 4. 创建自动交易器（传入 position_manager，卖出比例 1/3 等相对该期权所有买入数量计算）
            self.auto_trader = AutoTrader(broker=self.broker, position_manager=self.position_manager)
            self._program_load_lines.append(
                (web_listen_timestamp(), "自动交易模块初始化成功")
            )
            self._program_load_refresh()

            # 5. 创建订单状态推送监听器（长桥交易推送）
            try:
                self.order_push_monitor = OrderPushMonitor(config=config)
                self.order_push_monitor.on_order_changed(self._on_order_changed)
                self._program_load_lines.append(
                    (web_listen_timestamp(), "订单推送监听器初始化成功")
                )
                self._program_load_refresh()
            except Exception as e:
                logger.warning("订单推送监听未启用: %s", e)
                self.order_push_monitor = None

            # [配置更新] 延后到 run() 中、账户持仓输出前再打印
            self._config_update_lines = [
                f"账户类型：{'模拟' if self.broker.is_paper else '真实'}",
                f"单次购买期权总价上限：${self.auto_trader.max_option_total_price}",
                f"单次购买期权数量上限：{self.auto_trader.max_option_quantity}张",
                f"价差容忍度：{self.auto_trader.price_deviation_tolerance}%",
                f"容忍度内买入价：{'市价' if self.auto_trader.buy_use_market_when_within_tolerance else '指令价'}",
            ]
        except Exception as e:
            self._program_load_live.stop()
            logger.exception("❌ 交易组件初始化失败（详见下方堆栈，请检查 .env 中长桥凭证与网络）: %s", e)
            logger.warning("程序将以监控模式运行（不执行交易）")
            self.broker = None
            self.position_manager = None
            self.auto_trader = None
            self.order_push_monitor = None
            self._config_update_lines = None

    def _on_order_changed(self, event):
        """长桥订单状态推送回调：更新本地持仓与交易记录"""
        if self.position_manager and self.broker:
            try:
                self.position_manager.on_order_push(event, self.broker)
            except Exception as e:
                logger.warning("订单推送更新持仓失败: %s", e)
        
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

        # 继续往 [程序加载] 流式块追加网页监听相关子条目（复用 __init__ 中已启动的 Live）
        # 创建浏览器管理器
        self.browser = BrowserManager(
            headless=Config.HEADLESS,
            slow_mo=Config.SLOW_MO,
            storage_state_path=Config.STORAGE_STATE_PATH,
            log_lines=self._program_load_lines,
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
            self._program_load_live.stop()
            print("错误: 没有配置任何监控页面")
            return False
        
        # 检查登录状态（使用第一个页面）
        first_url = page_configs[0][0]
        self._program_load_lines.append((web_listen_timestamp(), "检查登录状态..."))
        self._program_load_refresh()
        if not await self.browser.is_logged_in(first_url):
            print("需要登录...")
            success = await self.browser.login(
                Config.WHOP_EMAIL,
                Config.WHOP_PASSWORD,
                Config.LOGIN_URL
            )
            
            if not success:
                self._program_load_live.stop()
                print("登录失败，请检查凭据是否正确")
                return False
        
        # 使用单页面监控（向后兼容）
        if not await self._setup_single_page_monitor(page, page_configs[0]):
            self._program_load_live.stop()
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
            self._program_load_live.stop()
            print(f"无法导航到目标页面: {url}")
            return False
        
        # 使用传统轮询监控器
        self._program_load_lines.append(
            (web_listen_timestamp(), f"使用轮询监控模式，间隔：{Config.POLL_INTERVAL} 秒")
        )
        self._program_load_refresh()
        self.monitor = MessageMonitor(
            page=page,
            poll_interval=Config.POLL_INTERVAL,
            skip_initial_messages=Config.SKIP_INITIAL_MESSAGES
        )   
        
        # 设置回调
        self.monitor.on_new_record(self._on_record)
        return True
    
    def _on_record(self, record: Record):
        """
        新指令回调 - 处理交易信号（单页面模式）
        
        Args:
            instruction: 解析出的指令
        """
        self._handle_instruction(record.instruction, "OPTION")
    
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
    
    async def run(self):
        """运行抓取器"""
        if not await self.setup():
            return

        self._program_load_lines.append(
            (web_listen_timestamp(), f"开始监控，轮询间隔: {Config.POLL_INTERVAL} 秒")
        )
        self._program_load_lines.append((web_listen_timestamp(), "按 Ctrl+C 停止监控"))
        self._program_load_refresh()

        if self.order_push_monitor:
            self.order_push_monitor.start(
                log_lines=self._program_load_lines,
                log_refresh=self._program_load_refresh,
            )
            time.sleep(1)  # 留时间让后台线程完成订阅并刷新「已订阅」到 [程序加载]

        self._program_load_refresh(show_spinner=False)
        self._program_load_live.stop()
        print()

        if self._config_update_lines is not None:
            print_config_update_display(self._config_update_lines)

        if self.position_manager and self.broker:
            try:
                self.position_manager.sync_from_broker(self.broker)
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


async def main():
    """主函数"""
    print("""
╔══════════════════════════════════════════════════════════╗
║           期权信号抓取器 + 自动交易系统 v2.1              ║
║           Option Signal Scraper & Auto Trading           ║
╚══════════════════════════════════════════════════════════╝
    """)
    
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
    
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, signal_handler)
    
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
  # 正常运行（监控并执行交易）
  python3 main.py
  # 分析本地HTML文件
  python3 analyze_local_messages.py debug/page_xxx.html
        """
    )
    parser.add_argument(
        '--version',
        action='version',
        version='期权信号抓取器 v2.1'
    )
    
    return parser.parse_args()


if __name__ == "__main__":
    # 正常运行模式
    asyncio.run(main())
