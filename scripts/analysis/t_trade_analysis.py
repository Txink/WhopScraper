#!/usr/bin/env python3
"""
股票 T 交易分析脚本

分析单一股票的买卖记录，找出哪些买入成本尚未通过 T 交易消除。

匹配规则：
  1. 以 A2 价格卖出 B2 股时，匹配之前买入价格 < A2 的记录（FIFO，最早买入优先）
     - 成功匹配的 B2 股视为"T完成"，不再关注
     - 剩余 B1-B2 股仍需后续 T 交易消除
  2. 若卖出量超过所有可匹配买入量，超额部分计入"待匹配卖出"缓冲
     - 后续出现买入价更低的记录时，再做对消

用法：
  python3 scripts/analysis/t_trade_analysis.py [TICKER] [--file PATH] [--days N]

  TICKER  股票代码，如 TSLL（不含 .US），默认 TSLL
  --file  交易记录 JSON 文件路径（不指定则从长桥 API 获取最近 N 天成交）
  --days  从 API 拉取最近多少天（默认 90），仅在不使用 --file 时生效
"""
import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List

from rich.console import Console
from rich.table import Table
from rich import box

_project_root = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_project_root))

console = Console()


# ───────────────────────── 解析辅助 ──────────────────────────

def _qty(v) -> int:
    try:
        return int(float(v or 0))
    except (ValueError, TypeError):
        return 0


def _price(v) -> float:
    try:
        return float(v or 0)
    except (ValueError, TypeError):
        return 0.0


def _ts(t: dict) -> str:
    return t.get("submitted_at") or ""


# ───────────────────────── 核心算法 ──────────────────────────

def analyze_t_trades(trades: List[Dict]) -> Dict:
    """
    匹配买卖记录，输出：
      unmatched_buys  — 尚未 T 出的买入批次
      matched         — 已完成的 T 交易对
      excess_sells    — 超额卖出（卖多于可匹配买入时的剩余）
    """
    trades = sorted(trades, key=_ts)

    # 待匹配的买入批次
    open_buys: List[Dict] = []
    # 待匹配的超额卖出（之前卖了但没有对应低价买入；等后续低价买入再消）
    excess_sells: List[Dict] = []
    # 已完成的 T 交易对
    matched: List[Dict] = []

    for trade in trades:
        side = (trade.get("side") or "").upper()
        qty   = _qty(trade.get("executed_quantity") or trade.get("quantity"))
        price = _price(trade.get("price"))
        ts    = _ts(trade)
        if qty <= 0 or price <= 0:
            continue

        if side == "BUY":
            remaining = qty
            # 先消化已有"超额卖出"中卖价更高的部分（即之前高价卖出，现在低价买入 → 逆向 T）
            new_excess = []
            for es in excess_sells:
                if es["price"] > price and remaining > 0:
                    mq = min(remaining, es["remaining_qty"])
                    matched.append({
                        "buy_ts": ts,       "buy_price": price,
                        "sell_ts": es["ts"], "sell_price": es["price"],
                        "quantity": mq,
                        "profit": round((es["price"] - price) * mq, 2),
                    })
                    remaining -= mq
                    leftover = es["remaining_qty"] - mq
                    if leftover > 0:
                        new_excess.append({**es, "remaining_qty": leftover})
                else:
                    new_excess.append(es)
            excess_sells = new_excess

            if remaining > 0:
                open_buys.append({
                    "ts": ts, "price": price,
                    "original_qty": remaining, "remaining_qty": remaining,
                })

        elif side == "SELL":
            remaining = qty
            # 按 FIFO 匹配价格低于卖价的开放买入批次
            for lot in open_buys:
                if lot["remaining_qty"] > 0 and lot["price"] < price and remaining > 0:
                    mq = min(remaining, lot["remaining_qty"])
                    matched.append({
                        "buy_ts": lot["ts"], "buy_price": lot["price"],
                        "sell_ts": ts,        "sell_price": price,
                        "quantity": mq,
                        "profit": round((price - lot["price"]) * mq, 2),
                    })
                    lot["remaining_qty"] -= mq
                    remaining -= mq

            # 剩余卖出量（无可匹配低价买入）→ 超额卖出缓冲
            if remaining > 0:
                excess_sells.append({"ts": ts, "price": price, "remaining_qty": remaining})

    unmatched = [lot for lot in open_buys if lot["remaining_qty"] > 0]
    return {
        "unmatched_buys": unmatched,
        "matched":        matched,
        "excess_sells":   excess_sells,
    }


