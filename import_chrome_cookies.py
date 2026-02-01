#!/usr/bin/env python3
"""
从系统 Chrome 导入 Cookies 和登录状态
将 Chrome 的登录状态转换为 Playwright 可用的格式
"""
import asyncio
import os
import sys
import json
import sqlite3
import shutil
from pathlib import Path
from datetime import datetime

from config import Config


class ChromeCookieImporter:
    """Chrome Cookie 导入器"""
    
    @staticmethod
    def get_chrome_cookie_path():
        """获取 Chrome Cookies 数据库路径"""
        if sys.platform == 'darwin':  # macOS
            return os.path.expanduser('~/Library/Application Support/Google/Chrome/Default/Cookies')
        elif sys.platform == 'win32':  # Windows
            return os.path.expanduser('~/AppData/Local/Google/Chrome/User Data/Default/Cookies')
        else:  # Linux
            return os.path.expanduser('~/.config/google-chrome/Default/Cookies')
    
    @staticmethod
    def extract_cookies_for_domain(domain='whop.com'):
        """从 Chrome 提取指定域名的 Cookies"""
        cookie_path = ChromeCookieImporter.get_chrome_cookie_path()
        
        if not os.path.exists(cookie_path):
            print(f"❌ Chrome Cookies 文件不存在: {cookie_path}")
            return None
        
        # Chrome 的 Cookies 是 SQLite 数据库，可能被锁定
        # 创建一个临时副本来读取
        import tempfile
        temp_cookie_path = os.path.join(tempfile.gettempdir(), 'chrome_cookies_temp.db')
        
        try:
            shutil.copy2(cookie_path, temp_cookie_path)
            
            # 连接到数据库
            conn = sqlite3.connect(temp_cookie_path)
            cursor = conn.cursor()
            
            # 查询 cookies
            # Chrome 的 cookies 表结构：
            # host_key, name, value, path, expires_utc, is_secure, is_httponly, etc.
            cursor.execute("""
                SELECT host_key, name, value, path, expires_utc, is_secure, is_httponly, samesite
                FROM cookies
                WHERE host_key LIKE ?
            """, (f'%{domain}%',))
            
            cookies = []
            for row in cursor.fetchall():
                host_key, name, value, path, expires_utc, is_secure, is_httponly, samesite = row
                
                # Chrome 的 expires_utc 是从 1601-01-01 开始的微秒数
                # 转换为 Unix 时间戳（秒）
                if expires_utc > 0:
                    # Chrome epoch is 1601-01-01, Unix epoch is 1970-01-01
                    # Difference: 11644473600 seconds
                    expires = (expires_utc / 1000000.0) - 11644473600
                else:
                    expires = -1
                
                cookie = {
                    'name': name,
                    'value': value,
                    'domain': host_key,
                    'path': path,
                    'expires': expires,
                    'httpOnly': bool(is_httponly),
                    'secure': bool(is_secure),
                    'sameSite': ['None', 'Lax', 'Strict'][samesite] if samesite in [0, 1, 2] else 'None'
                }
                
                cookies.append(cookie)
            
            conn.close()
            os.remove(temp_cookie_path)
            
            return cookies
            
        except Exception as e:
            print(f"❌ 提取 Cookies 失败: {e}")
            if os.path.exists(temp_cookie_path):
                os.remove(temp_cookie_path)
            return None


async def import_and_verify():
    """导入 Chrome Cookies 并验证"""
    print("\n" + "=" * 70)
    print("🔄 从系统 Chrome 导入登录状态")
    print("=" * 70 + "\n")
    
    # 步骤 1：提取 Chrome Cookies
    print("⏳ 正在从 Chrome 提取 Cookies...")
    print(f"   Chrome Cookies 路径: {ChromeCookieImporter.get_chrome_cookie_path()}\n")
    
    cookies = ChromeCookieImporter.extract_cookies_for_domain('whop.com')
    
    if not cookies:
        print("❌ 未能提取到 Whop 的 Cookies")
        print("\n可能的原因:")
        print("  1. Chrome 未安装或路径不对")
        print("  2. 你还没在 Chrome 中登录 Whop")
        print("  3. Chrome 正在运行（需要先关闭 Chrome）")
        print("\n解决方案:")
        print("  1. 确保在 Chrome 中登录了 Whop")
        print("  2. 关闭所有 Chrome 窗口")
        print("  3. 重新运行此脚本\n")
        return False
    
    print(f"✅ 成功提取 {len(cookies)} 个 Whop 相关的 Cookies\n")
    
    # 显示关键 Cookies
    print("关键 Cookies:")
    for cookie in cookies[:5]:
        print(f"  - {cookie['name']}: {cookie['value'][:20]}...")
    if len(cookies) > 5:
        print(f"  ... 还有 {len(cookies) - 5} 个")
    print()
    
    # 步骤 2：创建 Playwright storage state
    print("⏳ 正在创建 Playwright 存储状态...")
    
    storage_state = {
        'cookies': cookies,
        'origins': []
    }
    
    # 保存到文件
    storage_path = Config.STORAGE_STATE_PATH
    with open(storage_path, 'w') as f:
        json.dump(storage_state, f, indent=2)
    
    print(f"✅ 已保存到: {storage_path}\n")
    
    # 步骤 3：验证登录状态
    print("⏳ 正在验证导入的登录状态...")
    
    from playwright.async_api import async_playwright
    
    playwright = None
    browser = None
    
    try:
        playwright = await async_playwright().start()
        browser = await playwright.chromium.launch(headless=False)
        
        context = await browser.new_context(storage_state=storage_path)
        page = await context.new_page()
        
        print(f"   访问: {Config.TARGET_URL}")
        await page.goto(Config.TARGET_URL, wait_until='networkidle')
        await asyncio.sleep(5)
        
        current_url = page.url
        print(f"   当前页面: {current_url}\n")
        
        if 'login' not in current_url.lower():
            print("✅ 登录状态有效！成功使用 Chrome 的登录状态")
            
            # 测试消息提取
            print("\n⏳ 测试消息提取...")
            from scraper.monitor import MessageMonitor
            
            monitor = MessageMonitor(
                page=page,
                poll_interval=2.0,
                output_file=Config.OUTPUT_FILE,
                enable_sample_collection=False
            )
            
            messages = await monitor._extract_messages()
            if not messages:
                messages = await monitor._extract_messages_js()
            
            if messages:
                print(f"✅ 成功提取 {len(messages)} 条消息！\n")
                print("消息预览:")
                for i, msg in enumerate(messages[:3], 1):
                    text_preview = msg['text'][:80] + "..." if len(msg['text']) > 80 else msg['text']
                    print(f"  [{i}] {text_preview}")
            else:
                print("⚠️  未提取到消息（但登录状态有效）\n")
            
            print("\n" + "=" * 70)
            print("🎉 导入成功！")
            print("=" * 70)
            print("\n📝 下一步:")
            print("  1. 运行验证脚本:")
            print("     python3 test_whop_scraper.py")
            print("  2. 或运行页面分析:")
            print("     python3 analyze_page_structure.py")
            print("  3. 或启动主程序:")
            print("     python3 main.py\n")
            
            # 等待查看
            print("浏览器将在 10 秒后关闭...")
            await asyncio.sleep(10)
            
            return True
            
        else:
            print("❌ 登录状态无效，仍被重定向到登录页面")
            print("\n可能的原因:")
            print("  1. Chrome 中的登录已过期")
            print("  2. Cookies 不完整")
            print("  3. Whop 需要额外的身份验证\n")
            print("建议:")
            print("  1. 在 Chrome 中重新登录 Whop")
            print("  2. 或使用手动登录工具: python3 setup_login.py\n")
            
            return False
            
    except Exception as e:
        print(f"❌ 验证失败: {e}")
        import traceback
        traceback.print_exc()
        return False
        
    finally:
        if browser:
            await browser.close()
        if playwright:
            await playwright.stop()


