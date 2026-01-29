#!/usr/bin/env python3
"""
期权信号抓取器 - 主程序入口
实时监控 Whop 页面，解析期权交易信号
"""
import asyncio
import signal
import sys
from typing import Optional

from config import Config, create_env_template
from scraper.browser import BrowserManager
from scraper.monitor import MessageMonitor
from models.instruction import OptionInstruction


class SignalScraper:
    """期权信号抓取器"""
    
    def __init__(self):
        self.browser: Optional[BrowserManager] = None
        self.monitor: Optional[MessageMonitor] = None
        self._shutdown_event = asyncio.Event()
    
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
        
        # 检查是否需要登录
        print("正在检查登录状态...")
        if not await self.browser.is_logged_in(Config.TARGET_URL):
            print("需要登录...")
            success = await self.browser.login(
                Config.WHOP_EMAIL,
                Config.WHOP_PASSWORD,
                Config.LOGIN_URL
            )
            
            if not success:
                print("登录失败，请检查凭据是否正确")
                return False
        
        # 导航到目标页面
        if not await self.browser.navigate(Config.TARGET_URL):
            print("无法导航到目标页面")
            return False
        
        # 创建监控器
        self.monitor = MessageMonitor(
            page=page,
            poll_interval=Config.POLL_INTERVAL,
            output_file=Config.OUTPUT_FILE
        )
        
        # 设置回调
        self.monitor.on_new_instruction(self._on_instruction)
        
        return True
    
    def _on_instruction(self, instruction: OptionInstruction):
        """
        新指令回调
        
        Args:
            instruction: 解析出的指令
        """
        print("\n" + "=" * 60)
        print(f"[新信号] {instruction}")
        print(f"JSON: {instruction.to_json()}")
        print("=" * 60 + "\n")
        
        # TODO: 这里可以添加调用券商 API 的逻辑
        # 例如:
        # if instruction.instruction_type == "OPEN":
        #     broker_api.open_position(instruction)
        # elif instruction.instruction_type == "STOP_LOSS":
        #     broker_api.set_stop_loss(instruction.price)
        # ...
    
    async def run(self):
        """运行抓取器"""
        if not await self.setup():
            return
        
        print("\n" + "=" * 60)
        print("期权信号抓取器已启动")
        print(f"目标页面: {Config.TARGET_URL}")
        print(f"轮询间隔: {Config.POLL_INTERVAL} 秒")
        print(f"输出文件: {Config.OUTPUT_FILE}")
        print("按 Ctrl+C 停止")
        print("=" * 60 + "\n")
        
        try:
            await self.monitor.start()
        except KeyboardInterrupt:
            print("\n收到停止信号...")
        finally:
            await self.cleanup()
    
    async def cleanup(self):
        """清理资源"""
        if self.monitor:
            self.monitor.stop()
        
        if self.browser:
            await self.browser.close()
        
        print("程序已退出")


async def main():
    """主函数"""
    print("""
╔══════════════════════════════════════════════════════════╗
║           期权信号抓取器 v1.0                            ║
║           Option Signal Scraper                          ║
╚══════════════════════════════════════════════════════════╝
    """)
    
    scraper = SignalScraper()
    
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
