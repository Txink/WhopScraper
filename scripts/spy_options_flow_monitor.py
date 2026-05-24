#!/usr/bin/env python3
"""
SPY 期权大单实时监听

支持三种数据源（无需 Polygon 也可使用）：
1. yfinance：轮询 Yahoo 期权链，根据相邻两次成交量差值识别「大单」（无 API Key，数据通常有延迟）
2. longport：轮询长桥期权报价（需已配置 LONGPORT_*），使用现有行情权限，延迟通常小于 yfinance
3. polygon：Polygon.io WebSocket 逐笔成交（需 POLYGON_API_KEY 且订阅 Options 数据）

用法:
  # 使用 yfinance（默认，无需 API Key）
  python3 scripts/spy_options_flow_monitor.py --source yfinance

  # 使用长桥行情（需 .env 中已配置 LONGPORT_*）
  python3 scripts/spy_options_flow_monitor.py --source longport

  # 使用 Polygon 实时期权成交（需配置 POLYGON_API_KEY）
  python3 scripts/spy_options_flow_monitor.py --source polygon

  python3 scripts/spy_options_flow_monitor.py [--source yfinance|longport|polygon] [--min-contracts 100] [--min-premium 50000] [--expiry-days 45] [--poll-interval 60]
  # 使用 Polygon 时需传 API Key：--source polygon --polygon-api-key YOUR_KEY
  # 只看总价 100 万美元以上的大单：--min-premium 1000000
  # 说明：轮询模式（yfinance/longport）仅有成交量增量，无法区分买/卖方向。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

# 项目根目录加入 path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

try:
    import websockets
except ImportError:
    websockets = None
try:
    import requests
except ImportError:
    requests = None
try:
    import yfinance as yf
except ImportError:
    yf = None

# 长桥：仅脚本内按需导入，避免未配置时影响主程序
_longport_quote_ctx = None

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# Polygon WebSocket 选项集群
POLYGON_WS_OPTIONS_URL = "wss://socket.polygon.io/options"
POLYGON_OPTIONS_CONTRACTS_URL = "https://api.polygon.io/v3/reference/options/contracts"


def _load_env() -> None:
    """从 .env 加载环境变量（若存在）"""
    env_path = os.path.join(os.path.dirname(__file__), "..", ".env")
    if os.path.isfile(env_path):
        try:
            from dotenv import load_dotenv
            load_dotenv(env_path)
        except Exception:
            pass


def _parse_polygon_symbol(sym: str) -> dict:
    """解析 Polygon 期权符号 O:SPY250321C00600000"""
    result = {"raw": sym, "underlying": "SPY", "expiry": "", "type": "?", "strike": 0.0}
    if not sym.startswith("O:") or len(sym) < 18:
        return result
    rest = sym[2:]
    result["underlying"] = rest[:3] if rest[:3].isalpha() else "SPY"
    try:
        result["expiry"] = f"20{rest[3:5]}-{rest[5:7]}-{rest[7:9]}"
        result["type"] = "C" if rest[9].upper() == "C" else "P"
        result["strike"] = float(rest[10:18].lstrip("0") or "0") / 1000.0
    except Exception:
        pass
    return result


def _parse_yf_contract_symbol(symbol: str) -> dict:
    """解析 Yahoo 期权合约符号 如 SPY250321C00600000 或 SPY250321C00600000"""
    result = {"raw": symbol, "underlying": "SPY", "expiry": "", "type": "?", "strike": 0.0}
    if len(symbol) < 15:
        return result
    try:
        result["underlying"] = symbol[:3]
        result["expiry"] = f"20{symbol[3:5]}-{symbol[5:7]}-{symbol[7:9]}"
        result["type"] = "C" if symbol[9].upper() == "C" else "P"
        result["strike"] = float(symbol[10:18].lstrip("0") or "0") / 1000.0
    except Exception:
        pass
    return result


def fetch_spy_option_contracts_polygon(api_key: str, expiry_days: int = 45) -> List[str]:
    """通过 Polygon REST 获取 SPY 期权合约列表。"""
    if not requests:
        return []
    expiry_after = (datetime.now(timezone.utc) + timedelta(days=expiry_days)).strftime("%Y-%m-%d")
    params = {
        "underlying_ticker": "SPY",
        "expiration_date.gte": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "expiration_date.lte": expiry_after,
        "limit": 1000,
        "apiKey": api_key,
    }
    symbols: List[str] = []
    try:
        resp = requests.get(POLYGON_OPTIONS_CONTRACTS_URL, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        for r in data.get("results") or []:
            ticker = r.get("ticker")
            if ticker:
                symbols.append(ticker)
        logger.info("Polygon 已拉取 SPY 期权合约数量: %s（%s 天内到期）", len(symbols), expiry_days)
    except Exception as e:
        logger.warning("Polygon 拉取合约失败: %s，使用内置示例列表", e)
        today = date.today()
        for d in range(0, min(expiry_days, 60), 7):
            dte = today + timedelta(days=d)
            yy, mm, dd = str(dte.year)[2:], dte.strftime("%m"), dte.strftime("%d")
            for strike in range(550, 601, 5):
                for opt_type in ("C", "P"):
                    symbols.append(f"O:SPY{yy}{mm}{dd}{opt_type}{strike * 1000:08d}")
            if len(symbols) >= 200:
                break
    return symbols[:1000]


def is_large_trade(
    size: int,
    price: float,
    min_contracts: int,
    min_premium_usd: float,
) -> bool:
    """判断是否为「大单」"""
    if size >= min_contracts:
        return True
    premium = price * size * 100
    return premium >= min_premium_usd


def format_polygon_trade(
    msg: dict,
    min_contracts: int,
    min_premium_usd: float,
) -> Optional[str]:
    """格式化 Polygon 单笔大单"""
    if msg.get("ev") != "T":
        return None
    sym = msg.get("sym", "")
    p, s = float(msg.get("p", 0)), int(msg.get("s", 0))
    if not is_large_trade(s, p, min_contracts, min_premium_usd):
        return None
    premium = p * s * 100
    parsed = _parse_polygon_symbol(sym)
    ts = ""
    if msg.get("t"):
        try:
            ts = datetime.fromtimestamp(int(msg["t"]) / 1000, tz=timezone.utc).strftime("%H:%M:%S")
        except Exception:
            ts = str(msg["t"])
    return (
        f"[大单] {parsed['underlying']} {parsed['expiry']} {parsed['type']} {parsed['strike']:.0f} "
        f"| 张数={s} 权利金≈${premium:,.0f} @ {p:.2f} | {ts}"
    )


# --------------- yfinance 轮询 ---------------


def fetch_spy_option_chain_yfinance(expiry_days: int) -> List[Tuple[str, str, float, float, float]]:
    """拉取 SPY 期权链（Yahoo），返回 (contractSymbol, expiry, strike, lastPrice, volume) 列表。"""
    if not yf:
        return []
    out: List[Tuple[str, str, float, float, float]] = []
    try:
        ticker = yf.Ticker("SPY")
        expirations = getattr(ticker, "options", None) or []
        if not expirations:
            return []
        cutoff = (datetime.now(timezone.utc) + timedelta(days=expiry_days)).date()
        for exp_str in expirations:
            try:
                exp_date = datetime.strptime(exp_str, "%Y-%m-%d").date()
                if exp_date > cutoff:
                    continue
            except Exception:
                continue
            try:
                chain = ticker.option_chain(exp_str)
            except Exception:
                continue
            for _, row in (chain.calls or []).iterrows():
                sym = getattr(row, "contractSymbol", None) or getattr(row, "contractSymbol", "")
                strike = float(getattr(row, "strike", 0) or 0)
                last = float(getattr(row, "lastPrice", 0) or getattr(row, "last", 0) or 0)
                vol = int(getattr(row, "volume", 0) or 0)
                if sym:
                    out.append((str(sym), exp_str, strike, last, vol))
            for _, row in (chain.puts or []).iterrows():
                sym = getattr(row, "contractSymbol", None) or getattr(row, "contractSymbol", "")
                strike = float(getattr(row, "strike", 0) or 0)
                last = float(getattr(row, "lastPrice", 0) or getattr(row, "last", 0) or 0)
                vol = int(getattr(row, "volume", 0) or 0)
                if sym:
                    out.append((str(sym), exp_str, strike, last, vol))
    except Exception as e:
        logger.debug("yfinance 拉取期权链异常: %s", e)
    return out


def run_yfinance_poll(
    min_contracts: int,
    min_premium_usd: float,
    expiry_days: int,
    poll_interval: float,
) -> None:
    """yfinance 轮询：对比相邻两次成交量，增量达到阈值则视为大单并打印。"""
    if not yf:
        logger.error("请安装 yfinance: pip install yfinance")
        return
    logger.info(
        "SPY 期权大单监听（yfinance 轮询，每 %s 秒）。仅输出 权利金>=$%s 的增量。数据可能有延迟。",
        poll_interval, min_premium_usd,
    )
    logger.info("等待大单…（仅成交量增量，无法区分买/卖方向，Ctrl+C 退出）")
    prev: Dict[str, float] = {}  # contractSymbol -> volume
    while True:
        try:
            rows = fetch_spy_option_chain_yfinance(expiry_days)
        except Exception as e:
            logger.warning("拉取期权链失败: %s", e)
            time.sleep(poll_interval)
            continue
        now_ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
        for sym, expiry, strike, last_price, vol in rows:
            key = sym
            prev_vol = prev.get(key, 0.0)
            delta = max(0, (vol - prev_vol))
            prev[key] = float(vol)
            if delta == 0:
                continue
            est_premium = (last_price or 0) * delta * 100
            # 仅当权利金达到阈值才输出（避免仅因张数>=100 就输出小额单）
            if est_premium < min_premium_usd:
                continue
            parsed = _parse_yf_contract_symbol(sym)
            print(
                f"[大单] {parsed['underlying']} {expiry} {parsed['type']} {strike:.0f} "
                f"| 增量张数={int(delta)} 权利金≈${est_premium:,.0f} @ {last_price:.2f} | {now_ts}"
            )
        time.sleep(poll_interval)


# --------------- 长桥轮询 ---------------

def _get_longport_quote_ctx():
    """按需创建长桥 QuoteContext（仅行情，不建交易连接）。"""
    global _longport_quote_ctx
    if _longport_quote_ctx is not None:
        return _longport_quote_ctx
    try:
        from broker.config_loader import LongPortConfigLoader
        from longport.openapi import QuoteContext
        config = LongPortConfigLoader().get_config()
        _longport_quote_ctx = QuoteContext(config)
        return _longport_quote_ctx
    except Exception as e:
        logger.error("长桥 QuoteContext 初始化失败: %s", e)
        return None


def fetch_spy_option_symbols_longport(expiry_days: int, max_symbols: int = 500) -> List[str]:
    """通过长桥获取 SPY 期权合约代码列表（.US 格式），限制在 expiry_days 内且总数不超过 max_symbols。"""
    ctx = _get_longport_quote_ctx()
    if ctx is None:
        return []
    symbol = "SPY.US"
    symbols: List[str] = []
    try:
        resp = ctx.option_chain_expiry_date_list(symbol)
        if not resp:
            return []
        today = date.today()
        cutoff = today + timedelta(days=expiry_days)
        expiries: List[Tuple[date, str]] = []
        for date_obj in resp:
            if hasattr(date_obj, "strftime"):
                d = date_obj
            else:
                try:
                    d = datetime.strptime(str(date_obj)[:10], "%Y-%m-%d").date()
                except Exception:
                    continue
            if d < today or d > cutoff:
                continue
            expiries.append((d, d.strftime("%y%m%d")))
        expiries.sort(key=lambda x: x[0])
        for d, expiry_yyyymmdd in expiries:
            if len(symbols) >= max_symbols:
                break
            try:
                chain_resp = ctx.option_chain_info_by_date(symbol, d)
            except Exception:
                continue
            for strike_info in chain_resp:
                if strike_info.call_symbol:
                    symbols.append(strike_info.call_symbol)
                if strike_info.put_symbol:
                    symbols.append(strike_info.put_symbol)
                if len(symbols) >= max_symbols:
                    break
        logger.info("长桥已拉取 SPY 期权合约数量: %s（%s 天内到期）", len(symbols), expiry_days)
    except Exception as e:
        logger.warning("长桥拉取 SPY 期权列表失败: %s", e)
    return symbols


def run_longport_poll(
    min_contracts: int,
    min_premium_usd: float,
    expiry_days: int,
    poll_interval: float,
) -> None:
    """长桥轮询：用 option_quote 拉取成交量，对比相邻两次的增量作为大单。"""
    ctx = _get_longport_quote_ctx()
    if ctx is None:
        logger.error("长桥未配置或初始化失败，请检查 .env 中 LONGPORT_PAPER_* 或 LONGPORT_REAL_*")
        return
    symbols = fetch_spy_option_symbols_longport(expiry_days, max_symbols=500)
    if not symbols:
        logger.warning("未获取到 SPY 期权合约，请确认长桥行情权限包含美股期权")
        return
    logger.info(
        "SPY 期权大单监听（长桥轮询，每 %s 秒）。仅输出 权利金>=$%s 的增量。",
        poll_interval, min_premium_usd,
    )
    logger.info("等待大单…（仅成交量增量，无法区分买/卖方向，Ctrl+C 退出）")
    prev: Dict[str, float] = {}
    while True:
        try:
            resp = ctx.option_quote(symbols)
        except Exception as e:
            logger.warning("长桥 option_quote 失败: %s", e)
            time.sleep(poll_interval)
            continue
        now_ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
        for q in resp:
            sym = getattr(q, "symbol", None) or ""
            vol = int(getattr(q, "volume", 0) or 0)
            last_done = float(getattr(q, "last_done", 0) or 0)
            prev_vol = prev.get(sym, 0.0)
            delta = max(0, vol - prev_vol)
            prev[sym] = float(vol)
            if delta == 0:
                continue
            est_premium = last_done * delta * 100
            # 仅当权利金达到阈值才输出（避免仅因张数>=100 就输出小额单）
            if est_premium < min_premium_usd:
                continue
            # 解析长桥期权代码 如 SPY250321C00600000.US
            base = sym.replace(".US", "") if sym.endswith(".US") else sym
            parsed = _parse_yf_contract_symbol(base) if len(base) >= 15 else {"underlying": "SPY", "type": "?", "strike": 0}
            strike = getattr(getattr(q, "extend", None), "strike_price", None) if hasattr(q, "extend") and getattr(q, "extend", None) else None
            strike = float(strike) if strike is not None else parsed.get("strike", 0)
            expiry = parsed.get("expiry", "")
            if not expiry and len(base) >= 9:
                expiry = f"20{base[3:5]}-{base[5:7]}-{base[7:9]}"
            print(
                f"[大单] {parsed.get('underlying', 'SPY')} {expiry} {parsed.get('type', '?')} {strike:.0f} "
                f"| 增量张数={int(delta)} 权利金≈${est_premium:,.0f} @ {last_done:.2f} | {now_ts}"
            )
        time.sleep(poll_interval)


# --------------- Polygon WebSocket ---------------


async def run_polygon_ws(
    api_key: str,
    symbols: List[str],
    min_contracts: int,
    min_premium_usd: float,
) -> None:
    """Polygon WebSocket：认证、订阅、处理大单。"""
    if not websockets:
        logger.error("需要安装 websockets: pip install websockets")
        return
    if not symbols:
        logger.warning("无合约可订阅")
        return
    params = ",".join(f"T.{s}" for s in symbols[:1000])

    async def handler(ws: Any) -> None:
        await ws.send(json.dumps({"action": "auth", "params": api_key}))
        await ws.send(json.dumps({"action": "subscribe", "params": params}))
        logger.info("已订阅 %s 个 SPY 期权合约，过滤: 张数>=%s 或 权利金>=$%s", len(symbols), min_contracts, min_premium_usd)
        logger.info("等待大单推送（Ctrl+C 退出）…")
        while True:
            try:
                raw = await ws.recv()
            except Exception as e:
                logger.warning("recv 异常: %s", e)
                break
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue
            for m in (msg if isinstance(msg, list) else [msg]):
                line = format_polygon_trade(m, min_contracts, min_premium_usd)
                if line:
                    print(line)

    while True:
        try:
            async with websockets.connect(
                POLYGON_WS_OPTIONS_URL,
                ping_interval=20,
                ping_timeout=10,
                close_timeout=5,
            ) as ws:
                await handler(ws)
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.warning("WebSocket 断开，5 秒后重连: %s", e)
            await asyncio.sleep(5)


def main() -> int:
    _load_env()  # 仅用于 longport 的 LONGPORT_* 等主程序配置
    ap = argparse.ArgumentParser(description="SPY 期权大单实时监听（支持 yfinance / longport / polygon）")
    ap.add_argument("--source", choices=("yfinance", "longport", "polygon"), default="yfinance", help="数据源（默认 yfinance）")
    ap.add_argument("--polygon-api-key", type=str, default=None, help="Polygon API Key（仅 --source polygon 时必填）")
    ap.add_argument("--min-contracts", type=int, default=100, help="大单最小合约张数（默认 100）")
    ap.add_argument("--min-premium", type=float, default=50000, help="大单最小权利金/美元（默认 50000）")
    ap.add_argument("--expiry-days", type=int, default=45, help="只处理多少天内到期的合约（默认 45）")
    ap.add_argument("--poll-interval", type=float, default=60, help="yfinance/longport 轮询间隔/秒（默认 60）")
    args = ap.parse_args()

    source = args.source.strip().lower()
    min_contracts = args.min_contracts
    min_premium = args.min_premium
    expiry_days = args.expiry_days
    poll_interval = args.poll_interval

    if source == "polygon":
        api_key = (args.polygon_api_key or "").strip()
        if not api_key:
            logger.error("使用 --source polygon 时需传入 --polygon-api-key。可改用 --source yfinance 或 --source longport。")
            return 1
        symbols = fetch_spy_option_contracts_polygon(api_key, expiry_days=expiry_days)
        asyncio.run(run_polygon_ws(api_key, symbols, min_contracts, min_premium))
    elif source == "longport":
        run_longport_poll(min_contracts, min_premium, expiry_days, poll_interval)
    else:
        run_yfinance_poll(min_contracts, min_premium, expiry_days, poll_interval)
    return 0


if __name__ == "__main__":
    sys.exit(main())
