"""
Whop 登录助手脚本
用于手动登录 Whop 并保存 cookie 以供后续使用
"""
import asyncio
import sys
import os
from pathlib import Path
from playwright.async_api import async_playwright


class WhopLoginHelper:
    """Whop 登录助手"""
    
    def __init__(
        self,
        whop_url: str = "https://whop.com/login/",
        storage_file: str = ".auth/whop_state.json"
    ):
        """
        初始化登录助手
        
        Args:
            whop_url: Whop 登录页面 URL
            storage_file: Cookie 存储文件路径
        """
        self.whop_url = whop_url
        self.storage_file = storage_file
        
    async def manual_login(self):
        """
        打开浏览器，等待用户手动登录，然后保存 cookie
        """
        print("=" * 60)
        print("Whop 登录助手")
        print("=" * 60)
        print(f"即将打开浏览器访问: {self.whop_url}")
        print("请在浏览器中手动完成登录操作...")
        print("登录完成后，请返回终端并按回车键继续")
        print("=" * 60)
        
        async with async_playwright() as p:
            # 启动浏览器（非无头模式，方便用户操作）
            browser = await p.chromium.launch(
                headless=False,
                args=[
                    '--disable-blink-features=AutomationControlled',
                    '--window-size=1920,1080',
                ]
            )
            
            # 创建浏览器上下文
            context = await browser.new_context(
                viewport={'width': 1920, 'height': 1080},
                user_agent=(
                    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                    'AppleWebKit/537.36 (KHTML, like Gecko) '
                    'Chrome/120.0.0.0 Safari/537.36'
                )
            )
            
            # 创建新页面
            page = await context.new_page()
            
            # 访问 Whop 登录页面
            print(f"\n正在访问 {self.whop_url}...")
            try:
                await page.goto(
                    self.whop_url,
                    wait_until='domcontentloaded',
                    timeout=60000
                )
            except Exception as e:
                print(f"⚠️  页面加载警告: {e}")
                print("尝试继续...")
            
            print("\n✅ 浏览器已打开")
            print("📝 请在浏览器中完成以下操作：")
            print("   1. 输入您的邮箱和密码")
            print("   2. 点击登录按钮")
            print("   3. 等待登录成功并跳转到主页")
            print("   4. 确认您已经成功登录后")
            print("\n👇 然后返回终端按回车键继续...")
            
            # 等待用户按回车
            await asyncio.get_event_loop().run_in_executor(None, input)
            
            # 保存登录状态
            print("\n正在保存登录状态...")
            
            # 确保目录存在
            storage_path = Path(self.storage_file)
            storage_path.parent.mkdir(parents=True, exist_ok=True)
            
            await context.storage_state(path=self.storage_file)
            
            print(f"✅ 登录状态已保存到: {self.storage_file}")
            print("\n📊 已保存的信息包括:")
            print("   - Cookies")
            print("   - LocalStorage")
            print("   - SessionStorage")
            
            # 显示当前 URL
            current_url = page.url
            print(f"\n当前页面 URL: {current_url}")
            
            # 关闭浏览器
            print("\n正在关闭浏览器...")
            await context.close()
            await browser.close()
            
            print("\n" + "=" * 60)
            print("✅ 完成！")
            print("=" * 60)
            print(f"Cookie 已保存，下次运行时将自动使用 {self.storage_file}")
            print("您可以运行 main.py 开始自动监控和抓取")
            print("=" * 60)
    
    async def test_login_state(self, test_url: str = None):
        """
        测试保存的登录状态是否有效
        
        Args:
            test_url: 要测试的 URL，默认使用 whop_url
        """
        if test_url is None:
            test_url = self.whop_url
            
        print("=" * 60)
        print("测试登录状态")
        print("=" * 60)
        print(f"使用 cookie 文件: {self.storage_file}")
        print(f"测试 URL: {test_url}")
        print("=" * 60)
        
        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(
                    headless=False,
                    args=['--disable-blink-features=AutomationControlled']
                )
                
                # 使用保存的登录状态创建上下文
                context = await browser.new_context(
                    storage_state=self.storage_file,
                    viewport={'width': 1920, 'height': 1080},
                    user_agent=(
                        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                        'AppleWebKit/537.36 (KHTML, like Gecko) '
                        'Chrome/120.0.0.0 Safari/537.36'
                    )
                )
                
                page = await context.new_page()
                
                print("\n正在访问测试页面...")
                try:
                    await page.goto(
                        test_url,
                        wait_until='domcontentloaded',
                        timeout=60000
                    )
                except Exception as e:
                    print(f"⚠️  页面加载警告: {e}")
                
                await asyncio.sleep(3)
                
                current_url = page.url
                print(f"当前 URL: {current_url}")
                
                # 检查是否被重定向到登录页面
                if 'login' in current_url.lower():
                    print("\n❌ 登录状态已失效，请重新登录")
                    print("   运行: python3 whop_login.py")
                else:
                    print("\n✅ 登录状态有效！")
                    print("   您可以使用 main.py 开始监控")
                
                print("\n浏览器将在 5 秒后关闭...")
                await asyncio.sleep(5)
                
                await context.close()
                await browser.close()
                
        except FileNotFoundError:
            print(f"\n❌ 找不到 cookie 文件: {self.storage_file}")
            print("   请先运行登录命令: python3 whop_login.py")
        except Exception as e:
            print(f"\n❌ 测试失败: {e}")


async def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(
        description='Whop 登录助手 - 保存和测试登录状态',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用示例:
  
  首次登录（保存 cookie）:
    python3 whop_login.py
  
  测试登录状态是否有效:
    python3 whop_login.py --test
  
  指定自定义 URL:
    python3 whop_login.py --url https://whop.com/your-custom-url/
  
  指定自定义 cookie 文件:
    python3 whop_login.py --storage my_cookies.json
        """
    )
    
    parser.add_argument(
        '--test',
        action='store_true',
        help='测试保存的登录状态是否有效'
    )
    
    parser.add_argument(
        '--url',
        type=str,
        default='https://whop.com/login/',
        help='Whop URL（默认: https://whop.com/login/）'
    )
    
    parser.add_argument(
        '--storage',
        type=str,
        default='.auth/whop_state.json',
        help='Cookie 存储文件路径（默认: .auth/whop_state.json）'
    )
    
    parser.add_argument(
        '--test-url',
        type=str,
        help='用于测试的 URL（默认使用 --url 的值）'
    )
    
    args = parser.parse_args()
    
    helper = WhopLoginHelper(
        whop_url=args.url,
        storage_file=args.storage
    )
    
    if args.test:
        # 测试模式
        test_url = args.test_url if args.test_url else args.url
        await helper.test_login_state(test_url)
    else:
        # 登录模式
        await helper.manual_login()


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\n操作已取消")
        sys.exit(0)
