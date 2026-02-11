#!/usr/bin/env python3
"""
使用系统 Chrome 浏览器配置文件
保持 Google 账号登录状态，访问 Whop
"""
import asyncio
import os
import sys
from pathlib import Path
from playwright.async_api import async_playwright

from config import Config


class ChromeProfileManager:
    """Chrome 配置文件管理器"""
    
    @staticmethod
    def get_default_chrome_profile_path():
        """获取默认 Chrome 用户数据目录"""
        if sys.platform == 'darwin':  # macOS
            return os.path.expanduser('~/Library/Application Support/Google/Chrome')
        elif sys.platform == 'win32':  # Windows
            return os.path.expanduser('~/AppData/Local/Google/Chrome/User Data')
        else:  # Linux
            return os.path.expanduser('~/.config/google-chrome')
    
    @staticmethod
    def list_chrome_profiles():
        """列出所有 Chrome 配置文件"""
        base_path = ChromeProfileManager.get_default_chrome_profile_path()
        
        if not os.path.exists(base_path):
            return []
        
        profiles = []
        
        # 默认配置文件
        default_profile = os.path.join(base_path, 'Default')
        if os.path.exists(default_profile):
            profiles.append({
                'name': 'Default',
                'path': default_profile,
                'display': '默认配置文件'
            })
        
        # 其他配置文件 (Profile 1, Profile 2, etc.)
        for item in os.listdir(base_path):
            if item.startswith('Profile '):
                profile_path = os.path.join(base_path, item)
                if os.path.isdir(profile_path):
                    profiles.append({
                        'name': item,
                        'path': profile_path,
                        'display': f'配置文件 {item.split()[-1]}'
                    })
        
        return profiles


