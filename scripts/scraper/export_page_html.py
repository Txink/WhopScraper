#!/usr/bin/env python3
"""
打开目标页面，导出当前页面 HTML 到指定路径。
不依赖环境变量，通过命令行参数控制；未传参数时使用默认配置。
用法:
  python3 scripts/scraper/export_page_html.py [--type stock|option] [--output PATH] [--url URL]
  默认：--type stock，--output tmp/${type}/page_html.html；可选 --url 指定页面，否则从 PAGES 按 type 取首个。
"""
import argparse
import asyncio
import sys
from pathlib import Path
from typing import Optional

_project_root = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_project_root))

if (_project_root / ".env").is_file():
    from dotenv import load_dotenv
    load_dotenv(_project_root / ".env")

from config import Config
from scraper.browser import BrowserManager


def _get_url_by_type(page_type: str) -> Optional[str]:
    """从 Config.get_all_pages() 中按 type 取首个 URL。"""
    pages = Config.get_all_pages()
    for url, t, _ in pages:
        if t == page_type:
            return url
    return None


def _parse_args():
    parser = argparse.ArgumentParser(
        description="打开目标页面并导出当前 HTML。",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--type",
        choices=("stock", "option"),
        default="stock",
        help="页面类型，用于未传 --url 时从 PAGES 中选取对应类型页面",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="HTML 导出路径；默认 tmp/<type>/page_html.html",
    )
    parser.add_argument(
        "--url",
        type=str,
        default=None,
        help="目标页面 URL；不传则从 .env PAGES 中按 --type 取首个",
    )
    args = parser.parse_args()
    if args.output is None:
        args.output = str(_project_root / "tmp" / args.type / "page_html.html")
    out_path = Path(args.output)
    if not out_path.is_absolute():
        out_path = _project_root / out_path
    args.output_path = out_path
    if not args.url:
        args.url = _get_url_by_type(args.type)
    return args


async def main():
    args = _parse_args()
    url = args.url
    if not url:
        print(f"未配置 type={args.type} 的页面，请传 --url 或在 .env 的 PAGES 中添加对应类型页面。")
        return
    print(f"目标页面: {url}")
    print(f"HTML 导出路径: {args.output_path}")

    browser = BrowserManager(
        headless=False,
        slow_mo=Config.SLOW_MO,
        storage_state_path=Config.STORAGE_STATE_PATH,
        maximize_window=False,
    )
    page = await browser.start()

    if not await browser.is_logged_in(url):
        print("需要登录...")
        ok = await browser.login(Config.WHOP_EMAIL, Config.WHOP_PASSWORD, Config.LOGIN_URL)
        if not ok:
            print("登录失败")
            await browser.close()
            return
    if not await browser.navigate(url):
        print("无法导航到目标页面")
        await browser.close()
        return

    await asyncio.sleep(2)

    html = await page.content()
    args.output_path.parent.mkdir(parents=True, exist_ok=True)
    args.output_path.write_text(html, encoding="utf-8")
    print(f"已导出 HTML -> {args.output_path}")

    await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