def check_chrome_status():
    """检查 Chrome 状态"""
    print("\n" + "=" * 70)
    print("🔍 检查系统 Chrome 状态")
    print("=" * 70 + "\n")
    
    cookie_path = ChromeCookieImporter.get_chrome_cookie_path()
    print(f"Chrome Cookies 路径: {cookie_path}")
    
    if os.path.exists(cookie_path):
        print("✅ Chrome Cookies 文件存在")
        
        # 获取文件大小
        size = os.path.getsize(cookie_path)
        print(f"   文件大小: {size / 1024:.2f} KB")
        
        # 获取修改时间
        mtime = os.path.getmtime(cookie_path)
        mtime_str = datetime.fromtimestamp(mtime).strftime('%Y-%m-%d %H:%M:%S')
        print(f"   最后修改: {mtime_str}\n")
        
        # 尝试读取 Cookies
        print("⏳ 正在检查 Whop Cookies...")
        cookies = ChromeCookieImporter.extract_cookies_for_domain('whop.com')
        
        if cookies:
            print(f"✅ 找到 {len(cookies)} 个 Whop 相关的 Cookies")
            print("\nCookie 列表:")
            for cookie in cookies:
                print(f"  - {cookie['name']}")
            print("\n👍 可以导入这些 Cookies！")
            print("   运行: python3 import_chrome_cookies.py\n")
        else:
            print("❌ 未找到 Whop 相关的 Cookies")
            print("   请确保在 Chrome 中登录了 Whop\n")
    else:
        print("❌ Chrome Cookies 文件不存在")
        print("   请确保已安装 Google Chrome 并至少打开过一次\n")


def print_help():
    """打印帮助信息"""
    print("""
╔══════════════════════════════════════════════════════════╗
║      Chrome Cookies 导入工具 v1.0                         ║
║      Chrome Cookie Importer                              ║
╚══════════════════════════════════════════════════════════╝

使用方法:
  python3 import_chrome_cookies.py            # 导入 Chrome Cookies
  python3 import_chrome_cookies.py --check    # 检查 Chrome 状态
  python3 import_chrome_cookies.py --help     # 显示帮助

说明:
  这个工具从你系统 Chrome 中提取 Whop 的登录状态（Cookies），
  并转换为 Playwright 可用的格式。
  
前提条件:
  1. 已安装 Google Chrome
  2. 在 Chrome 中登录过 Whop
  3. Chrome 必须完全关闭（不能有任何窗口打开）
  
优势:
  ✅ 直接使用 Chrome 的登录状态
  ✅ 无需在 Playwright 中重新登录
  ✅ 支持 Google 账号等复杂登录方式
  ✅ 一次导入，永久使用
  
注意事项:
  ⚠️  必须先关闭所有 Chrome 窗口
  ⚠️  如果导入失败，使用备用方案: python3 setup_login.py
    """)


async def main():
    """主函数"""
    if '--help' in sys.argv or '-h' in sys.argv:
        print_help()
        return
    
    if '--check' in sys.argv or '-c' in sys.argv:
        check_chrome_status()
        return
    
    # 默认执行导入
    print("\n⚠️  重要提示:")
    print("  请确保已经关闭所有 Chrome 窗口！")
    print("  否则无法访问 Cookies 数据库。\n")
    
    choice = input("Chrome 已关闭？(y/n) [y]: ").strip().lower()
    if choice and choice != 'y':
        print("\n请先关闭 Chrome，然后重新运行此脚本。")
        return
    
    await import_and_verify()


if __name__ == "__main__":
    asyncio.run(main())