async def test_with_chrome_profile(profile_path: str = None):
    """使用 Chrome 配置文件测试 Whop 访问"""
    print("\n" + "=" * 70)
    print("🌐 使用 Chrome 配置文件访问 Whop")
    print("=" * 70 + "\n")
    
    # 如果没有指定配置文件，使用默认的
    if not profile_path:
        profile_path = os.path.join(
            ChromeProfileManager.get_default_chrome_profile_path(),
            'Default'
        )
    
    print(f"📁 使用配置文件: {profile_path}")
    
    if not os.path.exists(profile_path):
        print(f"❌ 配置文件不存在: {profile_path}")
        return False
    
    playwright = None
    browser = None
    
    try:
        print("\n⏳ 正在启动 Chrome...")
        print("ℹ️  使用你的 Chrome 配置文件（包含所有登录状态）\n")
        
        playwright = await async_playwright().start()
        
        # 创建一个临时的用户数据目录副本，避免与正在运行的 Chrome 冲突
        import tempfile
        import shutil
        
        temp_dir = tempfile.mkdtemp(prefix='playwright_chrome_')
        print(f"📁 创建临时目录: {temp_dir}")
        
        # 只复制必要的文件（避免复制整个 Chrome 数据目录）
        print("⏳ 正在复制 Cookie 和登录状态...")
        
        # 需要复制的文件
        files_to_copy = [
            'Cookies',
            'Cookies-journal',
            'Local Storage',
            'Session Storage',
            'Network',
        ]
        
        for file_name in files_to_copy:
            src = os.path.join(profile_path, file_name)
            dst = os.path.join(temp_dir, file_name)
            
            if os.path.exists(src):
                if os.path.isdir(src):
                    shutil.copytree(src, dst, dirs_exist_ok=True)
                else:
                    shutil.copy2(src, dst)
                print(f"  ✅ 已复制: {file_name}")
        
        print("\n⏳ 正在启动浏览器...")
        
        # 使用 Chromium 并指定用户数据目录
        browser = await playwright.chromium.launch_persistent_context(
            user_data_dir=temp_dir,
            headless=False,
            channel='chrome',  # 使用系统安装的 Chrome
            args=[
                '--disable-blink-features=AutomationControlled',
                '--disable-infobars',
            ],
            viewport={'width': 1920, 'height': 1080},
        )
        
        print("✅ 浏览器已启动\n")
        
        # 创建页面
        if len(browser.pages) > 0:
            page = browser.pages[0]
        else:
            page = await browser.new_page()
        
        # 访问 Whop 目标页面
        print(f"⏳ 正在访问: {Config.TARGET_URL}")
        await page.goto(Config.TARGET_URL, wait_until='networkidle')
        await asyncio.sleep(5)
        
        current_url = page.url
        print(f"✅ 当前页面: {current_url}\n")
        
        # 检查登录状态
        if 'login' in current_url.lower():
            print("⚠️  似乎被重定向到登录页面")
            print("   可能需要在浏览器中手动完成 Google 登录")
            print("\n请在浏览器中:")
            print("  1. 点击 'Sign in with Google'")
            print("  2. 选择你的 Google 账号")
            print("  3. 完成登录后，按 Enter 继续...")
            input("\n按 Enter 继续...")
            
            # 重新检查
            await asyncio.sleep(2)
            current_url = page.url
            print(f"当前页面: {current_url}")
        
        if 'login' not in current_url.lower():
            print("✅ 成功访问 Whop（已登录）\n")
            
            # 保存登录状态
            print("⏳ 正在保存登录状态...")
            await browser.storage_state(path=Config.STORAGE_STATE_PATH)
            print(f"✅ 登录状态已保存到: {Config.STORAGE_STATE_PATH}\n")
            
            # 测试提取消息
            print("⏳ 测试消息提取...")
            from scraper.monitor import MessageMonitor
            
            monitor = MessageMonitor(
                page=page,
                poll_interval=2.0,
            )
            
            messages = await monitor._extract_messages()
            if not messages:
                messages = await monitor._extract_messages_js()
            
            if messages:
                print(f"✅ 成功提取 {len(messages)} 条消息\n")
                print("消息预览:")
                for i, msg in enumerate(messages[:3], 1):
                    text_preview = msg['text'][:80] + "..." if len(msg['text']) > 80 else msg['text']
                    print(f"  [{i}] {text_preview}")
            else:
                print("⚠️  未提取到消息，可能需要检查页面选择器\n")
            
            print("\n" + "=" * 70)
            print("🎉 测试完成！")
            print("=" * 70)
            print("\n📝 后续步骤:")
            print("  1. 登录状态已保存，可以运行验证脚本:")
            print("     python3 test_whop_scraper.py")
            print("  2. 或启动主程序:")
            print("     python3 main.py\n")
            
            return True
        else:
            print("❌ 仍在登录页面，登录未成功\n")
            return False
        
    except Exception as e:
        print(f"\n❌ 出错: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    finally:
        # 等待用户查看
        print("\n浏览器将在 10 秒后关闭...")
        await asyncio.sleep(10)
        
        if browser:
            await browser.close()
            print("✅ 浏览器已关闭")
        
        if playwright:
            await playwright.stop()


async def interactive_profile_selection():
    """交互式选择 Chrome 配置文件"""
    print("\n" + "=" * 70)
    print("🔍 查找 Chrome 配置文件")
    print("=" * 70 + "\n")
    
    base_path = ChromeProfileManager.get_default_chrome_profile_path()
    print(f"Chrome 数据目录: {base_path}\n")
    
    if not os.path.exists(base_path):
        print("❌ 未找到 Chrome 数据目录")
        print("   请确保已安装 Google Chrome\n")
        return None
    
    profiles = ChromeProfileManager.list_chrome_profiles()
    
    if not profiles:
        print("❌ 未找到任何 Chrome 配置文件\n")
        return None
    
    print(f"找到 {len(profiles)} 个配置文件:\n")
    for i, profile in enumerate(profiles, 1):
        print(f"  [{i}] {profile['display']}")
        print(f"      路径: {profile['path']}")
        print()
    
    while True:
        choice = input(f"请选择配置文件 (1-{len(profiles)}) [默认: 1]: ").strip()
        
        if not choice:
            choice = '1'
        
        try:
            idx = int(choice) - 1
            if 0 <= idx < len(profiles):
                return profiles[idx]['path']
            else:
                print(f"⚠️  请输入 1 到 {len(profiles)} 之间的数字\n")
        except ValueError:
            print("⚠️  请输入有效的数字\n")


def print_help():
    """打印帮助信息"""
    print("""
╔══════════════════════════════════════════════════════════╗
║         使用 Chrome 配置文件工具 v1.0                      ║
║         Chrome Profile Tool                              ║
╚══════════════════════════════════════════════════════════╝

使用方法:
  python3 use_chrome_profile.py              # 交互式选择配置文件
  python3 use_chrome_profile.py --auto       # 自动使用默认配置文件
  python3 use_chrome_profile.py --help       # 显示帮助

说明:
  这个工具使用你系统 Chrome 浏览器中保存的登录状态来访问 Whop。
  如果你已经在 Chrome 中用 Google 账号登录过 Whop，
  这个工具会直接使用那个登录状态，无需重新登录。
  
优势:
  ✅ 自动使用 Google 账号登录
  ✅ 保持所有 Chrome 的 Cookie 和会话
  ✅ 无需手动输入密码
  ✅ 自动保存 Playwright 可用的登录状态
    """)


async def main():
    """主函数"""
    if '--help' in sys.argv or '-h' in sys.argv:
        print_help()
        return
    
    if '--auto' in sys.argv:
        # 自动使用默认配置文件
        profile_path = os.path.join(
            ChromeProfileManager.get_default_chrome_profile_path(),
            'Default'
        )
        await test_with_chrome_profile(profile_path)
    else:
        # 交互式选择
        profile_path = await interactive_profile_selection()
        if profile_path:
            await test_with_chrome_profile(profile_path)


if __name__ == "__main__":
    asyncio.run(main())
