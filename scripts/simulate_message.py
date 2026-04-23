"""
模拟一条 Whop 消息通过 RecordManager 管道，观察 stock_parser 的解析结果。
用于在终端直观看到：消息 -> 解析 -> instruction 的每一步表现。

用法：
    python3 scripts/simulate_message.py "夜盘13.1附近加仓hood"
    python3 scripts/simulate_message.py           # 运行一组默认用例
    python3 scripts/simulate_message.py --file path/to/text.txt
"""
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models.message import MessageGroup
from models.record_manager import RecordManager


def simulate(content: str, page_type: str = "stock") -> None:
    msg = MessageGroup(
        group_id=f"sim-{datetime.now().strftime('%Y%m%d%H%M%S%f')}",
        author="xiaozhaolucky",
        timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S.000"),
        primary_message=content,
    )
    mgr = RecordManager(page_type=page_type)
    records = mgr.create_records([msg])
    mgr.analyze_records(records)

    print("\n" + "=" * 72)
    print(f"输入: {content!r}")
    print("-" * 72)
    for r in records:
        inst = r.instruction
        if inst is None:
            print("  ❌ 解析失败（instruction = None）")
            continue
        ignored = getattr(inst, "ignored_by_watchlist", False)
        fields = [
            ("ticker", getattr(inst, "ticker", None)),
            ("action", getattr(inst, "action", None)),
            ("price", getattr(inst, "price", None)),
            ("quantity", getattr(inst, "quantity", None)),
            ("bucket", getattr(inst, "bucket", None)),
            ("ignored_by_watchlist", ignored),
        ]
        for k, v in fields:
            print(f"  {k:22s} = {v}")
        if ignored:
            print("  ⚠ 不在 config/watched_stocks.json → 实盘不会下单")

        # 让 instruction 自带的 display 也输出一次（对齐真实终端表现）
        if hasattr(inst, "display"):
            try:
                inst.display()
            except Exception as e:
                print(f"  (display() 抛错: {e})")


def main() -> None:
    args = sys.argv[1:]
    if args and args[0] == "--file":
        with open(args[1], "r", encoding="utf-8") as f:
            content = f.read().strip()
        simulate(content)
        return

    if args:
        simulate(" ".join(args))
        return

    # 默认覆盖几种常见场景
    cases = [
        "TSLL 11.88 买入",
        "夜盘13.1附近加仓hood",
        "hood 130可以建仓",
        "cifr可以夜盘和盘前找找15附近的价格回吸点",
        "盘前在16附近建仓cifr",
        "cifr可以夜盘和盘前找找15附近的价格回吸点 盘中有平期权波动回踩再加一笔 盘中在更新下盘中的价格 hood可以夜盘和盘前找找117附近的价格回吸点",
    ]
    for c in cases:
        simulate(c)


if __name__ == "__main__":
    main()
