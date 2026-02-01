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
from typing import Optional

from config import Config, create_env_template
from scraper.browser import BrowserManager
from scraper.monitor import MessageMonitor
from scraper.multi_monitor import MultiPageMonitor
from models.instruction import OptionInstruction

# 长桥交易模块
from broker import (
    load_longport_config,
    LongPortBroker,
    PositionManager,
    create_position_from_order,
    convert_to_longport_symbol,
    calculate_quantity
)
from broker.risk_controller import RiskController, AutoTrailingStopLoss

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
    
    def __init__(self, use_multi_page: bool = True):
        """
        初始化信号抓取器
        
        Args:
            use_multi_page: 是否使用多页面监控（默认True）
        """
        self.browser: Optional[BrowserManager] = None
        self.monitor: Optional[MessageMonitor] = None
        self.multi_monitor: Optional[MultiPageMonitor] = None
        self.use_multi_page = use_multi_page
        self._shutdown_event = asyncio.Event()
        
        # 交易组件
        self.broker: Optional[LongPortBroker] = None
        self.position_manager: Optional[PositionManager] = None
        self.risk_controller: Optional[RiskController] = None
        self.auto_trailing: Optional[AutoTrailingStopLoss] = None
        
        # 初始化交易组件
        self._init_trading_components()
    
    def _init_trading_components(self):
        """初始化交易组件（长桥API、持仓管理、风险控制）"""
        try:
            # 1. 加载长桥配置
            logger.info("正在初始化长桥交易接口...")
            config = load_longport_config()
            
            # 2. 创建交易接口
            self.broker = LongPortBroker(config)
            logger.info("✅ 长桥交易接口初始化成功")
            
            # 3. 创建持仓管理器
            self.position_manager = PositionManager(storage_file="data/positions.json")
            logger.info(f"✅ 持仓管理器初始化成功（当前持仓: {len(self.position_manager.get_all_positions())} 个）")
            
            # 4. 创建风险控制器
            self.risk_controller = RiskController(
                broker=self.broker,
                position_manager=self.position_manager,
                check_interval=30  # 30秒检查一次
            )
            
            # 设置风险控制回调
            self.risk_controller.on_stop_loss = self._on_stop_loss_triggered
            self.risk_controller.on_take_profit = self._on_take_profit_triggered
            self.risk_controller.on_risk_alert = self._on_risk_alert
            
            logger.info("✅ 风险控制器初始化成功")
            
            # 5. 创建自动移动止损
            self.auto_trailing = AutoTrailingStopLoss(
                risk_controller=self.risk_controller,
                trailing_pct=10.0,  # 10% 回撤
                check_interval=60  # 60秒检查一次
            )
            logger.info("✅ 自动移动止损初始化成功")
            
            # 启动风险控制（如果启用了自动交易）
            if self.broker.auto_trade:
                self.risk_controller.start()
                self.auto_trailing.start()
                logger.info("🚀 风险控制系统已启动")
            else:
                logger.info("ℹ️  自动交易未启用，风险控制系统待命")
            
        except Exception as e:
            logger.error(f"❌ 交易组件初始化失败: {e}")
            logger.warning("程序将以监控模式运行（不执行交易）")
            self.broker = None
            self.position_manager = None
            self.risk_controller = None
            self.auto_trailing = None
    
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
        
        # 创建浏览器管理器
        self.browser = BrowserManager(
            headless=Config.HEADLESS,
            slow_mo=Config.SLOW_MO,
            storage_state_path=Config.STORAGE_STATE_PATH
        )
        
        # 启动浏览器
        page = await self.browser.start()
        
        # 获取所有需要监控的页面配置
        page_configs = Config.get_all_pages()
        
        if not page_configs:
            print("错误: 没有配置任何监控页面")
            return False
        
        # 检查登录状态（使用第一个页面）
        first_url = page_configs[0][0]
        print("正在检查登录状态...")
        if not await self.browser.is_logged_in(first_url):
            print("需要登录...")
            success = await self.browser.login(
                Config.WHOP_EMAIL,
                Config.WHOP_PASSWORD,
                Config.LOGIN_URL
            )
            
            if not success:
                print("登录失败，请检查凭据是否正确")
                return False
        
        # 判断是使用多页面监控还是单页面监控
        if self.use_multi_page and len(page_configs) > 1:
            # 使用多页面监控
            print(f"使用多页面监控模式（共 {len(page_configs)} 个页面）")
            await self._setup_multi_page_monitor(page, page_configs)
        else:
            # 使用单页面监控（向后兼容）
            print("使用单页面监控模式")
            await self._setup_single_page_monitor(page, page_configs[0])
        
        return True
    
    async def _setup_single_page_monitor(self, page, page_config):
        """
        设置单页面监控（向后兼容模式）
        
        Args:
            page: 浏览器页面对象
            page_config: (url, page_type) 元组
        """
        url, page_type = page_config
        
        # 导航到目标页面
        if not await self.browser.navigate(url):
            print(f"无法导航到目标页面: {url}")
            return False
        
        # 创建单页面监控器
        self.monitor = MessageMonitor(
            page=page,
            poll_interval=Config.POLL_INTERVAL,
            output_file=Config.OUTPUT_FILE,
            enable_sample_collection=Config.ENABLE_SAMPLE_COLLECTION,
            display_mode=Config.DISPLAY_MODE
        )
        
        # 设置回调
        self.monitor.on_new_instruction(self._on_instruction)
        
        print(f"✅ 单页面监控器已设置: {page_type.upper()} - {url}")
    
    async def _setup_multi_page_monitor(self, page, page_configs):
        """
        设置多页面监控
        
        Args:
            page: 浏览器页面对象
            page_configs: [(url, page_type), ...] 列表
        """
        # 创建多页面监控器
        self.multi_monitor = MultiPageMonitor(
            poll_interval=Config.POLL_INTERVAL,
            output_file=Config.OUTPUT_FILE,
            enable_sample_collection=Config.ENABLE_SAMPLE_COLLECTION,
            display_mode=Config.DISPLAY_MODE
        )
        
        # 为每个页面创建浏览器上下文和页面
        for url, page_type in page_configs:
            # 对于第一个页面，使用已有的 page
            if url == page_configs[0][0]:
                current_page = page
            else:
                # 为其他页面创建新标签页
                current_page = await self.browser.context.new_page()
            
            # 导航到页面
            print(f"正在导航到 {page_type.upper()} 页面: {url}")
            await current_page.goto(url, wait_until="domcontentloaded", timeout=30000)
            
            # 添加到多页面监控器
            self.multi_monitor.add_page(
                page=current_page,
                page_type=page_type,
                url=url,
                enabled=True
            )
        
        # 设置回调
        self.multi_monitor.on_new_instruction(self._on_instruction_with_type)
        
        print(f"✅ 多页面监控器已设置，共 {len(page_configs)} 个页面")
    
    def _on_instruction(self, instruction: OptionInstruction):
        """
        新指令回调 - 处理交易信号（单页面模式）
        
        Args:
            instruction: 解析出的指令
        """
        self._handle_instruction(instruction, "OPTION")
    
    def _on_instruction_with_type(self, instruction: OptionInstruction, page_type: str):
        """
        新指令回调 - 处理交易信号（多页面模式）
        
        Args:
            instruction: 解析出的指令
            page_type: 页面类型 ('option' 或 'stock')
        """
        self._handle_instruction(instruction, page_type.upper())
    
    def _handle_instruction(self, instruction: OptionInstruction, source: str):
        """
        处理交易指令
        
        Args:
            instruction: 解析出的指令
            source: 信号来源
        """
        logger.info("\n" + "=" * 60)
        logger.info(f"📨 [新信号-{source}] {instruction}")
        logger.info(f"JSON: {instruction.to_json()}")
        logger.info("=" * 60)
        
        # 如果没有初始化交易组件，只记录信号
        if not self.broker or not self.position_manager:
            logger.warning("交易组件未初始化，仅记录信号")
            return
        
        # 检查是否是正股指令
        if instruction.option_type == 'STOCK':
            logger.info("正股交易信号，暂不支持自动交易")
            return
        
        try:
            # 根据指令类型执行不同操作
            if instruction.instruction_type == "OPEN":
                self._handle_open_position(instruction)
            
            elif instruction.instruction_type == "STOP_LOSS":
                self._handle_stop_loss(instruction)
            
            elif instruction.instruction_type == "TAKE_PROFIT":
                self._handle_take_profit(instruction)
            
            else:
                logger.warning(f"未知指令类型: {instruction.instruction_type}")
        
        except Exception as e:
            logger.error(f"❌ 处理指令失败: {e}", exc_info=True)
    
    def _handle_open_position(self, instruction: OptionInstruction):
        """
        处理开仓指令
        
        Args:
            instruction: 开仓指令
        """
        logger.info(f"🔵 处理开仓指令: {instruction.ticker} {instruction.option_type} {instruction.strike}")
        
        # 1. 转换期权代码（校验过期时间）
        try:
            symbol = convert_to_longport_symbol(
                ticker=instruction.ticker,
                option_type=instruction.option_type,
                strike=instruction.strike,
                expiry=instruction.expiry or "本周"
            )
            logger.info(f"期权代码: {symbol}")
        except ValueError as e:
            logger.error(f"❌ 期权代码转换失败: {e}")
            logger.warning(f"⚠️  跳过开仓指令 - {instruction.raw_message}")
            return
        
        # 2. 获取账户余额
        balance = self.broker.get_account_balance()
        available_cash = balance.get('available_cash', 10000)
        
        # 3. 计算购买数量
        quantity = calculate_quantity(
            price=instruction.price,
            available_cash=available_cash,
            position_size=instruction.position_size
        )
        logger.info(f"计划购买: {quantity} 张 @ ${instruction.price}")
        
        # 4. 提交订单
        order = self.broker.submit_option_order(
            symbol=symbol,
            side="BUY",
            quantity=quantity,
            price=instruction.price,
            order_type="LIMIT",
            remark=f"Auto open from signal: {instruction.raw_message}"
        )
        
        logger.info(f"✅ 开仓订单已提交: {order['order_id']}")
        
        # 5. 创建持仓记录
        position = create_position_from_order(
            symbol=symbol,
            ticker=instruction.ticker,
            option_type=instruction.option_type,
            strike=instruction.strike,
            expiry=instruction.expiry or "本周",
            quantity=quantity,
            avg_cost=instruction.price,
            order_id=order['order_id']
        )
        
        self.position_manager.add_position(position)
        logger.info(f"✅ 持仓已记录: {symbol}")
        
        # 6. 打印持仓摘要
        self.position_manager.print_summary()
    
    def _handle_stop_loss(self, instruction: OptionInstruction):
        """
        处理止损指令
        
        Args:
            instruction: 止损指令
        """
        logger.info(f"🔴 处理止损指令: 价格 ${instruction.price}")
        
        # 获取所有持仓，设置止损
        positions = self.position_manager.get_all_positions()
        
        if not positions:
            logger.warning("当前无持仓，忽略止损指令")
            return
        
        # 为最新持仓设置止损（可以改进为更智能的匹配）
        latest_position = positions[-1]
        
        if self.risk_controller:
            # 直接设置止损价格
            latest_position.set_stop_loss(instruction.price)
            self.position_manager.update_position(
                latest_position.symbol,
                stop_loss_price=instruction.price
            )
            logger.info(f"✅ 已为 {latest_position.symbol} 设置止损: ${instruction.price}")
        else:
            logger.warning("风险控制器未启用")
    
    def _handle_take_profit(self, instruction: OptionInstruction):
        """
        处理止盈指令
        
        Args:
            instruction: 止盈指令
        """
        logger.info(f"🟢 处理止盈指令: 价格 ${instruction.price}, 比例 {instruction.sell_ratio}")
        
        positions = self.position_manager.get_all_positions()
        
        if not positions:
            logger.warning("当前无持仓，忽略止盈指令")
            return
        
        latest_position = positions[-1]
        
        # 计算平仓数量
        sell_quantity = int(latest_position.quantity * instruction.sell_ratio)
        
        if sell_quantity <= 0:
            logger.warning(f"平仓数量为 0，忽略")
            return
        
        logger.info(f"准备平仓: {latest_position.symbol} x{sell_quantity}")
        
        # 提交卖出订单
        order = self.broker.submit_option_order(
            symbol=latest_position.symbol,
            side="SELL",
            quantity=sell_quantity,
            price=instruction.price,
            order_type="LIMIT",
            remark=f"Take profit: {instruction.sell_ratio*100:.0f}% @ ${instruction.price}"
        )
        
        logger.info(f"✅ 止盈订单已提交: {order['order_id']}")
        
        # 更新持仓数量
        new_quantity = latest_position.quantity - sell_quantity
        if new_quantity <= 0:
            self.position_manager.remove_position(latest_position.symbol)
            logger.info(f"✅ 持仓已清空: {latest_position.symbol}")
        else:
            self.position_manager.update_position(
                latest_position.symbol,
                quantity=new_quantity,
                available_quantity=new_quantity
            )
            logger.info(f"✅ 持仓已更新: {latest_position.symbol} 剩余 {new_quantity} 张")
    
    def _on_stop_loss_triggered(self, position, order, alert):
        """止损触发回调"""
        logger.warning(f"🛑 止损已触发并执行: {position.symbol}")
        logger.info(f"   订单 ID: {order['order_id']}")
        logger.info(f"   触发价: ${alert['trigger_price']:.2f}")
        logger.info(f"   当前价: ${alert['current_price']:.2f}")
        logger.info(f"   盈亏: ${alert['pnl']:,.2f} ({alert['pnl_pct']:+.2f}%)")
    
    def _on_take_profit_triggered(self, position, order, alert):
        """止盈触发回调"""
        logger.info(f"💰 止盈已触发并执行: {position.symbol}")
        logger.info(f"   订单 ID: {order['order_id']}")
        logger.info(f"   触发价: ${alert['trigger_price']:.2f}")
        logger.info(f"   当前价: ${alert['current_price']:.2f}")
        logger.info(f"   盈亏: ${alert['pnl']:,.2f} ({alert['pnl_pct']:+.2f}%)")
    
    def _on_risk_alert(self, alert_data):
        """风险警报回调"""
        logger.error(f"⚠️  风险警报: {alert_data}")
        # 这里可以添加通知逻辑（邮件、短信、Telegram等）
    
    async def run(self):
        """运行抓取器"""
        if not await self.setup():
            return
        
        print("\n" + "=" * 60)
        print("期权信号抓取器已启动")
        print(f"轮询间隔: {Config.POLL_INTERVAL} 秒")
        print(f"展示模式: {Config.DISPLAY_MODE}")
        print(f"输出文件: {Config.OUTPUT_FILE}")
        print("按 Ctrl+C 停止")
        print("=" * 60 + "\n")
        
        try:
            if self.multi_monitor:
                await self.multi_monitor.start()
            elif self.monitor:
                await self.monitor.start()
            else:
                print("错误: 没有可用的监控器")
        except KeyboardInterrupt:
            print("\n收到停止信号...")
        finally:
            await self.cleanup()
    
    async def cleanup(self):
        """清理资源"""
        logger.info("正在清理资源...")
        
        # 停止风险控制
        if self.auto_trailing:
            self.auto_trailing.stop()
            logger.info("自动移动止损已停止")
        
        if self.risk_controller:
            self.risk_controller.stop()
            logger.info("风险控制器已停止")
        
        # 保存持仓
        if self.position_manager:
            self.position_manager.print_summary()
            logger.info("持仓已保存")
        
        # 停止监控
        if self.multi_monitor:
            self.multi_monitor.stop()
            logger.info("多页面监控已停止")
        
        if self.monitor:
            self.monitor.stop()
            logger.info("页面监控已停止")
        
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
    
    # 检查是否有多个页面需要监控
    import os
    from dotenv import load_dotenv
    load_dotenv()
    
    option_pages = os.getenv("WHOP_OPTION_PAGES", "")
    stock_pages = os.getenv("WHOP_STOCK_PAGES", "")
    enable_stock = os.getenv("ENABLE_STOCK_MONITOR", "false").lower() == "true"
    
    # 判断是否使用多页面监控
    use_multi = (option_pages.count(',') > 0 or 
                 (option_pages and stock_pages and enable_stock))
    
    scraper = SignalScraper(use_multi_page=use_multi)
    
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


def test_parser():
    """测试解析器"""
    from parser.option_parser import OptionParser
    
    test_messages = [
        "INTC - $48 CALLS 本周 $1.2",
        "小仓位  止损 0.95",
        "1.75出三分之一",
        "止损提高到1.5",
        "1.65附近出剩下三分之二",
        "AAPL $150 PUTS 1/31 $2.5",
        "TSLA - 250 CALL $3.0 小仓位",
        "2.0 出一半",
        "止损调整到 1.8",
    ]
    
    print("=" * 60)
    print("期权指令解析测试")
    print("=" * 60)
    
    for msg in test_messages:
        print(f"\n原始消息: {msg}")
        instruction = OptionParser.parse(msg)
        if instruction:
            print(f"解析结果: {instruction}")
            print(f"JSON: {instruction.to_json()}")
        else:
            print("解析结果: 未能识别")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--test":
        # 运行解析器测试
        test_parser()
    else:
        # 运行主程序
        asyncio.run(main())
