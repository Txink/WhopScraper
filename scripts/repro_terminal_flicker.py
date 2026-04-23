"""
复现"终端消息一闪而过"问题：
用真实的 RichLogger + RecordManager 管道，连续喂入多条 MessageGroup，
观察 Rich Live 面板行为。

使用：
    python3 scripts/repro_terminal_flicker.py          # 交互模式，在 TTY 看效果
    python3 scripts/repro_terminal_flicker.py --dump   # 捕获 ANSI 到文件，事后分析
"""
import os
import sys
import time
from datetime import datetime
from io import StringIO

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rich.console import Console

import utils.rich_logger as rich_logger_mod
from utils.rich_logger import RichLogger, set_logger
from models.message import MessageGroup
from models.record_manager import RecordManager


CASES = [
    ("post_AAA", "TSLL 11.88 买入"),
    ("post_BBB", "HOOD 130可以建仓"),
    ("post_CCC", "CIFR 15附近回吸"),
    ("post_DDD", "夜盘13.1附近加仓hood"),
]


def run_scenario(logger: RichLogger, *, register_order_for_first: bool = False):
    """模拟 scan_once 的主循环（不经过 DOM / Playwright）。"""
    mgr = RecordManager(page_type="stock")
    msgs = [
        MessageGroup(
            group_id=gid,
            author="sim",
            timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S.000"),
            primary_message=content,
        )
        for gid, content in CASES
    ]
    records = mgr.create_records(msgs)
    mgr.analyze_records(records)

    for idx, record in enumerate(records):
        dom_id = record.message.group_id
        logger.trade_start(dom_id=dom_id)
        record.message.display()
        if record.instruction is not None:
            record.instruction.display()
        # 第一条模拟已下单：注册 order_id，使该 flow 在 trade_end 后保留在 Live 中
        if idx == 0 and register_order_for_first:
            logger.trade_register_order(order_id=f"FAKE_ORDER_{idx}", dom_id=dom_id)
        logger.trade_end(dom_id=dom_id)
        # 模拟两次 scan 之间的间隔
        time.sleep(0.3)


def main():
    dump = "--dump" in sys.argv
    keep_first_alive = "--keep-first-alive" in sys.argv

    if dump:
        # 用 StringIO 接输出，强制彩色，保留 ANSI 控制序列，事后分析
        buf = StringIO()
        console = Console(
            file=buf,
            force_terminal=True,
            force_interactive=True,
            color_system="truecolor",
            width=120,
        )
        logger = RichLogger(console=console)
        set_logger(logger)

        run_scenario(logger, register_order_for_first=keep_first_alive)

        raw = buf.getvalue()
        out_path = os.path.join(os.path.dirname(__file__), "..", "tmp", "flicker_dump.ansi")
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(raw)

        print(f"ANSI 输出已写入 {out_path}  (共 {len(raw)} 字节)")
        # 简要统计 ANSI 控制序列
        esc = raw.count("\x1b[")
        clr_line = raw.count("\x1b[2K")  # 清除整行
        cur_up = sum(1 for _ in range(len(raw)) if raw[_:_+3].startswith("\x1b[") and "A" in raw[_:_+5])
        print(f"  ESC 序列: {esc}")
        print(f"  清除整行 (ESC[2K): {clr_line}")
        return

    # 交互 TTY 模式
    console = Console()
    logger = RichLogger(console=console)
    set_logger(logger)
    run_scenario(logger, register_order_for_first=keep_first_alive)
    print("\n--- 回放完成 ---")


if __name__ == "__main__":
    main()
