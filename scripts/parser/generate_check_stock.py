#!/usr/bin/env python3
"""
从指定股票的 origin_<TICKER>_message.json 生成 check_<TICKER>_message.json。
每条消息用 StockParser 解析，check 字段格式与 data/check.json 一致，symbol 使用传入的 TICKER。

仓位计算规则（基于 data/watched_stocks.json）：
  - 默认买入/卖出仓位 = bucket * position（整数股数）
  - 卖出一半（sell_quantity == '1/2'）= bucket * position * 0.5
  - 小仓位（position_size/sell_quantity == '小仓位'）= bucket * position（同常规仓）
  - 买入标注"常规仓的一半/一半" = bucket * position * 0.5

价格规则（基于 STOCK_PRICE_DEVIATION_TOLERANCE 配置）：
  - 实际下单时：若市场价不超过目标价容忍度，则用市场价；否则用目标价
  - check 中输出 target_price（目标价）供参考

用法:
  python3 scripts/parser/generate_check_stock.py TICKER [--input PATH] [--output PATH]
  默认输入：tmp/stock/origin_<TICKER>_message.json
  默认输出：tmp/stock/check_<TICKER>_message.json
"""
import argparse
import json
import os
import sys
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Optional


def _round2(x: float) -> float:
    """标准四舍五入保留2位小数（避免 Python round() 银行家舍入问题）。"""
    return float(Decimal(str(x)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))

_project_root = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_project_root))

from parser.stock_parser import StockParser
from utils.watched_stocks import get_stock_position_shares, get_bucket_ratio


def _calc_quantity(ticker: str, sell_quantity: Optional[str], position_size: Optional[str]) -> Optional[int]:
    """
    根据 watched_stocks 配置计算具体股数。
    - 默认（含小仓位）= bucket * position（常规仓）
    - 一半（sell_quantity='1/2' 或 position_size 含"一半"）= bucket * position * 0.5
    - 分数比例（如 sell_quantity='1/3'）= bucket * position * ratio
    """
    position = get_stock_position_shares(ticker)
    if position is None or position <= 0:
        return None
    bucket = get_bucket_ratio(ticker)
    base = position * bucket

    # 卖出比例优先
    if sell_quantity:
        if sell_quantity == '1/2':
            return max(1, int(base * 0.5))
        if '/' in sell_quantity and sell_quantity != '小仓位':
            try:
                num, den = sell_quantity.split('/')
                ratio = int(num) / int(den)
                return max(1, int(base * ratio))
            except Exception:
                pass
        # 小仓位 / 全部 / 其他 → 默认常规仓

    # 买入仓位标注：仅"含一半"时减半
    if position_size:
        ps = position_size.strip()
        if '一半' in ps:
            return max(1, int(base * 0.5))
        # 小仓位 / 常规仓 / 其他 → 默认常规仓

    return max(1, int(base))


def _instruction_to_check(inst, message_timestamp: str, symbol: str) -> Optional[dict]:
    """将 StockInstruction 转为与 check.json 一致的 check 对象，附带仓位计算。"""
    if inst is None:
        return None

    ticker = (getattr(inst, 'ticker', None) or symbol or "").strip().upper()

    # 目标价（指令价），标准四舍五入保留2位小数
    target_price = None
    if inst.price is not None:
        target_price = _round2(inst.price)
    elif getattr(inst, "price_range", None) and len(inst.price_range) >= 2:
        target_price = _round2((inst.price_range[0] + inst.price_range[1]) / 2)

    check = {
        "timestamp": (message_timestamp or getattr(inst, "timestamp", None) or "").strip(),
        "instruction_type": inst.instruction_type,
        "symbol": symbol,
    }

    if target_price is not None:
        check["target_price"] = target_price
    if getattr(inst, "price_range", None):
        check["price_range"] = inst.price_range

    sell_quantity = getattr(inst, "sell_quantity", None)
    position_size = getattr(inst, "position_size", None)

    if sell_quantity:
        check["sell_quantity"] = sell_quantity
    if position_size:
        check["position_size"] = position_size

    # 计算具体股数
    quantity = _calc_quantity(ticker, sell_quantity, position_size)
    if quantity is not None:
        check["quantity"] = quantity

    # 参考价
    ref_price = getattr(inst, "sell_reference_price", None)
    if ref_price is not None:
        check["sell_reference_price"] = ref_price
    ref_label = getattr(inst, "sell_reference_label", None)
    if ref_label:
        check["sell_reference_label"] = ref_label
    buy_ref = getattr(inst, "buy_quantity_reference", None)
    if buy_ref:
        check["buy_quantity_reference"] = buy_ref

    if getattr(inst, "stop_loss_price", None) is not None:
        check["stop_loss_price"] = inst.stop_loss_price

    return check


def _parse_args():
    parser = argparse.ArgumentParser(description="根据原始消息生成 check_<TICKER>_message.json")
    parser.add_argument("ticker", type=str, help="股票代码，如 TSLL")
    parser.add_argument("--input", type=str, default=None, help="原始消息 JSON 路径")
    parser.add_argument("--output", type=str, default=None, help="输出 check JSON 路径（默认 tmp/stock/check_<TICKER>_message.json）")
    args = parser.parse_args()
    args.ticker = (args.ticker or "").strip().upper()
    if not args.ticker:
        parser.error("请提供 ticker")
    if args.input is None:
        args.input = _project_root / "tmp" / "stock" / f"origin_{args.ticker}_message.json"
    else:
        args.input = Path(args.input)
    if not args.input.is_absolute():
        args.input = _project_root / args.input
    if args.output is None:
        args.output = _project_root / "tmp" / "stock" / f"check_{args.ticker}_message.json"
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
        messages = json.load(f)
    if not isinstance(messages, list):
        print("输入 JSON 应为消息数组")
        sys.exit(1)
    symbol = args.ticker
    result = []
    for msg in messages:
        if not isinstance(msg, dict):
            result.append({"origin": msg, "check": None})
            continue
        content = (msg.get("content") or "").strip()
        dom_id = msg.get("domID") or ""
        ts = msg.get("timestamp") or ""
        origin = {
            "domID": dom_id,
            "content": content,
            "original_content": content,
            "timestamp": ts,
            "refer": msg.get("refer"),
            "position": msg.get("position"),
            "history": msg.get("history") if isinstance(msg.get("history"), list) else [],
        }
        inst = StockParser.parse(content, message_id=dom_id, message_timestamp=ts)
        if inst is None:
            result.append({"origin": origin, "check": None})
            continue
        ticker_parsed = (getattr(inst, "ticker") or "").strip().upper()
        if ticker_parsed and ticker_parsed != symbol:
            result.append({"origin": origin, "check": None})
            continue
        check = _instruction_to_check(inst, ts, symbol)
        result.append({"origin": origin, "check": check})
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    with_check = sum(1 for r in result if r.get("check") is not None)
    print(f"已生成 {len(result)} 条记录，其中 {with_check} 条有 check -> {args.output}")


if __name__ == "__main__":
    main()
