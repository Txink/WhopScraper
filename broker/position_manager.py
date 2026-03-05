"""
持仓管理模块
跟踪和管理期权持仓，计算盈亏，支持止损止盈。
支持从 broker 同步账户余额、期权持仓及交易记录；订单推送时更新本地持仓与交易记录。
"""
import re
from decimal import Decimal
from typing import Dict, List, Optional, Any
from datetime import datetime
from dataclasses import dataclass, asdict
import json
import logging

from rich.console import Console

from broker.order_formatter import print_position_update_display

logger = logging.getLogger(__name__)
console = Console()


def _make_json_serializable(obj: Any) -> Any:
    """递归将 Decimal 等转为 JSON 可序列化类型。"""
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, dict):
        return {k: _make_json_serializable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_make_json_serializable(v) for v in obj]
    return obj


def _is_filled(status: Any) -> bool:
    """订单状态是否为已成交（Filled）。"""
    if status is None:
        return False
    s = str(status).upper().split(".")[-1]
    return s == "FILLED"


def _parse_option_symbol(symbol: str) -> Optional[tuple]:
    """
    解析期权代码为 (ticker, expiry, option_type, strike)。
    格式：TICKER + YYMMDD + C/P + 行权价×1000.US
    """
    if not symbol or not symbol.endswith(".US") or len(symbol) < 12:
        return None
    base = symbol.replace(".US", "")
    m = re.match(r"^([A-Z]+)(\d{6})([CP])(\d+)$", base)
    if not m:
        return None
    ticker, expiry, opt, strike_str = m.groups()
    opt_type = "CALL" if opt == "C" else "PUT"
    try:
        strike = int(strike_str) / 1000.0
    except ValueError:
        return None
    return (ticker, expiry, opt_type, strike)


@dataclass
class Position:
    """持仓信息"""
    symbol: str                    # 期权代码
    ticker: str                    # 股票代码
    option_type: str               # CALL/PUT
    strike: float                  # 行权价
    expiry: str                    # 到期日
    quantity: int                  # 持仓数量
    available_quantity: int        # 可用数量
    avg_cost: float                # 平均成本
    current_price: float           # 当前价格
    market_value: float            # 市值
    unrealized_pnl: float          # 未实现盈亏
    unrealized_pnl_pct: float      # 盈亏百分比
    
    # 风控参数
    stop_loss_price: Optional[float] = None      # 止损价
    take_profit_price: Optional[float] = None    # 止盈价
    
    # 开仓信息
    open_time: Optional[str] = None              # 开仓时间
    order_id: Optional[str] = None               # 订单 ID
    
    # 更新时间
    updated_at: Optional[str] = None
    
    def to_dict(self) -> dict:
        """转换为字典"""
        return asdict(self)
    
    def calculate_pnl(self, current_price: float = None, multiplier: int = 100):
        """
        计算盈亏
        
        Args:
            current_price: 当前价格（可选，默认使用对象的 current_price）
            multiplier: 合约乘数，期权 100（1 张=100 股），股票 1
        """
        if current_price:
            self.current_price = current_price
        if getattr(self, "option_type", "") == "STOCK":
            multiplier = 1
        # 计算市值和盈亏
        self.market_value = self.current_price * self.quantity * multiplier
        cost = self.avg_cost * self.quantity * multiplier
        self.unrealized_pnl = self.market_value - cost
        if cost > 0:
            self.unrealized_pnl_pct = (self.unrealized_pnl / cost) * 100
        else:
            self.unrealized_pnl_pct = 0.0
        self.updated_at = datetime.now().isoformat()
    
    def should_stop_loss(self) -> bool:
        """是否触发止损"""
        if self.stop_loss_price is None:
            return False
        return self.current_price <= self.stop_loss_price
    
    def should_take_profit(self) -> bool:
        """是否触发止盈"""
        if self.take_profit_price is None:
            return False
        return self.current_price >= self.take_profit_price
    
    def set_stop_loss(self, price: float):
        """设置止损价"""
        self.stop_loss_price = price
        logger.info(f"设置止损: {self.symbol} @ {price}")
    
    def set_take_profit(self, price: float):
        """设置止盈价"""
        self.take_profit_price = price
        logger.info(f"设置止盈: {self.symbol} @ {price}")
    
    def adjust_stop_loss(self, new_price: float):
        """调整止损价（移动止损）"""
        old_price = self.stop_loss_price
        self.stop_loss_price = new_price
        logger.info(f"调整止损: {self.symbol} {old_price} → {new_price}")


def _is_stock_symbol(symbol: str) -> bool:
    """是否为股票代码（非期权）。期权格式如 AAPL251220C150000.US，股票如 AAPL.US。"""
    return bool(symbol) and symbol.endswith(".US") and _parse_option_symbol(symbol) is None


