#!/usr/bin/env python3
"""
股票页消息抓取脚本
支持两种模式（环境变量 AUTO_SCROLL_HISTORY 控制）：
1. 自动历史分页（默认）：脚本自动将消息区滚动到顶部，触发「上一页」加载，每次加载后立即
   提取并按 domID 去重保存，避免 DOM 回收导致丢失；直到连续 2 轮无新消息或达到最大轮数后结束。
2. 定时抓取（AUTO_SCROLL_HISTORY=false）：有界面打开，每 N 秒抓取当前 DOM，需手动滚动，Ctrl+C 结束。
用法：
  python3 scripts/capture_stock_messages.py [URL]
  环境变量：AUTO_SCROLL_HISTORY、SCROLL_TOP_WAIT_MS、MAX_HISTORY_ROUNDS、CAPTURE_INTERVAL_SEC；
           USE_WHEEL_SCROLL、WHEEL_SCROLL_STEPS、WHEEL_SCROLL_DELTA。
  导出 HTML：加参数 --export-html 或设 EXPORT_HTML=1，仅打开页面并将当前 HTML 保存到 test/data/stock_html.html 后退出。
"""
import asyncio
import json
import os
import sys
from pathlib import Path

_project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_project_root))

if (_project_root / ".env").is_file():
    from dotenv import load_dotenv
    load_dotenv(_project_root / ".env")

from config import Config
from scraper.browser import BrowserManager
from scraper.message_extractor import EnhancedMessageExtractor
from parser.stock_parser import StockParser
from utils.watched_stocks import get_watched_tickers


def _output_paths():
    """原始消息与解析结果输出路径，可由环境变量 STOCK_ORIGIN_OUTPUT_PATH、STOCK_PARSED_OUTPUT_PATH 覆盖。"""
    origin = os.getenv("STOCK_ORIGIN_OUTPUT_PATH", "").strip()
    parsed = os.getenv("STOCK_PARSED_OUTPUT_PATH", "").strip()
    origin_path = Path(origin) if origin else _project_root / "data" / "stock_origin_message.json"
    if not origin_path.is_absolute():
        origin_path = _project_root / origin_path
    if not parsed:
        parsed_path = origin_path.parent / "stock_parsed_message.json"
    else:
        parsed_path = Path(parsed) if Path(parsed).is_absolute() else _project_root / parsed
    return origin_path, parsed_path


OUTPUT_PATH = _project_root / "data" / "stock_origin_message.json"  # 默认，main 内按 env 覆盖
PARSED_OUTPUT_PATH = _project_root / "data" / "stock_parsed_message.json"
EXPORT_HTML_PATH = _project_root / "test" / "data" / "stock_html.html"


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


def _get_filter_tickers():
    """解析时只保留这些 ticker 的指令；为空则保留所有解析出的股票指令。"""
    env_ticker = os.getenv("FILTER_TICKER", "").strip().upper()
    if env_ticker:
        return {env_ticker}
    return get_watched_tickers()


