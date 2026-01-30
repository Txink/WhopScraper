"""
Playwright 浏览器管理模块
处理浏览器启动、登录和 Cookie 持久化
"""
import os
import asyncio
from typing import Optional
from playwright.async_api import async_playwright, Browser, BrowserContext, Page, Playwright


class BrowserManager:
    """浏览器管理器"""
    
    def __init__(
        self,
        headless: bool = False,
        slow_mo: int = 0,
        storage_state_path: str = "storage_state.json"
    ):
        """
        初始化浏览器管理器
        
        Args:
            headless: 是否无头模式运行
            slow_mo: 操作延迟（毫秒），用于调试
            storage_state_path: Cookie 存储路径
        """
        self.headless = headless
        self.slow_mo = slow_mo
        self.storage_state_path = storage_state_path
        
        self._playwright: Optional[Playwright] = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None
    
    async def start(self) -> Page:
        """
        启动浏览器并返回页面对象
        
        Returns:
            Page 对象
        """
        self._playwright = await async_playwright().start()
        
        # 启动 Chromium 浏览器
        self._browser = await self._playwright.chromium.launch(
            headless=self.headless,
            slow_mo=self.slow_mo,
            args=[
                '--disable-blink-features=AutomationControlled',
                '--disable-infobars',
                '--window-size=1920,1080',
            ]
        )
        
        # 检查是否有保存的登录状态
        if os.path.exists(self.storage_state_path):
            print(f"加载已保存的登录状态: {self.storage_state_path}")
            self._context = await self._browser.new_context(
                storage_state=self.storage_state_path,
                viewport={'width': 1920, 'height': 1080},
                user_agent=(
                    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                    'AppleWebKit/537.36 (KHTML, like Gecko) '
                    'Chrome/120.0.0.0 Safari/537.36'
                )
            )
        else:
            print("首次启动，需要登录")
            self._context = await self._browser.new_context(
                viewport={'width': 1920, 'height': 1080},
                user_agent=(
                    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                    'AppleWebKit/537.36 (KHTML, like Gecko) '
                    'Chrome/120.0.0.0 Safari/537.36'
                )
            )
        
        self._page = await self._context.new_page()
        return self._page
    
    async def login(self, email: str, password: str, login_url: str) -> bool:
        """
        执行登录操作
        
        Args:
            email: 登录邮箱
            password: 登录密码
            login_url: 登录页面 URL
            
        Returns:
            是否登录成功
        """
        if not self._page:
            raise RuntimeError("浏览器未启动，请先调用 start()")
        
        try:
            print(f"正在访问登录页面: {login_url}")
            try:
                await self._page.goto(
                    login_url,
                    wait_until='domcontentloaded',
                    timeout=60000
                )
            except Exception as e:
                print(f"⚠️  页面加载警告: {e}")
            
            # 等待页面加载
            await asyncio.sleep(3)
            
            # 查找并填写邮箱
            # Whop 登录页面可能使用不同的选择器，这里尝试多种可能
            email_selectors = [
                'input[type="email"]',
                'input[name="email"]',
                'input[placeholder*="email" i]',
                '#email',
            ]
            
            email_input = None
            for selector in email_selectors:
                try:
                    email_input = await self._page.wait_for_selector(
                        selector, timeout=3000
                    )
                    if email_input:
                        break
                except Exception:
                    continue
            
            if not email_input:
                print("错误: 找不到邮箱输入框")
                return False
            
            await email_input.fill(email)
            print("已填写邮箱")
            
            # 查找并填写密码
            password_selectors = [
                'input[type="password"]',
                'input[name="password"]',
                '#password',
            ]
            
            password_input = None
            for selector in password_selectors:
                try:
                    password_input = await self._page.wait_for_selector(
                        selector, timeout=3000
                    )
                    if password_input:
                        break
                except Exception:
                    continue
            
            if not password_input:
                print("错误: 找不到密码输入框")
                return False
            
            await password_input.fill(password)
            print("已填写密码")
            
            # 查找并点击登录按钮
            login_button_selectors = [
                'button[type="submit"]',
                'button:has-text("Log in")',
                'button:has-text("登录")',
                'button:has-text("Sign in")',
                'input[type="submit"]',
            ]
            
            login_button = None
            for selector in login_button_selectors:
                try:
                    login_button = await self._page.wait_for_selector(
                        selector, timeout=3000
                    )
                    if login_button:
                        break
                except Exception:
                    continue
            
            if not login_button:
                print("错误: 找不到登录按钮")
                return False
            
            await login_button.click()
            print("已点击登录按钮")
            
            # 等待登录完成
            await asyncio.sleep(5)
            
            # 检查是否登录成功（通过 URL 变化或页面元素判断）
            current_url = self._page.url
            if 'login' not in current_url.lower():
                print("登录成功!")
                # 保存登录状态
                await self.save_storage_state()
                return True
            else:
                print("登录可能失败，当前 URL:", current_url)
                return False
                
        except Exception as e:
            print(f"登录过程出错: {e}")
            return False
    
    async def save_storage_state(self):
        """保存当前的登录状态（Cookie 等）"""
        if self._context:
            await self._context.storage_state(path=self.storage_state_path)
            print(f"已保存登录状态到: {self.storage_state_path}")
    
    async def navigate(self, url: str) -> bool:
        """
        导航到指定页面
        
        Args:
            url: 目标 URL
            
        Returns:
            是否成功
        """
        if not self._page:
            raise RuntimeError("浏览器未启动，请先调用 start()")
        
        try:
            print(f"正在导航到: {url}")
            try:
                await self._page.goto(
                    url,
                    wait_until='domcontentloaded',
                    timeout=60000
                )
            except Exception as e:
                print(f"⚠️  页面加载警告: {e}")
            
            await asyncio.sleep(3)
            print(f"已到达页面: {self._page.url}")
            return True
        except Exception as e:
            print(f"导航失败: {e}")
            return False
    
    async def is_logged_in(self, target_url: str) -> bool:
        """
        检查是否已登录
        
        Args:
            target_url: 目标页面 URL
            
        Returns:
            是否已登录
        """
        if not self._page:
            return False
        
        try:
            try:
                await self._page.goto(
                    target_url,
                    wait_until='domcontentloaded',
                    timeout=60000
                )
            except Exception as e:
                print(f"⚠️  页面加载警告: {e}")
            
            await asyncio.sleep(3)
            
            # 检查是否被重定向到登录页面
            current_url = self._page.url
            if 'login' in current_url.lower():
                return False
            
            # 检查页面是否有需要登录的提示
            content = await self._page.content()
            login_indicators = [
                'requires one of the products',
                'Log in',
                'Sign in',
                '请登录',
            ]
            
            for indicator in login_indicators:
                if indicator.lower() in content.lower():
                    # 可能需要登录，但不一定，需要进一步检查
                    pass
            
            return True
            
        except Exception as e:
            print(f"检查登录状态失败: {e}")
            return False
    
    @property
    def page(self) -> Optional[Page]:
        """获取当前页面对象"""
        return self._page
    
    @property
    def context(self) -> Optional[BrowserContext]:
        """获取当前浏览器上下文"""
        return self._context
    
    async def close(self):
        """关闭浏览器"""
        if self._context:
            await self._context.close()
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()
        
        print("浏览器已关闭")
    
    async def __aenter__(self):
        """支持 async with 语法"""
        await self.start()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """支持 async with 语法"""
        await self.close()
