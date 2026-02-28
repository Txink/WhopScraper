#!/usr/bin/env python3
"""
从原始消息 JSON 中过滤出指定股票（ticker）相关的消息，导出到 tmp/stock/origin_<ticker>_message.json。
匹配规则：仅看 content 中是否出现该 ticker（按整词、不区分大小写），不看 history。
用法:
  python3 scripts/parser/filter_target_stock.py TICKER [--input PATH] [--output PATH]
  默认输入：tmp/stock/origin_message.json
  默认输出：tmp/stock/origin_<TICKER>_message.json
"""
import argparse
import json
import re
import sys
from pathlib import Path

_project_root = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_project_root))


def _contains_ticker(text: str, ticker: str) -> bool:
    """判断文本中是否包含该 ticker（整词、不区分大小写）。
    使用 (?<![a-zA-Z0-9]) / (?![a-zA-Z0-9]) 替代 \\b，
    避免中文字符被 Python 3 视为 \\w 导致 \\b 边界失效。
    例：'开仓tsll' 中 \\btsll\\b 因'仓'是 \\w 而不匹配，改用此方法可正确匹配。
    """
    if not (text and isinstance(text, str)):
        return False
    pattern = re.compile(
        r"(?<![a-zA-Z0-9])" + re.escape(ticker) + r"(?![a-zA-Z0-9])",
        re.IGNORECASE
    )
    return pattern.search(text) is not None


def filter_messages(messages: list, ticker: str) -> list:
    """仅保留 content 中出现 ticker 的消息。"""
    result = []
    for item in messages:
        if not isinstance(item, dict):
            continue
        content = (item.get("content") or "").strip()
        if _contains_ticker(content, ticker):
            result.append(item)
    return result


def _parse_args():
    parser = argparse.ArgumentParser(
        description="过滤出指定股票相关的消息并导出。",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "ticker",
        type=str,
        help="股票代码（如 tsll、TSLL、HIMS）",
    )
    parser.add_argument(
        "--input",
        type=str,
        default=None,
        help="原始消息 JSON 路径；默认 tmp/stock/origin_message.json",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="导出路径；默认 tmp/stock/origin_<ticker>_message.json",
    )
    args = parser.parse_args()
    args.ticker = (args.ticker or "").strip().upper()
    if not args.ticker:
        parser.error("请提供 ticker")
    if args.input is None:
        args.input = _project_root / "tmp" / "stock" / "origin_message.json"
    else:
        args.input = Path(args.input)
    if not args.input.is_absolute():
        args.input = _project_root / args.input
    if args.output is None:
        args.output = _project_root / "tmp" / "stock" / f"origin_{args.ticker}_message.json"
    else:
        args.output = Path(args.output)
    if not args.output.is_absolute():
        args.output = _project_root / args.output
    return args


def main():
    args = _parse_args()
    if not args.input.exists():
        print(f"输入文件不存在: {args.input}")
        sys.exit(1)
    with open(args.input, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        print("输入 JSON 应为消息数组")
        sys.exit(1)
    filtered = filter_messages(data, args.ticker)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(filtered, f, ensure_ascii=False, indent=4)
    print(f"已过滤出 {len(filtered)} 条与 {args.ticker} 相关的消息 -> {args.output}")


if __name__ == "__main__":
    main()