# 查找消息区滚动容器并返回其中心点坐标（用于模拟滚轮）、以及设置 scrollTop=0 的脚本
# 返回 { centerX, centerY } 或 null；若仅需 scrollTop 则用 _SCROLL_TOP_JS
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
        scrollTop: scrollEl.scrollTop,
        scrollHeight: scrollEl.scrollHeight,
        clientHeight: scrollEl.clientHeight
    };
}
"""

# 仅将滚动容器 scrollTop 设为 0（不模拟滚轮）
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


def _export_parsed(messages, path: Path) -> None:
    """将消息列表解析为关注股票的 StockInstruction 并写入 path。"""
    filter_tickers = _get_filter_tickers()
    parsed_list = []
    for msg in messages:
        content = (msg.primary_message or "").strip()
        if not content:
            continue
        inst = StockParser.parse(
            content,
            message_id=msg.group_id,
            message_timestamp=getattr(msg, "timestamp", None),
        )
        if inst is None:
            continue
        ticker = (inst.ticker or "").strip().upper()
        if filter_tickers and ticker not in filter_tickers:
            continue
        inst.origin = msg
        if getattr(msg, "timestamp", None):
            inst.timestamp = msg.timestamp
        inst.ensure_symbol()
        parsed_list.append(inst.to_dict())
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(parsed_list, f, ensure_ascii=False, indent=2)


def _merged_count(path: Path) -> int:
    """返回已保存文件中去重后的消息条数。"""
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return len(data) if isinstance(data, list) else 0
    except (FileNotFoundError, json.JSONDecodeError):
        return 0


async def _trigger_scroll_up(page, use_wheel: bool, wheel_steps: int, wheel_delta: int) -> None:
    """
    触发「向上滚动」以加载上一页。use_wheel=True 时在滚动容器上模拟鼠标滚轮向上（更易触发页面加载逻辑）。
    """
    if use_wheel:
        info = await page.evaluate(_FIND_SCROLL_CONTAINER_JS)
        if info and "centerX" in info:
            x = info["centerX"]
            y = info["centerY"]
            await page.mouse.move(x, y)
            for _ in range(wheel_steps):
                await page.mouse.wheel(0, -wheel_delta)
                await asyncio.sleep(0.08)
        else:
            await page.evaluate(_SCROLL_TOP_JS)
    else:
        await page.evaluate(_SCROLL_TOP_JS)


async def _run_auto_history(page, extractor, wait_ms: int, max_rounds: int, output_path: Path, parsed_path: Path) -> None:
    """
    自动滚动到顶部触发上一页加载，每轮：模拟向上滚动（滚轮或 scrollTop）-> 等待 -> 提取并保存（避免 DOM 回收丢失）。
    连续 2 轮合并后条数未增加则结束。
    """
    use_wheel = os.getenv("USE_WHEEL_SCROLL", "true").lower() in ("1", "true", "yes")
    wheel_steps = max(3, int(os.getenv("WHEEL_SCROLL_STEPS", "8")))
    wheel_delta = max(100, int(os.getenv("WHEEL_SCROLL_DELTA", "800")))
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
        _export_parsed(messages, parsed_path)
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


async def main():
    # URL：命令行参数 > 环境变量 STOCK_PAGE_URL > .env PAGES 首个 stock
    url = None
    if len(sys.argv) > 1 and sys.argv[1].startswith("http"):
        url = sys.argv[1].strip()
    if not url:
        url = os.getenv("STOCK_PAGE_URL", "").strip()
    if not url:
        pages = Config.get_all_pages()
        stock_pages = [(u, t, name) for u, t, name in pages if t == "stock"]
        if not stock_pages:
            print("未配置 type=stock 的页面，请设置 STOCK_PAGE_URL 或在 .env 的 PAGES 中添加正股页面。")
            return
        url, _, name = stock_pages[0]
    print(f"目标页面: {url}")
    output_path, parsed_path = _output_paths()
    print(f"输出路径: 原始消息 -> {output_path}，解析结果 -> {parsed_path}")

    # 本脚本固定有界面模式，启动时最大化窗口便于消息区全屏、滚轮落在正确区域
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

    # 仅导出 HTML 到本地后退出
    if os.getenv("EXPORT_HTML", "").strip() in ("1", "true", "yes") or "--export-html" in sys.argv:
        html = await page.content()
        EXPORT_HTML_PATH.parent.mkdir(parents=True, exist_ok=True)
        EXPORT_HTML_PATH.write_text(html, encoding="utf-8")
        print(f"已导出 HTML -> {EXPORT_HTML_PATH}")
        await browser.close()
        return

    extractor = EnhancedMessageExtractor(page)
    auto_history = os.getenv("AUTO_SCROLL_HISTORY", "true").lower() in ("1", "true", "yes")

    if auto_history:
        wait_ms = max(1500, int(os.getenv("SCROLL_TOP_WAIT_MS", "2500")))
        max_rounds = max(5, int(os.getenv("MAX_HISTORY_ROUNDS", "100")))
        print(f"\n自动加载历史分页：每轮滚动到顶部 -> 等待 {wait_ms}ms -> 提取并保存，最多 {max_rounds} 轮。\n")
        await _run_auto_history(page, extractor, wait_ms, max_rounds, output_path, parsed_path)
        print("历史分页抓取完成。")
    else:
        interval_sec = max(3, int(os.getenv("CAPTURE_INTERVAL_SEC", "10")))
        print(f"\n定时抓取模式：每 {interval_sec} 秒抓取当前 DOM，请手动滚动，Ctrl+C 结束。\n")
        try:
            while True:
                try:
                    messages = await extractor.extract_message_groups()
                except Exception as e:
                    if "Target closed" in str(e) or "browser has been closed" in str(e):
                        break
                    print(f"本次提取失败: {e}")
                    await asyncio.sleep(interval_sec)
                    continue
                rows = [_message_row_from_group(m) for m in messages]
                _merge_and_save(rows, output_path)
                _export_parsed(messages, parsed_path)
                await asyncio.sleep(interval_sec)
        except KeyboardInterrupt:
            pass
        print("已结束抓取。")

    await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
