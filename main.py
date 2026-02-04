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
from typing import Optional, Tuple

from config import Config
from scraper.browser import BrowserManager
from scraper.monitor import MessageMonitor, MutationObserverMonitor
from scraper.multi_monitor import MultiPageMonitor
from models.instruction import OptionInstruction

# 长桥交易模块
from broker import (
    load_longport_config,
    LongPortBroker,
    PositionManager,
    create_position_from_order,
    convert_to_longport_symbol,
    calculate_quantity,
    AutoTrader  # 新增：自动交易执行器
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
    
    def __init__(self, selected_page: Optional[Tuple[str, str, str]] = None, use_multi_page: bool = False):
        """
        初始化信号抓取器
        
        Args:
            selected_page: 本次要监控的单个页面 (url, type, name)，type 为 'option' 或 'stock'。若指定则仅监控该页。
            use_multi_page: 是否使用多页面监控（当未指定 selected_page 且配置了多页时使用）
        """
        self.browser: Optional[BrowserManager] = None
        self.monitor: Optional[MessageMonitor] = None
        self.multi_monitor: Optional[MultiPageMonitor] = None
        self.selected_page = selected_page
        self.use_multi_page = use_multi_page
        self._shutdown_event = asyncio.Event()
        
        # 交易组件
        self.broker: Optional[LongPortBroker] = None
        self.position_manager: Optional[PositionManager] = None
        self.risk_controller: Optional[RiskController] = None
        self.auto_trailing: Optional[AutoTrailingStopLoss] = None
        self.auto_trader: Optional[AutoTrader] = None  # 新增：自动交易执行器
        
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
            
            # 6. 创建自动交易执行器（新增）
            self.auto_trader = AutoTrader(broker=self.broker)
            logger.info("✅ 自动交易执行器初始化成功")
            
            # 启动风险控制（如果启用了自动交易）
            if self.broker.auto_trade:
                self.risk_controller.start()
                self.auto_trailing.start()
                logger.info("🚀 风险控制系统已启动")
                logger.info("🤖 自动交易执行器就绪")
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
        
        # 确定本次监控的页面：若指定了 selected_page 则仅监控该页，否则从配置取（可能多页）
        if self.selected_page:
            page_configs = [self.selected_page]
        else:
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
        设置单页面监控
        
        Args:
            page: 浏览器页面对象
            page_config: (url, page_type, name) 元组
        """
        url, page_type = page_config[0], page_config[1]
        
        # 导航到目标页面
        if not await self.browser.navigate(url):
            print(f"无法导航到目标页面: {url}")
            return False
        
        # 根据配置选择监控模式
        monitor_mode = Config.MONITOR_MODE.lower()
        
        if monitor_mode == 'event':
            # 使用事件驱动监控器
            print(f"使用事件驱动监控模式")
            self.monitor = MutationObserverMonitor(
                page=page,
                output_file=Config.OUTPUT_FILE,
                enable_sample_collection=Config.ENABLE_SAMPLE_COLLECTION,
                display_mode=Config.DISPLAY_MODE,
                check_interval=Config.CHECK_INTERVAL,
                status_report_interval=Config.STATUS_REPORT_INTERVAL
            )
        else:
            # 使用传统轮询监控器
            print(f"使用轮询监控模式")
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
            page_configs: [(url, page_type, name), ...] 列表
        """
        # 创建多页面监控器
        self.multi_monitor = MultiPageMonitor(
            poll_interval=Config.POLL_INTERVAL,
            output_file=Config.OUTPUT_FILE,
            enable_sample_collection=Config.ENABLE_SAMPLE_COLLECTION,
            display_mode=Config.DISPLAY_MODE
        )
        
        # 为每个页面创建浏览器上下文和页面
        for url, page_type, _ in page_configs:
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
        处理交易指令（使用新的AutoTrader）
        
        Args:
            instruction: 解析出的指令
            source: 信号来源
        """
        logger.info("\n" + "=" * 80)
        logger.info(f"📨 [新信号-{source}] {instruction}")
        logger.info(f"类型: {instruction.instruction_type}")
        logger.info(f"股票: {instruction.ticker}")
        if instruction.option_type:
            logger.info(f"期权: {instruction.option_type} ${instruction.strike} {instruction.expiry}")
        if instruction.price:
            logger.info(f"价格: ${instruction.price}")
        logger.info("=" * 80)
        
        # 如果没有初始化交易组件，只记录信号
        if not self.broker or not self.auto_trader:
            logger.warning("⚠️  交易组件未初始化，仅记录信号")
            return
        
        # 检查自动交易是否启用
        if not self.broker.auto_trade:
            logger.info("ℹ️  自动交易未启用，仅记录信号")
            return
        
        try:
            # 使用AutoTrader执行指令
            logger.info(f"🤖 使用AutoTrader执行指令...")
            result = self.auto_trader.execute_instruction(instruction)
            
            if result:
                logger.info(f"✅ 指令执行成功")
                logger.info(f"   订单ID: {result.get('order_id', 'N/A')}")
                logger.info(f"   状态: {result.get('status', 'N/A')}")
                
                # 如果是买入订单，同步持仓管理器
                if instruction.instruction_type == "BUY" and self.position_manager:
                    self._sync_position_after_buy(instruction, result)
            else:
                logger.warning(f"⚠️  指令执行跳过或失败")
        
        except Exception as e:
            logger.error(f"❌ 处理指令失败: {e}", exc_info=True)
    
    def _sync_position_after_buy(self, instruction: OptionInstruction, order_result: dict):
        """
        买入后同步持仓管理器
        
        Args:
            instruction: 买入指令
            order_result: 订单结果
        """
        try:
            if not self.position_manager:
                return
            
            # 生成期权代码
            symbol = self.auto_trader._generate_option_symbol(instruction)
            if not symbol:
                logger.warning("无法生成期权代码，跳过持仓同步")
                return
            
            # 创建持仓记录
            position = create_position_from_order(
                symbol=symbol,
                ticker=instruction.ticker,
                option_type=instruction.option_type,
                strike=instruction.strike,
                expiry=instruction.expiry,
                quantity=order_result.get('quantity', 0),
                avg_cost=order_result.get('price', instruction.price),
                order_id=order_result.get('order_id', '')
            )
            
            self.position_manager.add_position(position)
            logger.info(f"✅ 持仓已同步到管理器: {symbol}")
            
        except Exception as e:
            logger.error(f"持仓同步失败: {e}")
    
    # ========================================
    # 旧的处理方法（已由AutoTrader替代，保留供参考）
    # ========================================
    
    def _handle_open_position_legacy(self, instruction: OptionInstruction):
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
        
        # 3. 计算购买数量（由 MAX_OPTION_TOTAL_PRICE 与可用资金控制）
        quantity = calculate_quantity(
            price=instruction.price,
            available_cash=available_cash
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
    
    def _handle_stop_loss_legacy(self, instruction: OptionInstruction):
        """
        处理止损指令（旧版，已由AutoTrader替代）
        
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
    
    def _handle_take_profit_legacy(self, instruction: OptionInstruction):
        """
        处理止盈指令（旧版，已由AutoTrader替代）
        
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


async def test_whop_scraper():
    """测试 Whop 页面抓取功能"""
    print("\n" + "=" * 60)
    print("Whop 页面抓取测试")
    print("=" * 60 + "\n")
    
    # 验证配置
    if not Config.validate():
        print("❌ 配置验证失败")
        create_env_template()
        return
    
    print("✅ 配置验证通过\n")
    
    # 创建浏览器管理器
    browser = BrowserManager(
        headless=Config.HEADLESS,
        slow_mo=Config.SLOW_MO,
        storage_state_path=Config.STORAGE_STATE_PATH
    )
    
    try:
        # 启动浏览器
        print("🚀 正在启动浏览器...")
        page = await browser.start()
        print("✅ 浏览器已启动\n")
        
        # 获取所有需要监控的页面配置
        page_configs = Config.get_all_pages()
        
        if not page_configs:
            print("❌ 没有配置任何监控页面")
            return
        
        print(f"📋 发现 {len(page_configs)} 个监控页面:")
        for i, (url, page_type, name) in enumerate(page_configs, 1):
            desc = f"{name} - " if name else ""
            print(f"   {i}. [{page_type.upper()}] {desc}{url}")
        print()
        
        # 检查登录状态
        first_url = page_configs[0][0]
        print("🔐 正在检查登录状态...")
        if not await browser.is_logged_in(first_url):
            print("⚠️  需要登录...")
            success = await browser.login(
                Config.WHOP_EMAIL,
                Config.WHOP_PASSWORD,
                Config.LOGIN_URL
            )
            
            if not success:
                print("❌ 登录失败，请检查凭据是否正确")
                return
            print("✅ 登录成功\n")
        else:
            print("✅ 已登录\n")
        
        # 测试抓取第一个页面的消息
        test_url, test_type, _ = page_configs[0]
        print(f"📄 正在测试抓取页面: [{test_type.upper()}] {test_url}")
        
        # 导航到页面
        if not await browser.navigate(test_url):
            print(f"❌ 无法导航到页面: {test_url}")
            return
        
        print("✅ 页面导航成功\n")
        
        # 使用新的增强消息提取器（scraper层唯一输出格式）
        from scraper.message_extractor import EnhancedMessageExtractor
        from parser.option_parser import OptionParser
        
        extractor = EnhancedMessageExtractor(page)
        
        print("🔍 正在提取消息（使用新的DOM提取逻辑）...")
        raw_groups = await extractor.extract_message_groups()
        
        print(f"\n✅ 成功提取 {len(raw_groups)} 条原始消息\n")
        
        if raw_groups:
            # 解析为交易指令
            print("📊 正在解析交易指令...")
            instructions = []
            for group in raw_groups:
                simple_dict = group.to_simple_dict()
                content = simple_dict.get('content', '').strip()
                if content and len(content) > 5:
                    instruction = OptionParser.parse(content)
                    if instruction:
                        instructions.append(instruction)
            
            print(f"✅ 解析出 {len(instructions)} 条交易指令\n")
            
            # 显示原始消息（前10条）
            print("=" * 80)
            print("【原始消息示例】（前100条）")
            print("=" * 80)
            for i, group in enumerate(raw_groups[:100], 1):
                simple_dict = group.to_simple_dict()
                print(f"ID: {simple_dict['domID']}")
                print(f"内容: {simple_dict['content']}")
                print(f"时间: {simple_dict['timestamp']}")
                print(f"引用: {simple_dict['refer']}")
                print(f"位置: {simple_dict['position']}")
                print(f"历史: {simple_dict['history']}")
                print("-" * 40)
            
            if len(raw_groups) > 100:
                print(f"\n... 还有 {len(raw_groups) - 100} 条消息未显示")
            
            # 显示交易指令
            if instructions:
                print("\n" + "=" * 80)
                print("【解析出的交易指令】（前5条）")
                print("=" * 80)
                for i, instruction in enumerate(instructions[:5], 1):
                    print(f"\n{i}. {instruction}")
                    print(f"   类型: {instruction.instruction_type}")
                    print(f"   股票: {instruction.ticker}")
                    print(f"   价格: ${instruction.price}")
                    if instruction.instruction_type != "OPEN":
                        print(f"   比例: {instruction.sell_ratio*100:.0f}%")
                print()
                
                if len(instructions) > 5:
                    print(f"... 还有 {len(instructions) - 5} 条指令未显示")
            else:
                print("\nℹ️  未解析出任何交易指令")
            
            # 显示交易组表格
            if trade_groups:
                print("\n" + "=" * 120)
                print("【交易组摘要】")
                print("=" * 120)
                print(format_as_table(trade_groups))
        else:
            print("⚠️  未提取到任何消息")
        
        print("=" * 60)
        print("测试完成")
        print("=" * 60)
        
    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
    
    finally:
        # 关闭浏览器
        print("\n🧹 正在清理资源...")
        await browser.close()
        print("✅ 浏览器已关闭")


async def test_broker():
    """测试交易接口"""
    print("\n" + "=" * 60)
    print("交易接口测试")
    print("=" * 60 + "\n")
    
    try:
        # 加载配置
        print("📋 正在加载长桥配置...")
        config = load_longport_config()
        print("✅ 配置加载成功\n")
        
        # 创建交易接口
        print("🔌 正在连接长桥API...")
        broker = LongPortBroker(config)
        print("✅ 连接成功\n")
        
        # 获取账户余额
        print("💰 正在获取账户余额...")
        balance = broker.get_account_balance()
        print(f"✅ 账户余额:")
        print(f"   总资产: ${balance.get('total_assets', 0):,.2f}")
        print(f"   可用现金: ${balance.get('available_cash', 0):,.2f}")
        print(f"   持仓市值: ${balance.get('position_value', 0):,.2f}")
        print()
        
        # 测试报价（可选）
        print("📊 正在测试期权报价...")
        # 这里可以添加具体的报价测试
        print("⚠️  报价测试需要提供具体的期权代码\n")
        
        print("=" * 60)
        print("测试完成")
        print("=" * 60)
        
    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()


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
  
  # 导出页面DOM和截图（用于调试选择器）
  python3 test/test_export_page_dom.py
  
  # 测试 Whop 页面抓取（使用新的消息提取逻辑）
  python3 main.py --test whop-scraper
  
  # 测试交易接口
  python3 main.py --test broker
  
  # 测试配置文件
  python3 main.py --test config
  
  # 分析本地HTML文件
  python3 analyze_local_messages.py debug/page_xxx.html
        """
    )
    
    parser.add_argument(
        '--test',
        type=str,
        choices=['whop-scraper', 'broker', 'config'],
        help='运行测试模式，指定测试类型'
    )
    
    parser.add_argument(
        '--version',
        action='version',
        version='期权信号抓取器 v2.1'
    )
    
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_arguments()
    
    if args.test:
        # 测试模式
        if args.test == 'whop-scraper':
            asyncio.run(test_whop_scraper())
        elif args.test == 'broker':
            asyncio.run(test_broker())
        elif args.test == 'config':
            test_config()
    else:
        # 正常运行模式
        asyncio.run(main())
