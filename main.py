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
        设置单页面监控
        
        Args:
            page: 浏览器页面对象
            page_config: (url, page_type) 元组
        """
        url, page_type = page_config
        
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


async def analyze_local_html():
    """分析本地HTML文件（不需要启动浏览器）"""
    print("\n" + "=" * 60)
    print("本地HTML分析工具")
    print("=" * 60 + "\n")
    
    import os
    from glob import glob
    
    # 查找debug目录下的HTML文件
    html_files = glob("debug/page_*.html")
    
    if not html_files:
        print("❌ 未找到HTML文件")
        print("\n💡 提示: 请先运行以下命令导出HTML:")
        print("   python3 main.py --test export-dom\n")
        return
    
    # 按修改时间排序，最新的在前
    html_files.sort(key=lambda x: os.path.getmtime(x), reverse=True)
    
    print(f"📁 找到 {len(html_files)} 个HTML文件:\n")
    for i, file in enumerate(html_files[:5], 1):
        mtime = os.path.getmtime(file)
        from datetime import datetime
        time_str = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M:%S")
        size_mb = os.path.getsize(file) / 1024 / 1024
        print(f"   {i}. {os.path.basename(file)}")
        print(f"      时间: {time_str}, 大小: {size_mb:.2f} MB")
    
    if len(html_files) > 5:
        print(f"\n   ... 还有 {len(html_files) - 5} 个文件")
    
    # 选择文件
    print("\n请选择要分析的文件 (输入序号，默认=1，最新的文件): ", end='')
    choice = input().strip()
    
    if not choice:
        choice = "1"
    
    try:
        index = int(choice) - 1
        if index < 0 or index >= len(html_files):
            print("❌ 无效的选择")
            return
    except ValueError:
        print("❌ 无效的输入")
        return
    
    html_file = html_files[index]
    print(f"\n✅ 已选择: {html_file}\n")
    
    # 读取HTML文件
    print("📖 正在读取HTML文件...")
    with open(html_file, 'r', encoding='utf-8') as f:
        html_content = f.read()
    
    print(f"✅ 已读取 {len(html_content)} 字符\n")
    
    # 使用playwright分析HTML
    print("🔍 正在分析HTML结构...\n")
    
    from playwright.async_api import async_playwright
    
    async with async_playwright() as p:
        # 启动浏览器
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        
        # 加载HTML内容
        await page.set_content(html_content)
        
        # 分析页面结构
        js_analysis = """
        () => {
            const analysis = {
                url: 'local-file',
                all_elements_count: document.querySelectorAll('*').length,
                potential_message_containers: [],
                text_elements: []
            };
            
            // 尝试多种可能的选择器
            const selectors = [
                '[data-message-id]',
                '[class*="message"]',
                '[class*="Message"]',
                '[class*="post"]',
                '[class*="Post"]',
                '[role="article"]',
                'article'
            ];
            
            for (const selector of selectors) {
                const elements = document.querySelectorAll(selector);
                if (elements.length > 0) {
                    const sample = elements[0];
                    analysis.potential_message_containers.push({
                        selector: selector,
                        count: elements.length,
                        sample_classes: sample.className,
                        sample_id: sample.id,
                        sample_text: sample.innerText.substring(0, 200),
                        sample_html: sample.outerHTML.substring(0, 500)
                    });
                }
            }
            
            // 查找包含特定关键字的元素
            const keywords = ['GILD', 'NVDA', 'CALL', 'PUT', '止损', '出'];
            const walker = document.createTreeWalker(
                document.body,
                NodeFilter.SHOW_TEXT,
                null,
                false
            );
            
            let node;
            const seenTexts = new Set();
            while (node = walker.nextNode()) {
                const text = node.textContent.trim();
                if (text.length > 10 && !seenTexts.has(text)) {
                    for (const keyword of keywords) {
                        if (text.includes(keyword)) {
                            let element = node.parentElement;
                            let depth = 0;
                            const path = [];
                            
                            while (element && depth < 5) {
                                path.push({
                                    tag: element.tagName,
                                    class: element.className,
                                    id: element.id
                                });
                                element = element.parentElement;
                                depth++;
                            }
                            
                            analysis.text_elements.push({
                                text: text.substring(0, 100),
                                keyword: keyword,
                                path: path
                            });
                            seenTexts.add(text);
                            break;
                        }
                    }
                    
                    if (analysis.text_elements.length >= 30) break;
                }
            }
            
            return analysis;
        }
        """
        
        analysis_data = await page.evaluate(js_analysis)
        
        # 生成分析报告
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        analysis_file = f"debug/local_analysis_{timestamp}.txt"
        
        with open(analysis_file, 'w', encoding='utf-8') as f:
            f.write("=" * 60 + "\n")
            f.write("本地HTML结构分析\n")
            f.write("=" * 60 + "\n\n")
            f.write(f"源文件: {html_file}\n")
            f.write(f"总元素数: {analysis_data['all_elements_count']}\n\n")
            
            f.write("=" * 60 + "\n")
            f.write("可能的消息容器选择器\n")
            f.write("=" * 60 + "\n\n")
            
            for i, container in enumerate(analysis_data['potential_message_containers'], 1):
                f.write(f"{i}. 选择器: {container['selector']}\n")
                f.write(f"   数量: {container['count']}\n")
                f.write(f"   类名: {container['sample_classes']}\n")
                f.write(f"   ID: {container['sample_id']}\n")
                f.write(f"\n   示例文本:\n   {container['sample_text']}\n")
                f.write(f"\n   示例HTML:\n   {container['sample_html']}\n")
                f.write("\n" + "-" * 60 + "\n\n")
            
            f.write("\n" + "=" * 60 + "\n")
            f.write("包含交易关键字的元素\n")
            f.write("=" * 60 + "\n\n")
            
            for i, elem in enumerate(analysis_data['text_elements'], 1):
                f.write(f"{i}. 关键字: {elem['keyword']}\n")
                f.write(f"   文本: {elem['text']}\n")
                f.write(f"   路径:\n")
                for j, node in enumerate(elem['path']):
                    indent = "   " * (j + 2)
                    f.write(f"{indent}<{node['tag']} class='{node['class']}' id='{node['id']}'>\n")
                f.write("\n")
        
        # 关闭浏览器
        await browser.close()
        
        print(f"✅ 分析完成\n")
        print("=" * 60)
        print("分析结果")
        print("=" * 60)
        print(f"\n📊 统计信息:")
        print(f"   总元素数: {analysis_data['all_elements_count']}")
        print(f"   找到 {len(analysis_data['potential_message_containers'])} 种可能的消息容器")
        print(f"   找到 {len(analysis_data['text_elements'])} 个包含交易关键字的元素")
        
        print(f"\n📄 详细分析报告已保存到:")
        print(f"   {analysis_file}")
        
        print("\n💡 下一步:")
        print("   1. 查看分析报告了解页面结构")
        print("   2. 根据报告调整 scraper/message_extractor.py 中的选择器")
        print("   3. 运行 python3 main.py --test message-extractor 验证")
        print("=" * 60 + "\n")


async def export_page_dom():
    """导出页面DOM和截图供本地分析"""
    print("\n" + "=" * 60)
    print("导出页面DOM和截图")
    print("=" * 60 + "\n")
    
    # 验证配置
    if not Config.validate():
        print("❌ 配置验证失败")
        create_env_template()
        return
    
    print("✅ 配置验证通过\n")
    
    # 创建输出目录
    output_dir = "debug"
    os.makedirs(output_dir, exist_ok=True)
    
    # 创建浏览器管理器
    browser = BrowserManager(
        headless=False,  # 使用非无头模式便于查看
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
        
        # 导航到页面
        test_url, test_type = page_configs[0]
        print(f"📄 正在访问页面: [{test_type.upper()}] {test_url}")
        
        if not await browser.navigate(test_url):
            print(f"❌ 无法导航到页面: {test_url}")
            return
        
        print("✅ 页面导航成功\n")
        
        # 等待页面初始加载
        import asyncio
        print("⏳ 等待页面初始加载...")
        await asyncio.sleep(3)
        
        # 等待用户确认
        print("\n" + "=" * 60)
        print("⚠️  重要提示")
        print("=" * 60)
        print("\n浏览器窗口已打开，请在浏览器中执行以下操作：")
        print("\n1. 📜 滚动页面到最底部，加载所有历史消息")
        print("2. ⏳ 等待所有消息完全加载")
        print("3. ✅ 确认页面内容完整")
        print("\n完成后按 [回车] 键继续导出...\n")
        
        # 等待用户输入
        input()
        
        print("\n✅ 收到确认，开始导出...\n")
        
        # 生成时间戳
        from datetime import datetime
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # 1. 导出完整HTML
        html_file = f"{output_dir}/page_{timestamp}.html"
        print(f"📝 正在导出HTML到: {html_file}")
        html_content = await page.content()
        with open(html_file, 'w', encoding='utf-8') as f:
            f.write(html_content)
        print(f"✅ HTML已保存 ({len(html_content)} 字符)\n")
        
        # 2. 截图
        screenshot_file = f"{output_dir}/page_{timestamp}.png"
        print(f"📸 正在截图到: {screenshot_file}")
        await page.screenshot(path=screenshot_file, full_page=True)
        print(f"✅ 截图已保存\n")
        
        # 3. 导出消息结构分析
        analysis_file = f"{output_dir}/analysis_{timestamp}.txt"
        print(f"🔍 正在分析页面结构...")
        
        # 使用JavaScript分析页面结构
        js_analysis = """
        () => {
            const analysis = {
                url: window.location.href,
                title: document.title,
                all_elements_count: document.querySelectorAll('*').length,
                
                // 查找可能的消息容器
                potential_message_containers: [],
                
                // 查找可能的文本内容
                text_elements: []
            };
            
            // 尝试多种可能的选择器
            const selectors = [
                '[class*="message"]',
                '[class*="Message"]',
                '[class*="post"]',
                '[class*="Post"]',
                '[class*="content"]',
                '[class*="Content"]',
                '[role="article"]',
                'article',
                '[data-message]',
                '[data-post]'
            ];
            
            for (const selector of selectors) {
                const elements = document.querySelectorAll(selector);
                if (elements.length > 0) {
                    const sample = elements[0];
                    analysis.potential_message_containers.push({
                        selector: selector,
                        count: elements.length,
                        sample_classes: sample.className,
                        sample_id: sample.id,
                        sample_attributes: Array.from(sample.attributes).map(a => `${a.name}="${a.value.substring(0, 50)}"`),
                        sample_text: sample.innerText.substring(0, 200),
                        sample_html: sample.outerHTML.substring(0, 500)
                    });
                }
            }
            
            // 查找包含特定关键字的元素
            const keywords = ['GILD', 'CALL', 'PUT', '止损', '出'];
            const walker = document.createTreeWalker(
                document.body,
                NodeFilter.SHOW_TEXT,
                null,
                false
            );
            
            let node;
            while (node = walker.nextNode()) {
                const text = node.textContent.trim();
                if (text.length > 10) {
                    for (const keyword of keywords) {
                        if (text.includes(keyword)) {
                            let element = node.parentElement;
                            let depth = 0;
                            const path = [];
                            
                            while (element && depth < 5) {
                                path.push({
                                    tag: element.tagName,
                                    class: element.className,
                                    id: element.id
                                });
                                element = element.parentElement;
                                depth++;
                            }
                            
                            analysis.text_elements.push({
                                text: text.substring(0, 100),
                                keyword: keyword,
                                path: path
                            });
                            break;
                        }
                    }
                }
            }
            
            return analysis;
        }
        """
        
        analysis_data = await page.evaluate(js_analysis)
        
        with open(analysis_file, 'w', encoding='utf-8') as f:
            import json
            f.write("=" * 60 + "\n")
            f.write("页面结构分析\n")
            f.write("=" * 60 + "\n\n")
            f.write(f"URL: {analysis_data['url']}\n")
            f.write(f"标题: {analysis_data['title']}\n")
            f.write(f"总元素数: {analysis_data['all_elements_count']}\n\n")
            
            f.write("=" * 60 + "\n")
            f.write("可能的消息容器选择器\n")
            f.write("=" * 60 + "\n\n")
            
            for i, container in enumerate(analysis_data['potential_message_containers'], 1):
                f.write(f"{i}. 选择器: {container['selector']}\n")
                f.write(f"   数量: {container['count']}\n")
                f.write(f"   类名: {container['sample_classes']}\n")
                f.write(f"   ID: {container['sample_id']}\n")
                f.write(f"   属性:\n")
                for attr in container['sample_attributes']:
                    f.write(f"      {attr}\n")
                f.write(f"\n   示例文本:\n   {container['sample_text']}\n")
                f.write(f"\n   示例HTML:\n   {container['sample_html']}\n")
                f.write("\n" + "-" * 60 + "\n\n")
            
            f.write("\n" + "=" * 60 + "\n")
            f.write("包含交易关键字的元素\n")
            f.write("=" * 60 + "\n\n")
            
            for i, elem in enumerate(analysis_data['text_elements'][:20], 1):
                f.write(f"{i}. 关键字: {elem['keyword']}\n")
                f.write(f"   文本: {elem['text']}\n")
                f.write(f"   路径:\n")
                for j, node in enumerate(elem['path']):
                    indent = "   " * (j + 2)
                    f.write(f"{indent}<{node['tag']} class='{node['class']}' id='{node['id']}'>\n")
                f.write("\n")
        
        print(f"✅ 分析已保存\n")
        
        print("\n" + "=" * 60)
        print("导出完成！")
        print("=" * 60)
        print(f"\n📁 输出文件:")
        print(f"   1. HTML: {html_file}")
        print(f"   2. 截图: {screenshot_file}")
        print(f"   3. 分析: {analysis_file}")
        print(f"\n💡 下一步:")
        print(f"   1. 打开 {html_file} 查看页面结构")
        print(f"   2. 查看 {screenshot_file} 对照实际显示")
        print(f"   3. 阅读 {analysis_file} 了解可用的选择器")
        print(f"   4. 根据分析结果调整 message_extractor.py 中的选择器")
        print("=" * 60 + "\n")
        
    except Exception as e:
        print(f"\n❌ 导出失败: {e}")
        import traceback
        traceback.print_exc()
    
    finally:
        # 关闭浏览器
        print("\n🧹 正在清理资源...")
        await browser.close()
        print("✅ 浏览器已关闭")


async def test_message_extractor():
    """测试增强的消息提取器"""
    print("\n" + "=" * 60)
    print("消息提取器测试")
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
        test_url, test_type = page_configs[0]
        print(f"📄 正在测试抓取页面: [{test_type.upper()}] {test_url}")
        
        # 导航到页面
        if not await browser.navigate(test_url):
            print(f"❌ 无法导航到页面: {test_url}")
            return
        
        print("✅ 页面导航成功\n")
        
        # 使用增强的消息提取器
        from scraper.message_extractor import EnhancedMessageExtractor
        from scraper.message_grouper import MessageGrouper, format_as_table, format_as_detailed_table
        
        extractor = EnhancedMessageExtractor(page)
        
        print("🔍 正在提取消息...")
        raw_groups = await extractor.extract_message_groups()
        
        print(f"\n✅ 成功提取 {len(raw_groups)} 条消息\n")
        
        if raw_groups:
            # 将MessageGroup对象转换为字典格式
            messages = []
            for group in raw_groups:
                message_dict = {
                    'id': group.group_id,
                    'author': group.author,
                    'timestamp': group.timestamp,
                    'content': group.get_full_content(),
                    'primary_message': group.primary_message,
                    'related_messages': group.related_messages,
                    'quoted_message': group.quoted_message,
                    'quoted_context': group.quoted_context
                }
                messages.append(message_dict)
            
            # 使用消息分组器进行交易组聚合
            print("🔄 正在分析消息关联关系...")
            grouper = MessageGrouper()
            trade_groups = grouper.group_messages(messages)
            
            print(f"✅ 识别出 {len(trade_groups)} 个交易组\n")
            
            # 显示表格格式
            print("\n" + "=" * 155)
            print("【方式1】详细表格视图")
            print("=" * 155)
            print(format_as_detailed_table(trade_groups))
            
            print("\n" + "=" * 120)
            print("【方式2】分组摘要视图")
            print("=" * 120)
            print(format_as_table(trade_groups))
            
            # 显示原始消息（前5条）
            print("\n" + "=" * 60)
            print("【原始消息示例】（前5条）")
            print("=" * 60)
            for i, group in enumerate(raw_groups[:5], 1):
                print(f"\n{i}. 消息 ID: {group.group_id}")
                print(f"   作者: {group.author or '(未识别)'}")
                print(f"   时间: {group.timestamp or '(继承自上一条)'}")
                print(f"   内容: {group.primary_message[:80] if group.primary_message else '(空)'}...")
                if group.quoted_context:
                    print(f"   引用: {group.quoted_context[:60]}...")
                print("-" * 60)
            
            if len(raw_groups) > 5:
                print(f"\n... 还有 {len(raw_groups) - 5} 条消息未显示")
        else:
            print("⚠️  未提取到任何消息")
        
        print("\n" + "=" * 60)
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
        for i, (url, page_type) in enumerate(page_configs, 1):
            print(f"   {i}. [{page_type.upper()}] {url}")
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
        test_url, test_type = page_configs[0]
        print(f"📄 正在测试抓取页面: [{test_type.upper()}] {test_url}")
        
        # 导航到页面
        if not await browser.navigate(test_url):
            print(f"❌ 无法导航到页面: {test_url}")
            return
        
        print("✅ 页面导航成功\n")
        
        # 创建监控器（不启动持续监控，只抓取一次）
        import tempfile
        temp_output = tempfile.mktemp(suffix='.json')
        
        monitor = MessageMonitor(
            page=page,
            poll_interval=Config.POLL_INTERVAL,
            output_file=temp_output,  # 使用临时文件
            enable_sample_collection=False,
            display_mode="raw"  # 只显示原始消息
        )
        
        print("🔍 正在抓取消息...")
        instructions = await monitor.scan_once()
        
        # 提取原始消息
        messages_found = len(monitor._processed_ids)
        
        print(f"\n✅ 扫描完成")
        print(f"   发现消息: {messages_found} 条")
        print(f"   解析指令: {len(instructions)} 条\n")
        
        if instructions:
            print("📨 解析出的交易指令:")
            print("-" * 60)
            for i, instruction in enumerate(instructions[:5], 1):
                print(f"{i}. {instruction}")
                print(f"   类型: {instruction.instruction_type}")
                print(f"   原始消息: {instruction.raw_message[:80]}...")
                print()
        else:
            print("ℹ️  未解析出任何交易指令")
            
        # 清理临时文件
        import os
        try:
            os.remove(temp_output)
        except:
            pass
        
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
    
    print("\n" + "=" * 60)
    print("期权指令解析测试")
    print("=" * 60 + "\n")
    
    for msg in test_messages:
        print(f"原始消息: {msg}")
        instruction = OptionParser.parse(msg)
        if instruction:
            print(f"解析结果: {instruction}")
            print(f"JSON: {instruction.to_json()}")
        else:
            print("解析结果: 未能识别")
        print()


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


def test_config():
    """测试配置文件"""
    print("\n" + "=" * 60)
    print("配置文件测试")
    print("=" * 60 + "\n")
    
    # 检查配置文件是否存在
    env_file = ".env"
    if not os.path.exists(env_file):
        print(f"❌ 配置文件不存在: {env_file}")
        print("正在创建模板...")
        create_env_template()
        return
    
    print(f"✅ 配置文件存在: {env_file}\n")
    
    # 验证配置
    print("🔍 正在验证配置项...")
    is_valid = Config.validate()
    
    if is_valid:
        print("✅ 所有配置项验证通过\n")
        
        # 显示主要配置
        print("📋 当前配置:")
        print(f"   Headless: {Config.HEADLESS}")
        print(f"   轮询间隔: {Config.POLL_INTERVAL}秒")
        print(f"   日志级别: {Config.LOG_LEVEL}")
        print(f"   输出文件: {Config.OUTPUT_FILE}")
        print(f"   显示模式: {Config.DISPLAY_MODE}")
        
        # 显示监控页面
        page_configs = Config.get_all_pages()
        print(f"\n📄 监控页面 ({len(page_configs)} 个):")
        for i, (url, page_type) in enumerate(page_configs, 1):
            print(f"   {i}. [{page_type.upper()}] {url[:50]}...")
        
    else:
        print("❌ 配置验证失败，请检查配置项")
    
    print("\n" + "=" * 60)
    print("测试完成")
    print("=" * 60)


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
  
  # 测试解析器
  python3 main.py --test parser
  
  # 导出页面DOM和截图（用于调试选择器）
  python3 main.py --test export-dom
  
  # 分析本地HTML文件（不需要启动浏览器）
  python3 main.py --test analyze-html
  
  # 测试消息提取器（查看消息关联和引用）
  python3 main.py --test message-extractor
  
  # 测试 Whop 页面抓取
  python3 main.py --test whop-scraper
  
  # 测试交易接口
  python3 main.py --test broker
  
  # 测试配置文件
  python3 main.py --test config
        """
    )
    
    parser.add_argument(
        '--test',
        type=str,
        choices=['parser', 'export-dom', 'analyze-html', 'message-extractor', 'whop-scraper', 'broker', 'config'],
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
        if args.test == 'parser':
            test_parser()
        elif args.test == 'export-dom':
            asyncio.run(export_page_dom())
        elif args.test == 'analyze-html':
            asyncio.run(analyze_local_html())
        elif args.test == 'message-extractor':
            asyncio.run(test_message_extractor())
        elif args.test == 'whop-scraper':
            asyncio.run(test_whop_scraper())
        elif args.test == 'broker':
            asyncio.run(test_broker())
        elif args.test == 'config':
            test_config()
    else:
        # 正常运行模式
        asyncio.run(main())
