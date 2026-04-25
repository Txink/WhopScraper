"""Whop 交互式登录助手 —— 打开浏览器，等用户手动登录，然后保存 cookie。

用法（在 signal-station 项目根目录）:

    # 首次登录：打开浏览器登录后保存 cookie
    uv run --project backend python scripts/whop_login.py

    # 验证 cookie 还有效
    uv run --project backend python scripts/whop_login.py --test

    # 指定自定义 URL（比如直接跳到某个频道）
    uv run --project backend python scripts/whop_login.py --url https://whop.com/joined/xxx/

    # cookie 路径默认 .auth/whop_cookie.json，与后端 WhopBrowser 加载路径一致
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from playwright.async_api import async_playwright


# 默认路径：项目根/.auth/whop_cookie.json，对齐 app/whop/login.py::cookie_path()
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_COOKIE = PROJECT_ROOT / ".auth" / "whop_cookie.json"

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)


async def manual_login(login_url: str, cookie_path: Path) -> None:
    print("=" * 60)
    print("Whop 登录助手")
    print("=" * 60)
    print(f"将打开浏览器访问: {login_url}")
    print(f"Cookie 将保存到: {cookie_path}")
    print("=" * 60)

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=False,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--window-size=1280,800",
            ],
        )
        context = await browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent=USER_AGENT,
        )
        page = await context.new_page()

        print(f"\n正在访问 {login_url} ...")
        try:
            await page.goto(login_url, wait_until="domcontentloaded", timeout=60_000)
        except Exception as e:
            print(f"⚠️  页面加载警告: {e}（继续等待登录）")

        print("\n✅ 浏览器已打开\n")
        print("📝 请在浏览器中完成以下操作：")
        print("   1. 输入邮箱 + 密码（如有 2FA 也一并完成）")
        print("   2. 等待跳转到主页 / 频道页面")
        print("   3. 确认页面已正常显示，没有再要求登录")
        print("\n👇 然后回到终端按回车继续 …")

        # 阻塞等待用户回车（不阻塞 asyncio loop）
        await asyncio.get_event_loop().run_in_executor(None, input)

        cookie_path.parent.mkdir(parents=True, exist_ok=True)
        await context.storage_state(path=str(cookie_path))

        print(f"\n✅ 登录状态已保存到 {cookie_path}")
        print(f"   当前 URL: {page.url}")
        print("\n后续运行后端 (uvicorn app.main:app) 时会自动加载这个 cookie。")

        await context.close()
        await browser.close()


async def test_login(test_url: str, cookie_path: Path) -> int:
    print("=" * 60)
    print("Whop 登录状态测试")
    print("=" * 60)
    print(f"Cookie: {cookie_path}")
    print(f"测试访问: {test_url}")

    if not cookie_path.is_file():
        print(f"\n❌ Cookie 文件不存在: {cookie_path}")
        print("   先运行: python scripts/whop_login.py 完成首次登录")
        return 1

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=False,
            args=["--disable-blink-features=AutomationControlled"],
        )
        context = await browser.new_context(
            storage_state=str(cookie_path),
            viewport={"width": 1280, "height": 800},
            user_agent=USER_AGENT,
        )
        page = await context.new_page()
        try:
            await page.goto(test_url, wait_until="domcontentloaded", timeout=60_000)
        except Exception as e:
            print(f"⚠️  页面加载警告: {e}")

        await asyncio.sleep(3)
        current = page.url

        print(f"\n实际 URL: {current}")
        if "login" in current.lower():
            print("\n❌ Cookie 已失效（被重定向到登录页）")
            ret = 1
        else:
            print("\n✅ Cookie 有效，可以启动监听")
            ret = 0

        print("\n浏览器 5 秒后关闭…")
        await asyncio.sleep(5)
        await context.close()
        await browser.close()
        return ret


async def _main() -> int:
    parser = argparse.ArgumentParser(
        description="Whop 交互式登录助手",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--url",
        default="https://whop.com/login/",
        help="登录页或目标频道 URL（默认 https://whop.com/login/）",
    )
    parser.add_argument(
        "--test",
        action="store_true",
        help="不登录，仅用已保存的 cookie 访问 --url 验证有效性",
    )
    parser.add_argument(
        "--cookie",
        default=str(DEFAULT_COOKIE),
        help=f"cookie 文件路径（默认 {DEFAULT_COOKIE}）",
    )
    args = parser.parse_args()

    cookie_path = Path(args.cookie).expanduser().resolve()
    if args.test:
        return await test_login(args.url, cookie_path)
    await manual_login(args.url, cookie_path)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(_main()))
    except KeyboardInterrupt:
        print("\n操作已取消。")
        sys.exit(130)