# ───────────────────────── 显示 ──────────────────────────────

def _fmt_ts(ts: str) -> str:
    return ts.replace("T", " ").split(".")[0] if ts else "-"


def _fmt_price(p: float) -> str:
    return f"${p:.2f}"


def print_analysis(symbol: str, trades: List[Dict]) -> None:
    result = analyze_t_trades(trades)
    unmatched: List[Dict] = result["unmatched_buys"]
    matched:   List[Dict] = result["matched"]
    excess:    List[Dict] = result["excess_sells"]

    total_trades  = len(trades)
    total_matched = sum(m["quantity"] for m in matched)
    total_profit  = sum(m["profit"]   for m in matched)

    unmatched_qty   = sum(u["remaining_qty"] for u in unmatched)
    unmatched_cost  = (
        sum(u["price"] * u["remaining_qty"] for u in unmatched) / unmatched_qty
        if unmatched_qty else 0
    )

    net_qty = sum(
        _qty(t.get("executed_quantity") or t.get("quantity"))
        * (1 if (t.get("side") or "").upper() == "BUY" else -1)
        for t in trades
    )

    console.print()
    console.print(f"[bold cyan]{'═' * 55}[/bold cyan]")
    console.print(f"[bold cyan]  {symbol} T 交易分析   共 {total_trades} 条成交记录[/bold cyan]")
    console.print(f"[bold cyan]{'═' * 55}[/bold cyan]")

    # ── 待 T 出的买入批次 ──
    console.print()
    console.print(f"[bold yellow]📌 未 T 出的买入仓位（共 {unmatched_qty} 股，仍需做 T 消除）[/bold yellow]")
    if unmatched:
        tbl = Table(box=box.SIMPLE, show_header=True, header_style="bold white")
        tbl.add_column("买入时间",      style="dim",          width=20)
        tbl.add_column("买入价",        style="yellow",       justify="right", width=8)
        tbl.add_column("原始数量",      justify="right",      width=8)
        tbl.add_column("剩余待T",       justify="right",      width=8)
        tbl.add_column("已T占比",       justify="right",      width=8)
        for lot in sorted(unmatched, key=lambda x: x["ts"]):
            orig = lot["original_qty"]
            rem  = lot["remaining_qty"]
            tded = orig - rem
            pct  = f"{tded / orig * 100:.0f}%" if orig else "-"
            color = "green" if rem == 0 else ("yellow" if tded > 0 else "red")
            tbl.add_row(
                _fmt_ts(lot["ts"]),
                _fmt_price(lot["price"]),
                str(orig),
                f"[{color}]{rem}[/{color}]",
                pct,
            )
        console.print(tbl)
    else:
        console.print("  [green]✅ 所有买入仓位均已 T 出[/green]")

    # ── 已完成 T 交易 ──
    console.print()
    console.print(f"[bold green]✅ 已完成 T 交易（共 {len(matched)} 笔，T 出 {total_matched} 股，累计利润 ${total_profit:,.2f}）[/bold green]")
    if matched:
        tbl2 = Table(box=box.SIMPLE, show_header=True, header_style="bold white")
        tbl2.add_column("买入时间",  style="dim",     width=20)
        tbl2.add_column("买入价",    style="yellow",  justify="right", width=8)
        tbl2.add_column("卖出时间",  style="dim",     width=20)
        tbl2.add_column("卖出价",    style="cyan",    justify="right", width=8)
        tbl2.add_column("数量",      justify="right", width=7)
        tbl2.add_column("利润",      justify="right", width=10)
        for m in matched:
            profit_str = f"[green]+${m['profit']:,.2f}[/green]"
            tbl2.add_row(
                _fmt_ts(m["buy_ts"]),
                _fmt_price(m["buy_price"]),
                _fmt_ts(m["sell_ts"]),
                _fmt_price(m["sell_price"]),
                str(m["quantity"]),
                profit_str,
            )
        console.print(tbl2)

    # ── 超额卖出（异常情况提示）──
    if excess:
        excess_qty = sum(e["remaining_qty"] for e in excess)
        console.print()
        console.print(f"[bold red]⚠️  超额卖出未匹配（{excess_qty} 股卖出时无对应低价买入）[/bold red]")
        for e in excess:
            console.print(f"  {_fmt_ts(e['ts'])}  @ {_fmt_price(e['price'])}  {e['remaining_qty']} 股")

    # ── 汇总 ──
    console.print()
    console.print(f"[bold cyan]{'─' * 55}[/bold cyan]")
    console.print(f"[bold]📊 汇总[/bold]")
    console.print(f"  当前净持仓（买-卖）：[bold]{net_qty} 股[/bold]")
    console.print(f"  待 T 出：            [bold red]{unmatched_qty} 股[/bold red]  加权均价 {_fmt_price(unmatched_cost)}")
    console.print(f"  已 T 出：            [bold green]{total_matched} 股[/bold green]  累计利润 [green]${total_profit:,.2f}[/green]")
    console.print(f"[bold cyan]{'─' * 55}[/bold cyan]")
    console.print()