class PositionManager:
    """持仓管理器"""
    
    def __init__(self, storage_file: str = "data/positions.json", is_stock_mode: bool = False):
        """
        初始化持仓管理器
        
        Args:
            storage_file: 持仓数据存储文件
            is_stock_mode: True 表示当前监控股票页，同步并展示股票持仓（股、总价=数量×单价）；False 为期权页（张、×100）
        """
        self.storage_file = storage_file
        self.is_stock_mode = is_stock_mode
        self.positions: Dict[str, Position] = {}
        self.account_balance: Optional[Dict[str, Any]] = None
        self.trade_records: Dict[str, List[Dict[str, Any]]] = {}  # symbol -> list of order/execution records
        self.last_sync_stats: Dict[str, Any] = {}  # 最近一次 sync_from_broker 的统计信息
        if is_stock_mode:
            self._trade_records_file = "data/stock_trade_records.json"
        else:
            self._trade_records_file = storage_file.replace("positions.json", "trade_records.json") if "positions.json" in storage_file else "data/trade_records.json"
        self._load_positions()
        self._load_trade_records()
    
    def _load_trade_records(self):
        """从文件加载交易记录"""
        try:
            import os
            if os.path.exists(self._trade_records_file):
                with open(self._trade_records_file, "r", encoding="utf-8") as f:
                    self.trade_records = json.load(f)
                logger.debug(f"加载交易记录: {sum(len(v) for v in self.trade_records.values())} 条")
        except Exception as e:
            logger.warning(f"加载交易记录失败: {e}")
            self.trade_records = {}
    
    def _save_trade_records(self):
        """保存交易记录到文件"""
        try:
            import os
            os.makedirs(os.path.dirname(self._trade_records_file), exist_ok=True)
            with open(self._trade_records_file, "w", encoding="utf-8") as f:
                json.dump(_make_json_serializable(self.trade_records), f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.warning(f"保存交易记录失败: {e}")
    
    def _load_positions(self):
        """从文件加载持仓"""
        try:
            import os
            if os.path.exists(self.storage_file):
                with open(self.storage_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    for symbol, pos_data in data.items():
                        self.positions[symbol] = Position(**pos_data)
                logger.debug(f"加载持仓: {len(self.positions)} 个")
        except Exception as e:
            logger.error(f"加载持仓失败: {e}")
    
    def _save_positions(self):
        """保存持仓到文件"""
        try:
            import os
            os.makedirs(os.path.dirname(self.storage_file), exist_ok=True)
            
            data = {symbol: pos.to_dict() for symbol, pos in self.positions.items()}

            with open(self.storage_file, 'w', encoding='utf-8') as f:
                json.dump(_make_json_serializable(data), f, indent=2, ensure_ascii=False)
            
            logger.debug(f"保存持仓: {len(self.positions)} 个")
        except Exception as e:
            logger.error(f"保存持仓失败: {e}")
    
    def add_position(self, position: Position):
        """
        添加持仓
        
        Args:
            position: 持仓对象
        """
        self.positions[position.symbol] = position
        self._save_positions()
    
    def update_position(self, symbol: str, **kwargs):
        """
        更新持仓信息
        
        Args:
            symbol: 期权代码
            **kwargs: 要更新的字段
        """
        if symbol not in self.positions:
            logger.warning(f"持仓不存在: {symbol}")
            return
        
        position = self.positions[symbol]
        for key, value in kwargs.items():
            if hasattr(position, key):
                setattr(position, key, value)
        
        position.updated_at = datetime.now().isoformat()
        self._save_positions()
        logger.debug(f"更新持仓: {symbol}")
    
    def sync_from_broker(self, broker: Any, full_refresh: bool = False,
                         config_lines: Optional[List[str]] = None) -> None:
        """
        从券商同步：账户余额、持仓及交易记录。
        股票页（is_stock_mode=True）：同步股票持仓，总价=数量×单价（不乘 100）。
        期权页：同步期权持仓，总价=数量×单价×100（1 张=100 股）。

        Args:
            broker: 具备 get_account_balance()、get_positions()、get_today_orders() 的 broker 实例
            full_refresh: 为 True 时清空本地交易记录并从 API 完整重建（适合股票模式启动时校正）
        """
        self.last_sync_stats = {}
        try:
            self.account_balance = broker.get_account_balance()
            broker_positions = broker.get_positions()
            orders = broker.get_today_orders()
        except Exception as e:
            logger.warning(f"同步账户数据失败: {e}")
            return
        if not broker_positions:
            broker_positions = []
        multiplier = 1 if self.is_stock_mode else 100
        if self.is_stock_mode:
            relevant_positions = [p for p in broker_positions if _is_stock_symbol(p.get("symbol") or "")]
        else:
            relevant_positions = [p for p in broker_positions if _parse_option_symbol(p.get("symbol") or "")]
        for p in relevant_positions:
            symbol = p["symbol"]
            qty = int(float(p.get("quantity", 0)))
            avail = int(float(p.get("available_quantity", qty)))
            cost = float(p.get("cost_price", 0))
            if self.is_stock_mode:
                ticker = symbol.replace(".US", "") if symbol else ""
                option_type, strike, expiry = "STOCK", 0.0, ""
            else:
                parsed = _parse_option_symbol(symbol)
                if not parsed:
                    continue
                ticker, expiry, option_type, strike = parsed
            if symbol in self.positions:
                pos = self.positions[symbol]
                pos.quantity = qty
                pos.available_quantity = avail
                pos.avg_cost = cost
                pos.current_price = cost
                pos.calculate_pnl(multiplier=multiplier)
            else:
                pos = Position(
                    symbol=symbol,
                    ticker=ticker,
                    option_type=option_type,
                    strike=strike,
                    expiry=expiry,
                    quantity=qty,
                    available_quantity=avail,
                    avg_cost=cost,
                    current_price=cost,
                    market_value=cost * qty * multiplier,
                    unrealized_pnl=0.0,
                    unrealized_pnl_pct=0.0,
                    updated_at=datetime.now().isoformat(),
                )
                self.positions[symbol] = pos
        for symbol in list(self.positions.keys()):
            if not any(p.get("symbol") == symbol for p in relevant_positions):
                del self.positions[symbol]
        def _symbol_relevant(s: str) -> bool:
            return _is_stock_symbol(s) if self.is_stock_mode else bool(_parse_option_symbol(s))
        relevant_symbols = set(self.positions.keys())
        for o in orders or []:
            sym = o.get("symbol")
            if sym and sym not in relevant_symbols and _symbol_relevant(sym):
                relevant_symbols.add(sym)

        if full_refresh:
            # 完整刷新：清空全部本地记录（含旧期权记录），后续从 API 重建
            logger.debug("full_refresh=True：清空全部本地交易记录，将从 API 完整重建")
            self.trade_records = {}
            existing_order_ids: dict = {}
        else:
            # 增量模式：保留已有记录，只合并新增 Filled 订单（按 order_id 去重）
            for sym in relevant_symbols:
                self.trade_records.setdefault(sym, [])
            existing_order_ids = {
                sym: {str(r.get("order_id")) for r in self.trade_records.get(sym, [])}
                for sym in relevant_symbols
            }

        for o in orders or []:
            sym = o.get("symbol")
            if sym not in relevant_symbols:
                continue
            if not _is_filled(o.get("status")):
                continue
            oid = o.get("order_id")
            if oid and str(oid) in existing_order_ids.get(sym, set()):
                continue
            rec = {
                "order_id": oid,
                "symbol": sym,
                "side": o.get("side"),
                "quantity": o.get("quantity"),
                "executed_quantity": o.get("executed_quantity"),
                "price": o.get("price"),
                "status": o.get("status"),
                "submitted_at": o.get("submitted_at"),
            }
            self.trade_records.setdefault(sym, []).append(rec)
            if oid:
                existing_order_ids.setdefault(sym, set()).add(str(oid))

        # 从券商历史 Filled 订单重建/补全交易记录
        # full_refresh 时查 365 天完整校正；增量时查 90 天补全缺漏
        history_days = 365 if full_refresh else 90
        get_history = getattr(broker, "get_history_orders", None)
        if callable(get_history):
            try:
                from datetime import timedelta
                end_at = datetime.now()
                start_at = end_at - timedelta(days=history_days)
                logger.debug(f"从 API 拉取历史订单（最近 {history_days} 天）…")
                history_orders = get_history(start_at, end_at)
                for o in history_orders or []:
                    sym = o.get("symbol")
                    if not sym or sym not in relevant_symbols:
                        continue
                    self.trade_records.setdefault(sym, [])
                    if not _is_filled(o.get("status")):
                        continue
                    oid = o.get("order_id")
                    if oid and str(oid) in existing_order_ids.get(sym, set()):
                        continue
                    rec = {
                        "order_id": oid,
                        "symbol": sym,
                        "side": o.get("side"),
                        "quantity": o.get("quantity"),
                        "executed_quantity": o.get("executed_quantity"),
                        "price": o.get("price"),
                        "status": o.get("status"),
                        "submitted_at": o.get("submitted_at"),
                    }
                    self.trade_records.setdefault(sym, []).append(rec)
                    if oid:
                        existing_order_ids.setdefault(sym, set()).add(str(oid))
                # 按时间升序排序
                for sym in self.trade_records:
                    self.trade_records[sym].sort(
                        key=lambda r: r.get("submitted_at") or ""
                    )
                if full_refresh:
                    total = sum(len(v) for v in self.trade_records.values())
                    self.last_sync_stats["trade_records_rebuilt"] = total
            except Exception as e:
                logger.warning(f"{'完整重建' if full_refresh else '回填'}历史订单失败: {e}")
        # 清理非持仓 symbol 的交易记录（本地文件可能残留旧数据）
        stale_symbols = [s for s in self.trade_records if s not in relevant_symbols]
        for s in stale_symbols:
            del self.trade_records[s]

        self._save_positions()
        self._save_trade_records()
        self._log_sync_summary(config_lines=config_lines)

    def on_order_push(self, event: Any, broker: Any) -> None:
        """
        订单状态推送时更新本地：记录该笔订单到交易记录，若已成交则刷新该 symbol 的持仓。
        
        Args:
            event: 长桥 PushOrderChanged 事件，需有 symbol, order_id, side, status, submitted_quantity, executed_quantity, submitted_price, submitted_at 等属性
            broker: 用于刷新持仓（get_positions）
        """
        symbol = getattr(event, "symbol", None) or ""
        if not symbol:
            return
        status = getattr(event, "status", None)
        status_name = (getattr(status, "name", "") or "").upper() if status else ""
        if not status_name and hasattr(event, "status"):
            status_name = str(getattr(event, "status", "")).upper().split(".")[-1]
        order_id = getattr(event, "order_id", "")
        side = getattr(event, "side", None)
        side_str = getattr(side, "name", str(side)) if side else ""
        qty = int(getattr(event, "submitted_quantity", 0) or 0)
        executed = int(getattr(event, "executed_quantity", 0) or 0)
        price = getattr(event, "submitted_price", None)
        if price is not None:
            price = float(price)
        submitted_at = getattr(event, "submitted_at", None)
        if hasattr(submitted_at, "isoformat"):
            submitted_at = submitted_at.isoformat()

        # 卖出成交时在更新持仓前计算本次利润，供订单推送表格展示
        realized_profit = None
        if status_name == "FILLED" and "SELL" in (side_str or "").upper() and price is not None:
            pos_before = self.positions.get(symbol)
            if pos_before and executed > 0:
                mult = 1 if _is_stock_symbol(symbol) else 100
                realized_profit = round((price - pos_before.avg_cost) * executed * mult, 2)

        if status_name == "FILLED":
            rec = {
                "order_id": order_id,
                "symbol": symbol,
                "side": side_str,
                "quantity": qty,
                "executed_quantity": executed,
                "price": price,
                "status": status_name or str(status),
                "submitted_at": submitted_at,
            }
            self.trade_records.setdefault(symbol, []).append(rec)
            self._save_trade_records()
            try:
                # 等待券商系统更新持仓数据，避免查到旧数据
                import time
                time.sleep(0.5)
                positions = broker.get_positions()
                found_in_broker = False
                for p in positions or []:
                    if (p.get("symbol") or "") == symbol:
                        found_in_broker = True
                        qty_b = int(float(p.get("quantity", 0)))
                        avail_b = int(float(p.get("available_quantity", qty_b)))
                        cost_b = float(p.get("cost_price", 0))
                        if qty_b <= 0:
                            self.remove_position(symbol)
                        elif symbol in self.positions:
                            self.update_position(symbol, quantity=qty_b, available_quantity=avail_b, avg_cost=cost_b)
                            mult = 1 if self.is_stock_mode else 100
                            self.positions[symbol].calculate_pnl(cost_b, multiplier=mult)
                        else:
                            # 解析期权代码；正股则用简单默认值
                            parsed = _parse_option_symbol(symbol)
                            is_stock = self.is_stock_mode and _is_stock_symbol(symbol)
                            mult = 1 if is_stock else 100
                            if parsed:
                                ticker, expiry, option_type, strike = parsed
                            else:
                                ticker = symbol.replace(".US", "")
                                expiry, option_type, strike = "", "STOCK", 0.0
                            pos = Position(
                                symbol=symbol,
                                ticker=ticker,
                                option_type=option_type,
                                strike=strike,
                                expiry=expiry,
                                quantity=qty_b,
                                available_quantity=avail_b,
                                avg_cost=cost_b,
                                current_price=cost_b,
                                market_value=cost_b * qty_b * mult,
                                unrealized_pnl=0.0,
                                unrealized_pnl_pct=0.0,
                                updated_at=datetime.now().isoformat(),
                            )
                            self.add_position(pos)
                        break
                if not found_in_broker and symbol in self.positions:
                    self.remove_position(symbol)
            except Exception as e:
                logger.warning(f"订单推送后刷新持仓失败: {e}")
            # 卖出利润写入 logger，供订单推送阶段展示
            if order_id and realized_profit is not None:
                from utils.rich_logger import get_logger
                rlog = get_logger()
                if rlog.is_order_in_flow(order_id):
                    rlog.set_pending_order_profit(order_id, realized_profit)
            # 输出 [持仓更新] 日志：若该 order 在交易流程中则并入同一表格，否则独立打印
            self._log_position_update(symbol, side_str, broker, order_id=str(order_id) if order_id else None)

    def _log_position_update(self, symbol: str, side_str: str, broker: Any = None, order_id: Optional[str] = None) -> None:
        """订单成交后输出该 symbol 的持仓表格。若提供 order_id 且该订单在交易流程中，则仅写入 pending 供同一表格合并展示。"""
        from utils.rich_logger import get_logger
        rlogger = get_logger()

        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        pos = self.positions.get(symbol)
        is_stock = pos and getattr(pos, "option_type", "") == "STOCK"
        mult = 1 if is_stock else 100
        unit = "股" if is_stock else "张"
        total_assets = 0.0
        if self.account_balance is not None:
            total_assets = float(self.account_balance.get("net_assets") or 0)
        if total_assets == 0:
            available_cash = float(self.account_balance.get("available_cash") or 0) if self.account_balance else 0.0
            total_position_value = sum(
                p.quantity * p.avg_cost * (1 if getattr(p, "option_type", "") == "STOCK" else 100)
                for p in self.positions.values()
            )
            total_assets = available_cash + total_position_value

        action = "买入" if "Buy" in side_str else "卖出"
        title = (
            f"[grey70]{ts}[/grey70] [bold magenta]\\[持仓更新][/bold magenta] "
            f"{action}成交后 [bold]{symbol}[/bold]"
        )

        positions_data = []
        if pos:
            position_value = pos.quantity * pos.avg_cost * mult
            pct = (position_value / total_assets * 100) if total_assets > 0 else 0

            records = []
            if broker:
                try:
                    all_orders = broker.get_today_orders()
                    for order in all_orders:
                        if order.get("symbol") == symbol and "filled" in str(order.get("status", "")).lower():
                            records.append(order)
                except Exception:
                    pass
            if not records:
                records = self.trade_records.get(symbol, [])

            norm_records = [
                self._normalize_record(r, ts)
                for r in sorted(records, key=lambda r: r.get("submitted_at") or "")
            ]
            row = {
                "symbol": symbol,
                "quantity": pos.quantity,
                "unit": unit,
                "avg_cost": pos.avg_cost,
                "position_value": position_value,
                "pct": pct,
                "stop_loss": getattr(pos, "stop_loss_price", None) or None,
                "records": norm_records,
            }
            if is_stock:
                raw_records = self.trade_records.get(symbol, [])
                if raw_records:
                    t_result = self._analyze_t_trades(raw_records)
                    unmatched = t_result.get("unmatched", [])
                    if unmatched:
                        row["t_unmatched_buys"] = unmatched
                        uq = sum(u["remaining_qty"] for u in unmatched)
                        row["t_unmatched_qty"] = uq
                        row["t_weighted_avg"] = (
                            sum(u["price"] * u["remaining_qty"] for u in unmatched) / uq
                            if uq else 0
                        )
            positions_data.append(row)
        else:
            positions_data.append({
                "symbol": symbol,
                "quantity": 0,
                "unit": unit,
                "avg_cost": 0.0,
                "position_value": 0.0,
                "pct": 0.0,
                "records": [],
            })

        if order_id and rlogger.is_order_in_flow(order_id):
            rlogger.set_pending_position_stage(order_id, positions_data)
            return
        rlogger.print_position_table(title, positions_data)

    def _print_longbridge_data_summary(self, full_refresh: bool = False) -> None:
        """启动时在 [账户持仓] 之前，打印所有长桥 API 调用动作的汇总 [长桥数据]。"""
        from broker.order_formatter import print_longbridge_data_display
        lines = []

        # 账户信息 (account_balance)
        if self.account_balance is not None:
            available = float(self.account_balance.get("available_cash") or 0)
            net = float(self.account_balance.get("net_assets") or 0)
            lines.append(f"调用 account_balance 获取账户信息：可用现金 ${available:,.2f}，总资产 ${net:,.2f}")

        # 持仓 (stock_positions) — 展示所有持仓
        pos_count = len(self.positions)
        lines.append(f"调用 stock_positions 获取{'股票' if self.is_stock_mode else '期权'}持仓：{pos_count} 个持仓")
        for sym in sorted(self.positions.keys()):
            ticker = sym.replace(".US", "")
            pos = self.positions[sym]
            qty = getattr(pos, "quantity", 0)
            lines.append(f"  - {ticker}（{qty} {'股' if self.is_stock_mode else '张'}）")

        # 交易记录 (history_orders) — 股票模式只展示纯股票代码（过滤期权）
        if self.is_stock_mode:
            record_symbols = sorted(s for s in self.trade_records if _is_stock_symbol(s))
        else:
            record_symbols = sorted(self.trade_records.keys())
        sym_count = len(record_symbols)
        rebuilt = self.last_sync_stats.get("trade_records_rebuilt")
        if rebuilt is not None:
            lines.append(f"调用 history_orders 获取交易记录：{sym_count} 个股票；更新本地交易记录（重建 {rebuilt} 条，最近 365 天）")
        else:
            total = sum(len(v) for v in self.trade_records.values())
            lines.append(f"调用 history_orders 获取交易记录：{sym_count} 个股票；更新本地交易记录（增量同步，共 {total} 条）")
        for sym in record_symbols:
            ticker = sym.replace(".US", "")
            count = len(self.trade_records[sym])
            lines.append(f"  - {ticker}（{count} 条）")

        print_longbridge_data_display(lines)

    @staticmethod
    def _normalize_record(rec: dict, fallback_ts: str = "") -> dict:
        """将原始交易记录转为 print_position_table 所需格式。"""
        rec_ts = rec.get("submitted_at") or fallback_ts
        if isinstance(rec_ts, str) and "T" in rec_ts:
            rec_ts = rec_ts.replace("T", " ")[:19]
            if len(rec_ts) == 19 and "." not in rec_ts:
                rec_ts = rec_ts + ".000"
        side_raw = rec.get("side", "")
        side = ("BUY" if "Buy" in (side_raw or "")
                else ("SELL" if "Sell" in (side_raw or "")
                      else (side_raw or "").upper()))
        if side not in ("BUY", "SELL"):
            side = "BUY"
        qty = int(float(rec.get("executed_quantity") or rec.get("quantity") or 0))
        price = rec.get("price")
        if price is None:
            price_str = "-"
        elif isinstance(price, (int, float)) and price == int(price):
            price_str = f"{int(price)}"
        else:
            price_str = f"{price}"
        return {"submitted_at": rec_ts, "side": side, "qty": qty, "price": price_str}

    def _log_sync_summary(self, config_lines: Optional[List[str]] = None) -> None:
        """同步完成后输出账户信息表格 + 持仓表格。"""
        from utils.rich_logger import get_logger
        rlogger = get_logger()

        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        available_cash = 0.0
        cash = 0.0
        total_assets = 0.0
        is_paper = True
        if self.account_balance is not None:
            available_cash = float(self.account_balance.get("available_cash") or 0)
            cash = float(self.account_balance.get("cash") or 0)
            total_assets = float(self.account_balance.get("net_assets") or 0)
            is_paper = self.account_balance.get("mode", "paper") == "paper"
        if total_assets == 0:
            total_position_value = sum(
                p.quantity * p.avg_cost * (1 if getattr(p, "option_type", "") == "STOCK" else 100)
                for p in self.positions.values()
            )
            total_assets = available_cash + total_position_value

        watched: set = None
        if self.is_stock_mode:
            try:
                from utils.watched_stocks import get_watched_tickers
                watched = {f"{t}.US" for t in get_watched_tickers()}
            except Exception:
                watched = None

        symbols = sorted(
            sym for sym in self.positions.keys()
            if self.positions[sym].quantity > 0
        )

        account = {
            "available_cash": available_cash,
            "cash": cash,
            "total_assets": total_assets,
            "is_paper": is_paper,
        }

        positions_data = []
        for sym in symbols:
            pos = self.positions[sym]
            is_stock = getattr(pos, "option_type", "") == "STOCK"
            mult = 1 if is_stock else 100
            unit = "股" if is_stock else "张"
            position_value = pos.quantity * pos.avg_cost * mult
            pct = (position_value / total_assets * 100) if total_assets > 0 else 0
            is_watched = (watched is None or sym in watched)
            records = self.trade_records.get(sym, []) if is_watched else []
            norm_records = [
                self._normalize_record(r, ts)
                for r in sorted(records, key=lambda r: r.get("submitted_at") or "")
            ]
            row = {
                "symbol": sym,
                "quantity": pos.quantity,
                "unit": unit,
                "avg_cost": pos.avg_cost,
                "position_value": position_value,
                "pct": pct,
                "stop_loss": getattr(pos, "stop_loss_price", None) or None,
                "records": norm_records,
            }
            if is_stock and records:
                t_result = self._analyze_t_trades(records)
                unmatched = t_result.get("unmatched", [])
                if unmatched:
                    row["t_unmatched_buys"] = unmatched
                    uq = sum(u["remaining_qty"] for u in unmatched)
                    row["t_unmatched_qty"] = uq
                    row["t_weighted_avg"] = (
                        sum(u["price"] * u["remaining_qty"] for u in unmatched) / uq
                        if uq else 0
                    )
            positions_data.append(row)

        rlogger.print_position_table(
            None, positions_data, account=account, config_lines=config_lines,
        )
    
    # ──────────────── T 交易分析（股票模式） ────────────────

    @staticmethod
    def _analyze_t_trades(trades: List[Dict]) -> Dict:
        """
        计算哪些买入批次尚未被 T 出。
        卖出时按买入价从高到低匹配（优先消掉高成本仓位）；超额卖出记入缓冲，
        后续出现更低买入价时逆向消除。
        """
        def _q(v):
            try:
                return int(float(v or 0))
            except Exception:
                return 0

        def _p(v):
            try:
                return float(v or 0)
            except Exception:
                return 0.0

        trades = sorted(trades, key=lambda t: t.get("submitted_at") or "")
        open_buys: List[Dict] = []   # 未匹配买入 {ts, price, original_qty, remaining_qty}
        excess_sells: List[Dict] = []  # 超额卖出缓冲
        total_matched_qty = 0
        total_profit = 0.0

        for trade in trades:
            side  = (trade.get("side") or "").upper()
            qty   = _q(trade.get("executed_quantity") or trade.get("quantity"))
            price = _p(trade.get("price"))
            ts    = trade.get("submitted_at") or ""
            if qty <= 0 or price <= 0:
                continue

            if side == "BUY":
                remaining = qty
                new_excess = []
                for es in excess_sells:
                    if es["price"] > price and remaining > 0:
                        mq = min(remaining, es["remaining_qty"])
                        total_matched_qty += mq
                        total_profit += round((es["price"] - price) * mq, 2)
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
                for lot in sorted(open_buys, key=lambda x: (-x["price"], x["ts"])):
                    if lot["remaining_qty"] > 0 and lot["price"] < price and remaining > 0:
                        mq = min(remaining, lot["remaining_qty"])
                        total_matched_qty += mq
                        total_profit += round((price - lot["price"]) * mq, 2)
                        lot["remaining_qty"] -= mq
                        remaining -= mq
                if remaining > 0:
                    excess_sells.append({"ts": ts, "price": price, "remaining_qty": remaining})

        unmatched = [lot for lot in open_buys if lot["remaining_qty"] > 0]
        return {
            "unmatched": unmatched,
            "excess_sells": excess_sells,   # 超额卖出：已高价卖出，等待更低价买入对消
            "total_matched_qty": total_matched_qty,
            "total_profit": total_profit,
        }

    def _print_t_analysis_summary(self) -> None:
        """启动时在 [仓位分析] 标题下输出各股票待 T 出的批次。"""
        ts_now = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        try:
            from utils.watched_stocks import get_watched_tickers
            watched = {f"{t}.US" for t in get_watched_tickers()}
        except Exception:
            watched = set()

        symbols = sorted(
            sym for sym in self.trade_records
            if sym in watched and self.trade_records[sym]
        )
        if not symbols:
            return

        console.print(
            f"[grey70]{ts_now}[/grey70] [bold magenta][仓位分析][/bold magenta]"
        )
        indent = "    "
        for sym in symbols:
            trades = self.trade_records[sym]
            result = self._analyze_t_trades(trades)
            unmatched     = result["unmatched"]
            excess_sells  = result["excess_sells"]
            total_matched = result["total_matched_qty"]
            total_profit  = result["total_profit"]

            unmatched_qty = sum(u["remaining_qty"] for u in unmatched)
            excess_qty    = sum(e["remaining_qty"] for e in excess_sells)
            unmatched_cost = (
                sum(u["price"] * u["remaining_qty"] for u in unmatched) / unmatched_qty
                if unmatched_qty else 0
            )

            if unmatched_qty == 0 and excess_qty == 0:
                console.print(
                    f"{indent}[bold]{sym}[/bold]  "
                    f"[green]✅ 无待T仓位[/green]  "
                    f"已T出 {total_matched} 股 利润 [green]+${total_profit:,.2f}[/green]"
                )
                continue

            console.print(
                f"{indent}[bold]{sym}[/bold]  "
                f"[yellow]待T: {unmatched_qty} 股  加权均价 ${unmatched_cost:.2f}[/yellow]  "
                f"已T出 {total_matched} 股 利润 [green]+${total_profit:,.2f}[/green]"
            )
            for lot in sorted(unmatched, key=lambda x: x["ts"]):
                orig = lot["original_qty"]
                rem  = lot["remaining_qty"]
                tded = orig - rem
                ts_short = lot["ts"].replace("T", " ")[:16] if lot["ts"] else "-"
                already = f"  [dim](已T {tded}股)[/dim]" if tded > 0 else ""
                console.print(
                    f"{indent}    - [grey70]{ts_short}[/grey70]  "
                    f"[yellow]${lot['price']:.2f}[/yellow] × "
                    f"[bold]{rem}股[/bold]{already}"
                )
            # 超额卖出：已高价卖出但尚无对应低价买入，待未来低价买入时对消
            if excess_sells:
                for es in sorted(excess_sells, key=lambda x: x["ts"]):
                    ts_short = es["ts"].replace("T", " ")[:16] if es["ts"] else "-"
                    console.print(
                        f"{indent}    ~ [grey70]{ts_short}[/grey70]  "
                        f"[red]卖出 ${es['price']:.2f}[/red] × "
                        f"[bold]{es['remaining_qty']}股[/bold]  [dim]待低价买入对消[/dim]"
                    )
        console.print()

    def remove_position(self, symbol: str):
        """
        移除持仓（已全部平仓）

        Args:
            symbol: 期权代码
        """
        if symbol in self.positions:
            del self.positions[symbol]
            self._save_positions()
    
    def get_position(self, symbol: str) -> Optional[Position]:
        """
        获取持仓
        
        Args:
            symbol: 期权代码
        
        Returns:
            Position 对象或 None
        """
        return self.positions.get(symbol)
    
    def get_all_positions(self) -> List[Position]:
        """获取所有持仓"""
        return list(self.positions.values())
    
    def get_total_buy_quantity(self, symbol: str) -> int:
        """
        获取该期权所有买入数量（从 trade_records 汇总所有 BUY 的成交数量）。
        用于卖出比例（如 1/3、1/2）的分母：比例相对「该期权历史上所有买入」而非当前持仓。
        
        Args:
            symbol: 期权代码
        
        Returns:
            该期权所有买入的成交数量之和，无记录时返回 0
        """
        records = self.trade_records.get(symbol, [])
        total = 0
        for rec in records:
            if (rec.get("side") or "").upper() != "BUY":
                continue
            q = rec.get("executed_quantity") or rec.get("quantity") or 0
            total += int(float(q))
        return total
    
    def sync_positions_from_broker(self, broker_positions: List[dict]):
        """
        从券商同步持仓
        
        Args:
            broker_positions: 券商返回的持仓列表
        """
        logger.info(f"同步持仓: {len(broker_positions)} 个")
        
        # 券商持仓的 symbol 集合
        broker_symbols = set()
        
        for pos_data in broker_positions:
            symbol = pos_data['symbol']
            broker_symbols.add(symbol)
            
            # 如果本地已有持仓，更新数量和价格
            if symbol in self.positions:
                position = self.positions[symbol]
                position.quantity = pos_data.get('quantity', position.quantity)
                position.available_quantity = pos_data.get('available_quantity', position.available_quantity)
                position.avg_cost = pos_data.get('cost_price', position.avg_cost)
                position.market_value = pos_data.get('market_value', position.market_value)
                position.calculate_pnl()
            else:
                # 新持仓（可能是手动交易或其他渠道）
                logger.warning(f"发现新持仓（未在本地记录）: {symbol}")
                # 这里可以选择添加或忽略
        
        # 移除券商已平仓但本地还保留的持仓
        local_symbols = set(self.positions.keys())
        closed_symbols = local_symbols - broker_symbols
        
        for symbol in closed_symbols:
            logger.info(f"检测到已平仓: {symbol}")
            # 可以选择移除或标记为已平仓
            # self.remove_position(symbol)
        
        self._save_positions()
    
    def update_prices(self, price_updates: Dict[str, float]):
        """
        批量更新持仓价格
        
        Args:
            price_updates: {symbol: current_price} 字典
        """
        for symbol, price in price_updates.items():
            if symbol in self.positions:
                self.positions[symbol].calculate_pnl(price)
        
        self._save_positions()
    
    def check_alerts(self) -> List[Dict]:
        """
        检查止损止盈触发
        
        Returns:
            触发的警报列表
        """
        alerts = []
        
        for position in self.positions.values():
            if position.should_stop_loss():
                alerts.append({
                    'type': 'STOP_LOSS',
                    'symbol': position.symbol,
                    'current_price': position.current_price,
                    'trigger_price': position.stop_loss_price,
                    'pnl': position.unrealized_pnl,
                    'pnl_pct': position.unrealized_pnl_pct
                })
            
            if position.should_take_profit():
                alerts.append({
                    'type': 'TAKE_PROFIT',
                    'symbol': position.symbol,
                    'current_price': position.current_price,
                    'trigger_price': position.take_profit_price,
                    'pnl': position.unrealized_pnl,
                    'pnl_pct': position.unrealized_pnl_pct
                })
        
        return alerts
    
    def get_total_pnl(self) -> Dict[str, float]:
        """
        获取总盈亏
        
        Returns:
            {'unrealized_pnl': float, 'total_market_value': float}
        """
        total_pnl = 0.0
        total_market_value = 0.0
        
        for position in self.positions.values():
            total_pnl += position.unrealized_pnl
            total_market_value += position.market_value
        
        return {
            'unrealized_pnl': total_pnl,
            'total_market_value': total_market_value
        }
    
    def get_positions_by_ticker(self, ticker: str) -> List[Position]:
        """
        获取指定股票的所有期权持仓
        
        Args:
            ticker: 股票代码
        
        Returns:
            持仓列表
        """
        return [pos for pos in self.positions.values() if pos.ticker == ticker]
    
    def print_summary(self):
        """打印持仓摘要"""
        print("\n" + "=" * 80)
        print("持仓摘要")
        print("=" * 80)
        
        if not self.positions:
            print("当前无持仓")
            print("=" * 80 + "\n")
            return
        
        total_stats = self.get_total_pnl()
        
        print(f"持仓数量: {len(self.positions)}")
        print(f"总市值:   ${total_stats['total_market_value']:,.2f}")
        print(f"总盈亏:   ${total_stats['unrealized_pnl']:,.2f}")
        print("-" * 80)
        
        # 按盈亏排序
        sorted_positions = sorted(
            self.positions.values(),
            key=lambda x: x.unrealized_pnl_pct,
            reverse=True
        )
        
        for pos in sorted_positions:
            pnl_symbol = "🟢" if pos.unrealized_pnl >= 0 else "🔴"
            print(f"{pnl_symbol} {pos.symbol}")
            print(f"   数量: {pos.quantity} 张 | 成本: ${pos.avg_cost:.2f} | 现价: ${pos.current_price:.2f}")
            print(f"   盈亏: ${pos.unrealized_pnl:,.2f} ({pos.unrealized_pnl_pct:+.2f}%)")
            
            if pos.stop_loss_price:
                print(f"   止损: ${pos.stop_loss_price:.2f}")
            if pos.take_profit_price:
                print(f"   止盈: ${pos.take_profit_price:.2f}")
            print()
        
        print("=" * 80 + "\n")


def create_position_from_order(
    symbol: str,
    ticker: str,
    option_type: str,
    strike: float,
    expiry: str,
    quantity: int,
    avg_cost: float,
    order_id: str = None
) -> Position:
    """
    从订单创建持仓对象
    
    Args:
        symbol: 期权代码
        ticker: 股票代码
        option_type: CALL/PUT
        strike: 行权价
        expiry: 到期日
        quantity: 数量
        avg_cost: 平均成本
        order_id: 订单 ID
    
    Returns:
        Position 对象
    """
    return Position(
        symbol=symbol,
        ticker=ticker,
        option_type=option_type,
        strike=strike,
        expiry=expiry,
        quantity=quantity,
        available_quantity=quantity,
        avg_cost=avg_cost,
        current_price=avg_cost,  # 初始价格等于成本
        market_value=avg_cost * quantity * 100,
        unrealized_pnl=0.0,
        unrealized_pnl_pct=0.0,
        open_time=datetime.now().isoformat(),
        order_id=order_id,
        updated_at=datetime.now().isoformat()
    )


if __name__ == "__main__":
    # 测试持仓管理器
    import sys
    
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )
    
    # 创建管理器
    manager = PositionManager(storage_file="data/test_positions.json")
    
    # 添加测试持仓
    pos1 = create_position_from_order(
        symbol="AAPL250131C150000.US",
        ticker="AAPL",
        option_type="CALL",
        strike=150.0,
        expiry="2025-01-31",
        quantity=2,
        avg_cost=2.5,
        order_id="TEST001"
    )
    
    manager.add_position(pos1)
    
    # 更新价格
    pos1.calculate_pnl(3.0)  # 价格上涨到 3.0
    manager.update_position(pos1.symbol, current_price=3.0)
    
    # 设置止损止盈
    pos1.set_stop_loss(2.0)
    pos1.set_take_profit(4.0)
    
    # 打印摘要
    manager.print_summary()
    
    # 检查警报
    alerts = manager.check_alerts()
    if alerts:
        print("触发警报:")
        for alert in alerts:
            print(f"  {alert}")
    
    print("\n✅ 持仓管理器测试完成！")
