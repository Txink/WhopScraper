#!/usr/bin/env python3
"""
打开目标页面，全屏浏览器，自动滚动抓取消息并导出到指定路径。
不依赖环境变量，通过命令行参数控制；未传参数时使用默认配置。
用法:
  python3 scripts/scraper/export_page_message.py [--type stock|option] [--output PATH] [--url URL]
  默认：--type stock，--output tmp/${type}/origin_message.json；可选 --url 指定页面，否则从 PAGES 按 type 取首个。
"""
import argparse
import asyncio
import json
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
from scraper.message_extractor import EnhancedMessageExtractor

# 查找消息区滚动容器（用于模拟滚轮）
_FIND_SCROLL_CONTAINER_JS = """
() => {
    const first = document.querySelector('[data-message-id]');
    if (!first) return null;
    let scrollEl = null;
    if (first.closest) {
        scrollEl = first.closest('[class*="overflow-y-scroll"]') || first.closest('.fui-ScrollAreaViewport');
    }
    if (!scrollEl) {
        let p = first.parentElement;
        while (p) {
            const style = window.getComputedStyle(p);
            const oy = style.overflowY;
            const sh = p.scrollHeight, ch = p.clientHeight;
            if ((oy === 'auto' || oy === 'scroll' || oy === 'overlay') && sh > ch + 5) {
                scrollEl = p;
                break;
            }
            p = p.parentElement;
        }
    }
    if (!scrollEl) return null;
    const rect = scrollEl.getBoundingClientRect();
    return {
        centerX: rect.left + rect.width / 2,
        centerY: rect.top + rect.height / 2,
    };
}
"""

_SCROLL_TOP_JS = """
() => {
    const first = document.querySelector('[data-message-id]');
    if (!first) return 0;
    let scrollEl = null;
    if (first.closest) {
        scrollEl = first.closest('[class*="overflow-y-scroll"]') || first.closest('.fui-ScrollAreaViewport');
    }
    if (!scrollEl) {
        let p = first.parentElement;
        while (p) {
            const style = window.getComputedStyle(p);
            const oy = style.overflowY;
            const sh = p.scrollHeight, ch = p.clientHeight;
            if ((oy === 'auto' || oy === 'scroll' || oy === 'overlay') && sh > ch + 5) {
                scrollEl = p;
                break;
            }
            p = p.parentElement;
        }
    }
    if (scrollEl) scrollEl.scrollTop = 0;
    return document.querySelectorAll('[data-message-id]').length;
}
"""


def _message_row_from_group(message) -> dict:
    """从 MessageGroup 构建与 origin_message 一致的单条格式。"""
    return {
        "domID": message.group_id,
        "content": (message.primary_message or "").strip(),
        "timestamp": message.timestamp or "",
        "refer": message.quoted_context if message.quoted_context else None,
        "position": message.get_position(),
        "history": list(message.history or []),
    }


def _merge_and_save(new_rows: list, path: Path) -> None:
    """按 domID 去重、按 timestamp 排序后写回。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        data = []
    if not isinstance(data, list):
        data = []
    by_id = {item.get("domID"): item for item in data}
    for row in new_rows:
        dom_id = row.get("domID") or ""
        if dom_id:
            by_id[dom_id] = row
    merged = list(by_id.values())
    merged.sort(key=lambda m: (m.get("timestamp") or ""))
    with open(path, "w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False, indent=4)
    print(f"已写入 {len(new_rows)} 条新消息，合计 {len(merged)} 条 -> {path}")


def _merged_count(path: Path) -> int:
    """返回已保存文件中去重后的消息条数。"""
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return len(data) if isinstance(data, list) else 0
    except (FileNotFoundError, json.JSONDecodeError):
        return 0


async def _trigger_scroll_up(page, use_wheel: bool, wheel_steps: int, wheel_delta: int) -> None:
    """触发向上滚动以加载上一页。"""
    if use_wheel:
        info = await page.evaluate(_FIND_SCROLL_CONTAINER_JS)
        if info and "centerX" in info:
            x, y = info["centerX"], info["centerY"]
            await page.mouse.move(x, y)
            for _ in range(wheel_steps):
                await page.mouse.wheel(0, -wheel_delta)
                await asyncio.sleep(0.08)
        else:
            await page.evaluate(_SCROLL_TOP_JS)
    else:
        await page.evaluate(_SCROLL_TOP_JS)


async def _run_auto_history(
    page,
    extractor: EnhancedMessageExtractor,
    output_path: Path,
    *,
    wait_ms: int = 2500,
    max_rounds: int = 100,
    use_wheel: bool = True,
    wheel_steps: int = 8,
    wheel_delta: int = 800,
) -> None:
    """自动滚动到顶部触发上一页加载，每轮提取并保存，连续 2 轮无新消息或达最大轮数后结束。"""
    if use_wheel:
        print(f"  使用模拟滚轮向上：{wheel_steps} 步，每步 deltaY=-{wheel_delta}，再等待 {wait_ms}ms")
    prev_merged = 0
    no_increase_rounds = 0
    for r in range(max_rounds):
        await _trigger_scroll_up(page, use_wheel, wheel_steps, wheel_delta)
        await asyncio.sleep(wait_ms / 1000.0)
        try:
            messages = await extractor.extract_message_groups()
        except Exception as e:
            print(f"  第 {r+1} 轮提取失败: {e}")
            no_increase_rounds += 1
            if no_increase_rounds >= 2:
                break
            continue
        rows = [_message_row_from_group(m) for m in messages]
        _merge_and_save(rows, output_path)
        merged = _merged_count(output_path)
        if merged > prev_merged:
            print(f"  第 {r+1} 轮：当前 DOM {len(rows)} 条，去重后合计 {merged} 条")
            prev_merged = merged
            no_increase_rounds = 0
        else:
            no_increase_rounds += 1
            if no_increase_rounds >= 2:
                print(f"  第 {r+1} 轮后无新消息，停止。共 {merged} 条。")
                break
    if no_increase_rounds < 2:
        print(f"  已达最大轮数 {max_rounds}，当前合计 {_merged_count(output_path)} 条。")


def _get_url_by_type(page_type: str) -> Optional[str]:
    """从 Config.get_all_pages() 中按 type 取首个 URL。"""
    pages = Config.get_all_pages()
    for url, t, _ in pages:
        if t == page_type:
            return url
    return None


def _parse_args():
    parser = argparse.ArgumentParser(
        description="打开目标页面，全屏自动滚动抓取消息并导出。",
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
        help="消息导出路径；默认 tmp/<type>/origin_message.json",
    )
    parser.add_argument(
        "--url",
        type=str,
        default=None,
        help="目标页面 URL；不传则从 .env PAGES 中按 --type 取首个",
    )
    args = parser.parse_args()
    if args.output is None:
        args.output = str(_project_root / "tmp" / args.type / "origin_message.json")
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
    print(f"消息导出路径: {args.output_path}")

    browser = BrowserManager(
        headless=False,
        slow_mo=Config.SLOW_MO,
        storage_state_path=Config.STORAGE_STATE_PATH,
        maximize_window=True,
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

    extractor = EnhancedMessageExtractor(page)
    print(f"\n自动加载历史分页：每轮滚动到顶部 -> 等待 2500ms -> 提取并保存，最多 100 轮。\n")
    await _run_auto_history(page, extractor, args.output_path)
    print("历史分页抓取完成。")

    await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