# ───────────────────────── 数据源 ────────────────────────────

def _is_filled(order: Dict) -> bool:
    """判断订单是否已成交（用于当日订单筛选）。"""
    s = (order.get("status") or "").upper()
    return "FILLED" in s or "FILL" in s


def fetch_trades_from_longbridge(symbol: str, days: int = 90) -> List[Dict]:
    """通过长桥 API 获取指定股票最近 days 天的已成交订单（含当日已成交）。"""
    try:
        from broker import LongPortBroker
    except ImportError as e:
        console.print(f"[red]❌ 无法导入 LongPortBroker: {e}，请安装依赖并配置长桥环境变量[/red]")
        sys.exit(1)

    broker = None
    try:
        broker = LongPortBroker()
        end_at = datetime.now()
        start_at = end_at - timedelta(days=days)
        console.print(f"[dim]正在从长桥 API 拉取 {symbol} 最近 {days} 天成交记录（含当日）…[/dim]")
        history = broker.get_history_orders(start_at, end_at)
        trades = [o for o in history if o.get("symbol") == symbol]
        seen_ids = {str(o.get("order_id")) for o in trades if o.get("order_id")}

        # 历史接口多数不包含当日，补充当日已成交订单并去重
        today_orders = broker.get_today_orders()
        for o in today_orders:
            if o.get("symbol") != symbol or not _is_filled(o):
                continue
            oid = str(o.get("order_id")) if o.get("order_id") else None
            if oid and oid in seen_ids:
                continue
            trades.append(o)
            if oid:
                seen_ids.add(oid)

        trades.sort(key=lambda r: r.get("submitted_at") or "")
        return trades
    except Exception as e:
        console.print(f"[red]❌ 长桥 API 请求失败: {e}[/red]")
        sys.exit(1)
    finally:
        if broker is not None:
            try:
                broker.close()
            except Exception:
                pass


def load_trades_from_file(symbol: str, data_file: Path) -> List[Dict]:
    """从本地 JSON 文件加载该 symbol 的交易记录。"""
    if not data_file.exists():
        console.print(f"[red]❌ 找不到文件: {data_file}[/red]")
        sys.exit(1)
    with open(data_file, encoding="utf-8") as f:
        all_records: Dict = json.load(f)
    return all_records.get(symbol, [])


# ───────────────────────── 入口 ──────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="股票 T 交易分析")
    parser.add_argument("ticker", nargs="?", default="TSLL",
                        help="股票代码，如 TSLL（不含 .US），默认 TSLL")
    parser.add_argument("--file", default=None,
                        help="交易记录 JSON 文件路径（指定后从文件读取，不请求 API）")
    parser.add_argument("--days", type=int, default=90,
                        help="与 API 合用，拉取最近多少天（默认 90）")
    args = parser.parse_args()

    ticker = args.ticker.upper().replace(".US", "")
    symbol = f"{ticker}.US"

    use_file = args.file is not None
    if use_file:
        data_file = Path(args.file)
        trades = load_trades_from_file(symbol, data_file)
    else:
        trades = fetch_trades_from_longbridge(symbol, days=args.days)

    if not trades:
        if use_file:
            console.print(f"[yellow]⚠️  {symbol} 在 {data_file.name} 中无交易记录[/yellow]")
        else:
            console.print(f"[yellow]⚠️  长桥 API 返回 {symbol} 最近 {args.days} 天无成交记录[/yellow]")
        sys.exit(0)

    print_analysis(symbol, trades)


if __name__ == "__main__":
    main()
