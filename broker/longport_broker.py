"""
长桥证券交易接口
支持模拟账户和真实账户，带风险控制和 dry_run 模式
"""
from decimal import Decimal
from typing import Dict, Optional, List
import io
import logging
import time
import os
import sys
from datetime import datetime

from longport.openapi import TradeContext, QuoteContext, Config, OrderSide, OrderType, TimeInForceType, OrderStatus, Market

from .config_loader import LongPortConfigLoader
from .order_formatter import (
    print_order_table,
    print_order_submitting_display,
    print_order_submitted_display,
    print_order_push_submitted_display,
    print_order_modify_table,
    print_order_cancel_table,
    print_orders_summary_table,
    print_account_info_table,
    print_positions_table,
    print_today_orders_table,
    print_success_message,
    print_error_message,
    print_warning_message,
    print_info_message,
    print_order_failed_table
)

logger = logging.getLogger(__name__)


class LongPortBroker:
    """长桥证券交易接口"""
    
    def __init__(self, config: Optional[Config] = None, config_loader: Optional[LongPortConfigLoader] = None):
        """
        初始化交易接口
        
        Args:
            config: 长桥配置对象（可选）
            config_loader: 配置加载器（可选）
        """
        if config_loader is None:
            config_loader = LongPortConfigLoader()
        
        self.config_loader = config_loader
        self.config = config or config_loader.get_config()
        # 先创建 QuoteContext 再 TradeContext，避免连接数达上限时先建 Trade 导致泄漏（因异常时未返回实例）
        # 创建 QuoteContext 时 SDK 会打印行情订阅表，临时屏蔽 stdout/stderr 以去掉该输出
        _old_stdout, _old_stderr = sys.stdout, sys.stderr
        try:
            sys.stdout = io.StringIO()
            sys.stderr = io.StringIO()
            self.quote_ctx = QuoteContext(self.config)  # 行情接口
        finally:
            sys.stdout = _old_stdout
            sys.stderr = _old_stderr
        self.ctx = TradeContext(self.config)
        self.positions: Dict[str, Dict] = {}  # 持仓跟踪

        # 模式标志
        self.dry_run = config_loader.is_dry_run()
        self.auto_trade = config_loader.is_auto_trade_enabled()
        self.is_paper = config_loader.is_paper_mode()
        self._quote_std_suppressed = False  # 仅首次行情请求时用 dup2 屏蔽 SDK 打印的订阅表

    def _with_fd_std_suppressed(self, func, *args, **kwargs):
        """在屏蔽 fd 1/2 的情况下执行 func，用于屏蔽长桥 SDK 直接写 fd 的行情订阅表。仅首次调用时执行屏蔽。"""
        if self._quote_std_suppressed:
            return func(*args, **kwargs)
        try:
            devnull = os.open(os.devnull, os.O_WRONLY)
            save_1, save_2 = os.dup(1), os.dup(2)
            os.dup2(devnull, 1)
            os.dup2(devnull, 2)
            os.close(devnull)
            try:
                return func(*args, **kwargs)
            finally:
                os.dup2(save_1, 1)
                os.dup2(save_2, 2)
                os.close(save_1)
                os.close(save_2)
        finally:
            self._quote_std_suppressed = True

    def close(self) -> None:
        """
        释放长桥连接（QuoteContext / TradeContext），便于连接数回收。
        程序退出时调用，调用后本实例不可再用于请求。
        """
        for name in ("quote_ctx", "ctx"):
            obj = getattr(self, name, None)
            if obj is None:
                continue
            try:
                if callable(getattr(obj, "close", None)):
                    obj.close()
            except Exception as e:
                logger.debug("关闭 %s 时忽略: %s", name, e)
            setattr(self, name, None)
        logger.debug("长桥连接已释放")

    def submit_option_order(
        self,
        symbol: str,
        side: str,  # "BUY" 或 "SELL"
        quantity: int,
        price: Optional[float] = None,
        order_type: str = "LIMIT",  # "LIMIT" 或 "MARKET"
        remark: str = "",
        trigger_price: Optional[float] = None,  # 触发价格（条件单）
        trailing_percent: Optional[float] = None,  # 跟踪止损百分比
        trailing_amount: Optional[float] = None,  # 跟踪止损金额
        instruction_timestamp: Optional[str] = None,  # 指令时间戳，用于提交订单展示的 time 与 [+Nms]
    ) -> Dict:
        """
        提交期权订单（支持止盈止损）
        
        Args:
            symbol: 期权代码，如 "EOSE260109C13500.US"
            side: 买卖方向 BUY/SELL
            quantity: 数量（合约数）
            price: 限价单价格（市价单传 None）
            order_type: 订单类型 LIMIT/MARKET
            remark: 订单备注
            trigger_price: 触发价格（条件单，用于止盈止损）
            trailing_percent: 跟踪止损百分比（如 5 表示 5%）
            trailing_amount: 跟踪止损金额
        
        Returns:
            订单信息字典
        """
        # 检查是否启用自动交易
        if not self.auto_trade:
            logger.warning("⚠️  自动交易未启用，跳过订单提交")
            return self._mock_order_response(symbol, side, quantity, price)
        
        # Dry run 模式
        if self.dry_run:
            logger.info(f"🧪 [DRY RUN] 模拟下单: {symbol} {side} {quantity} @ {price}")
            return self._mock_order_response(symbol, side, quantity, price)
        
        try:
            # 卖出时检查持仓（LIT 条件单不立即卖出，跳过持仓检查）
            if side.upper() == "SELL" and order_type.upper() != "LIT":
                if not self._check_position_for_sell(symbol, quantity):
                    raise ValueError(f"持仓不足: 无法卖出 {quantity} 张 {symbol}")    
            # 转换买卖方向
            order_side = OrderSide.Buy if side.upper() == "BUY" else OrderSide.Sell
            
            # 转换订单类型
            if order_type.upper() == "MARKET":
                o_type = OrderType.MO
                submitted_price = None
            elif order_type.upper() == "LIT":
                # 触价限价单（到价止损/止盈）
                o_type = OrderType.LIT
                if price is None:
                    raise ValueError("触价限价单必须提供限价")
                submitted_price = Decimal(str(price))
            else:
                o_type = OrderType.LO
                if price is None:
                    raise ValueError("限价单必须提供价格")
                submitted_price = Decimal(str(price))
            
            # LIT 订单使用 GoodTilCanceled（撤销前有效），其余用 Day
            tif = TimeInForceType.GoodTilCanceled if o_type == OrderType.LIT else TimeInForceType.Day

            # 准备订单参数
            order_params = {
                "side": order_side,
                "symbol": symbol,
                "order_type": o_type,
                "submitted_price": submitted_price,
                "submitted_quantity": quantity,
                "time_in_force": tif,
                "remark": remark or f"Auto trade via OpenAPI - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            }
            
            # 添加止盈止损参数
            if trigger_price:
                order_params["trigger_price"] = Decimal(str(trigger_price))
            if trailing_percent:
                order_params["trailing_percent"] = Decimal(str(trailing_percent))
            if trailing_amount:
                order_params["trailing_amount"] = Decimal(str(trailing_amount))
                
            order_info = {
                "symbol": symbol,
                "side": side,
                "quantity": quantity,
                "price": float(price) if price else None,
                "status": "submitted",
                "submitted_at": datetime.now().isoformat(),
                "mode": "paper" if self.is_paper else "real",
                "trigger_price": trigger_price,
                "trailing_percent": trailing_percent,
                "trailing_amount": trailing_amount,
                "remark": remark or f"Auto trade via OpenAPI - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                "instruction_timestamp": instruction_timestamp,
            }
            # 以即将调用 submit_order 的此刻（t0）作为「提交订单」时间点
            print_order_submitting_display(order_info)
            t0 = time.perf_counter()
            resp = self.ctx.submit_order(**order_params)
            order_info["_timing_submit_api_ms"] = (time.perf_counter() - t0) * 1000
            order_info["order_id"] = getattr(resp, "order_id", None) or getattr(resp, "id", None) or (str(resp) if resp else None)
            return order_info
            
        except ValueError as e:
            # 构造失败订单信息
            failed_order = {
                "symbol": symbol,
                "side": side,
                "quantity": quantity,
                "price": float(price) if price else None,
                "mode": "paper" if self.is_paper else "real",
                "remark": remark or f"Auto trade via OpenAPI - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            }
            
            # 使用红色边框表格展示失败订单
            print_order_failed_table(failed_order, str(e))
            
            logger.error(f"❌ 订单提交失败: {e}")
            raise
        except Exception as e:
            logger.error(f"❌ 订单提交失败: {e}")
            raise
    
    def cancel_order(self, order_id: str) -> Dict:
        """
        撤销订单
        
        Args:
            order_id: 订单ID
        
        Returns:
            撤销结果字典
        """
        # 检查是否启用自动交易
        if not self.auto_trade:
            logger.warning("⚠️  自动交易未启用，跳过订单撤销")
            return {"order_id": order_id, "status": "skipped", "reason": "auto_trade_disabled"}
        
        # Dry run 模式
        if self.dry_run:
            logger.info(f"🧪 [DRY RUN] 模拟撤销订单: {order_id}")
            return {"order_id": order_id, "status": "mock_cancelled", "mode": "dry_run"}
        
        try:
            # 先获取订单信息用于显示
            orders = self.get_today_orders()
            target_order = None
            for order in orders:
                if order.get('order_id') == order_id:
                    target_order = order
                    break
            
            # 撤销订单（API不返回值或返回None）
            self.ctx.cancel_order(order_id)
            
            result = {
                "order_id": order_id,
                "status": "cancelled",
                "cancelled_at": datetime.now().isoformat(),
                "mode": "paper" if self.is_paper else "real"
            }
            
            # 如果找到原订单信息，添加到结果中
            if target_order:
                result.update({
                    "symbol": target_order.get('symbol'),
                    "side": target_order.get('side'),
                    "quantity": target_order.get('quantity'),
                    "price": target_order.get('price')
                })
            
            # 使用彩色表格输出
            print_success_message("订单撤销成功")
            print_order_cancel_table(result, "撤销订单详情")
            
            return result
            
        except Exception as e:
            print_error_message(f"订单撤销失败: {e}")
            raise
    
    def replace_order(
        self,
        order_id: str,
        quantity: int,
        price: Optional[float] = None,
        trigger_price: Optional[float] = None,
        trailing_percent: Optional[float] = None,
        trailing_amount: Optional[float] = None,
        remark: str = ""
    ) -> Dict:
        """
        修改订单（替换订单）
        
        Args:
            order_id: 要修改的订单ID
            quantity: 新的数量
            price: 新的价格（限价单）
            trigger_price: 新的触发价格（条件单）
            trailing_percent: 新的跟踪止损百分比
            trailing_amount: 新的跟踪止损金额
            remark: 订单备注
        
        Returns:
            修改结果字典
        """
        # 检查是否启用自动交易
        if not self.auto_trade:
            logger.warning("⚠️  自动交易未启用，跳过订单修改")
            return {"order_id": order_id, "status": "skipped", "reason": "auto_trade_disabled"}
        
        # Dry run 模式
        if self.dry_run:
            logger.info(f"🧪 [DRY RUN] 模拟修改订单: {order_id}")
            return {
                "order_id": order_id,
                "quantity": quantity,
                "price": price,
                "status": "mock_replaced",
                "mode": "dry_run"
            }
        
        try:
            # 先获取原订单信息
            orders = self.get_today_orders()
            old_order = None
            for order in orders:
                if order.get('order_id') == order_id:
                    old_order = order
                    break
            
            if not old_order:
                raise ValueError(f"未找到订单: {order_id}")

            # 长桥 API 要求 price 和 quantity 均非空；未传时用原单价格/数量
            quantity_decimal = Decimal(int(quantity)) if quantity is not None else Decimal(int(old_order.get("quantity", 0)))
            price_val = price if price is not None else old_order.get("price")
            if price_val is not None:
                price_val = Decimal(str(price_val))

            # 准备修改参数（API 要求 quantity、price 必填，缺一不可）
            if price_val is None:
                raise ValueError("原订单无价格信息，无法修改订单（长桥要求替换时必传 price）")
            replace_params = {
                "order_id": order_id,
                "quantity": quantity_decimal,
                "price": price_val,
            }

            # 添加可选参数
            if trigger_price is not None:
                replace_params["trigger_price"] = Decimal(str(trigger_price))
            if trailing_percent is not None:
                replace_params["trailing_percent"] = Decimal(str(trailing_percent))
            if trailing_amount is not None:
                replace_params["trailing_amount"] = Decimal(str(trailing_amount))
            if remark:
                replace_params["remark"] = remark
            
            # 修改订单
            self.ctx.replace_order(**replace_params)
            
            # 新值字典
            new_values = {
                "quantity": quantity,
                "price": float(price) if price is not None else old_order.get('price'),
                "trigger_price": trigger_price,
                "trailing_percent": trailing_percent,
                "trailing_amount": trailing_amount
            }
            
            result = {
                "order_id": order_id,
                "quantity": quantity,
                "price": float(price) if price else None,
                "status": "replaced",
                "replaced_at": datetime.now().isoformat(),
                "mode": "paper" if self.is_paper else "real"
            }
            
            # 使用彩色表格输出修改对比
            print_success_message("订单修改成功")
            print_order_modify_table(order_id, old_order, new_values, "订单修改详情")
            
            return result
            
        except Exception as e:
            logger.error("订单修改失败: %s", e)
            err_str = str(e)
            if "602012" in err_str or "order amendment is not supported" in err_str.lower():
                raise ValueError(
                    "该订单类型不支持修改（长桥错误 602012）。"
                    "市价单、部分特殊限价单等不支持 replace。"
                    "建议：先撤单再按新条件重新下单。"
                ) from e
            raise
    
    def _mock_order_response(self, symbol: str, side: str, quantity: int, price: Optional[float]) -> Dict:
        """生成模拟订单响应"""
        return {
            "order_id": f"MOCK_{datetime.now().strftime('%Y%m%d%H%M%S')}",
            "symbol": symbol,
            "side": side,
            "quantity": quantity,
            "price": price,
            "status": "mock",
            "submitted_at": datetime.now().isoformat(),
            "mode": "dry_run"
        }
    
    def _check_position_for_sell(self, symbol: str, quantity: int) -> bool:
        """
        检查持仓是否足够卖出
        
        Args:
            symbol: 股票代码，如 "AAPL.US"
            quantity: 要卖出的数量
        
        Returns:
            bool: 是否有足够持仓
        """
        try:
            # 获取持仓信息
            positions = self.get_positions()
            
            # 查找目标股票的持仓
            target_position = None
            for pos in positions:
                if pos['symbol'] == symbol:
                    target_position = pos
                    break
            
            # 没有持仓
            if not target_position:
                logger.warning(f"❌ 没有持仓: {symbol}")
                print_warning_message(f"无法卖出 {symbol}: 没有持仓")
                return False
            
            # 可用数量不足
            available_quantity = target_position.get('available_quantity', 0)
            if available_quantity < quantity:
                logger.warning(
                    f"❌ 持仓数量不足: {symbol} "
                    f"可用 {available_quantity} < 卖出 {quantity}"
                )
                print_warning_message(
                    f"无法卖出 {quantity} 股 {symbol}: "
                    f"可用持仓仅 {available_quantity} 股"
                )
                return False
            
            return True
            
        except Exception as e:
            logger.error(f"持仓检查失败: {e}")
            return False
    
    def get_today_orders(self) -> list:
        """获取当日订单"""
        try:
            orders = self.ctx.today_orders()
            return [
                {
                    "order_id": order.order_id,
                    "symbol": order.symbol,
                    "side": "BUY" if order.side == OrderSide.Buy else "SELL",
                    "quantity": order.quantity,
                    "executed_quantity": order.executed_quantity,
                    "price": float(order.price) if order.price else None,
                    "status": str(order.status),
                    "submitted_at": order.submitted_at.isoformat()
                }
                for order in orders
            ]
        except Exception as e:
            logger.error(f"获取订单失败: {e}")
            return []

    def get_history_orders(self, start_at: datetime, end_at: datetime) -> list:
        """获取历史订单（仅 Filled，美股市场）。用于回填持仓对应的交易记录。"""
        try:
            resp = self.ctx.history_orders(
                status=[OrderStatus.Filled],
                market=Market.US,
                start_at=start_at,
                end_at=end_at,
            )
            orders = getattr(resp, "orders", resp) if not isinstance(resp, list) else resp
            if not isinstance(orders, list):
                orders = []
            return [
                {
                    "order_id": order.order_id,
                    "symbol": order.symbol,
                    "side": "BUY" if order.side == OrderSide.Buy else "SELL",
                    "quantity": order.quantity,
                    "executed_quantity": getattr(order, "executed_quantity", order.quantity),
                    "price": float(order.price) if getattr(order, "price", None) else None,
                    "status": str(getattr(order, "status", "")),
                    "submitted_at": order.submitted_at.isoformat() if hasattr(order.submitted_at, "isoformat") else str(order.submitted_at),
                }
                for order in orders
            ]
        except Exception as e:
            logger.debug(f"获取历史订单失败: {e}")
            return []

    def get_positions(self) -> list:
        """获取持仓信息"""
        try:
            response = self.ctx.stock_positions()
            # response.channels 是一个列表，每个元素包含 account_channel 和 positions
            positions = []
            for channel in response.channels:
                for pos in channel.positions:
                    positions.append({
                        "symbol": pos.symbol,
                        "symbol_name": pos.symbol_name,
                        "quantity": float(pos.quantity),
                        "available_quantity": float(pos.available_quantity),
                        "cost_price": float(pos.cost_price),
                        "currency": pos.currency,
                        "market": str(pos.market)
                    })
            return positions
        except Exception as e:
            logger.error(f"获取持仓失败: {e}")
            return []
    
    def get_account_balance(self) -> dict:
        """获取账户余额，通过 account_balance(currency=\"USD\") 指定币种为 USD。
        总资产=net_assets，现金=available_cash+frozen_cash，可用现金=available_cash。
        """
        try:
            balance = self.ctx.account_balance(currency="USD")
            if not balance:
                return {
                    "available_cash": 0.0,
                    "cash": 0.0,
                    "net_assets": 0.0,
                    "total_cash": 0.0,
                    "currency": "USD",
                    "mode": "paper" if self.is_paper else "real"
                }
            b = balance[0]
            cash_infos = b.cash_infos or []
            available_cash = float(cash_infos[0].available_cash) if cash_infos else 0.0
            frozen_cash = float(cash_infos[0].frozen_cash) if cash_infos else 0.0
            cash = available_cash + frozen_cash
            net_assets = float(b.net_assets)
            return {
                "available_cash": available_cash,
                "cash": cash,
                "net_assets": net_assets,
                "total_cash": net_assets,
                "currency": "USD",
                "mode": "paper" if self.is_paper else "real"
            }
        except Exception as e:
            logger.error(f"获取账户余额失败: {e}")
            return {}
    
    def show_account_info(self):
        """
        以表格形式展示账户信息
        包含总资产、可用资金、冻结资金、持仓市值等
        """
        try:
            # 获取账户余额
            balance_info = self.get_account_balance()
            
            # 获取持仓信息（用于计算持仓市值）
            positions = self.get_positions()
            position_value = sum(
                pos.get('quantity', 0) * pos.get('cost_price', 0) 
                for pos in positions
            )
            
            # 组合账户信息
            account_info = {
                **balance_info,
                'position_value': position_value
            }
            
            # 使用表格格式化输出
            mode_display = "🧪 模拟账户" if self.is_paper else "💰 真实账户"
            print_account_info_table(account_info, title=f"账户信息 ({mode_display})")
            
        except Exception as e:
            logger.error(f"展示账户信息失败: {e}")
            print_error_message(f"展示账户信息失败: {e}")
    
    def show_positions(self):
        """
        以表格形式展示持仓信息
        包含期权名称、持仓数量、成本价、当前价、盈亏等
        """
        try:
            positions = self.get_positions()
            
            if not positions:
                print_warning_message("无持仓")
                return
            
            # 使用表格格式化输出
            mode_display = "🧪 模拟账户" if self.is_paper else "💰 真实账户"
            print_positions_table(positions, title=f"持仓信息 ({mode_display})")
            
        except Exception as e:
            logger.error(f"展示持仓信息失败: {e}")
            print_error_message(f"展示持仓信息失败: {e}")
    
    def show_today_orders(self):
        """
        以表格形式展示当日订单
        包含期权名称、方向、数量、价格、状态等
        """
        try:
            orders = self.get_today_orders()
            
            if not orders:
                print_warning_message("无当日订单")
                return
            
            # 使用表格格式化输出
            mode_display = "🧪 模拟账户" if self.is_paper else "💰 真实账户"
            print_orders_summary_table(orders, title=f"当日订单 ({mode_display})")
            
        except Exception as e:
            logger.error(f"展示当日订单失败: {e}")
            print_error_message(f"展示当日订单失败: {e}")
    
    def get_option_expiry_dates(self, symbol: str) -> List[str]:
        """
        获取期权到期日列表
        
        Args:
            symbol: 标的代码，如 "AAPL.US"
        
        Returns:
            到期日列表，格式为 YYMMDD 字符串，如 ["260207", "260214", "260221"]
        """
        try:
            # 确保symbol带有市场后缀
            if not symbol.endswith('.US'):
                symbol = f"{symbol}.US"
            
            resp = self._with_fd_std_suppressed(
                self.quote_ctx.option_chain_expiry_date_list, symbol
            )
            
            # 转换 datetime.date 对象为 YYMMDD 字符串
            expiry_dates = []
            for date_obj in resp:
                date_str = date_obj.strftime("%y%m%d")
                expiry_dates.append(date_str)
            
            logger.info(f"获取 {symbol} 期权到期日: {len(expiry_dates)} 个")
            return expiry_dates
        except Exception as e:
            logger.error(f"获取期权到期日失败: {e}")
            return []
    
    def get_option_chain_info(self, symbol: str, expiry_date: str) -> Dict:
        """
        获取指定到期日的期权链信息（包含所有行权价）
        
        Args:
            symbol: 标的代码，如 "AAPL.US"
            expiry_date: 到期日，格式为 YYMMDD 字符串，如 "260207"
        
        Returns:
            期权链信息字典，包含看涨和看跌期权的行权价和代码
        """
        try:
            from datetime import datetime
            
            # 确保symbol带有市场后缀
            if not symbol.endswith('.US'):
                symbol = f"{symbol}.US"
            
            # 将 YYMMDD 字符串转换为 datetime.date 对象
            date_obj = datetime.strptime(expiry_date, "%y%m%d").date()
            
            # 获取期权链
            resp = self._with_fd_std_suppressed(
                self.quote_ctx.option_chain_info_by_date, symbol, date_obj
            )
            
            # 解析响应
            option_chain = {
                "symbol": symbol,
                "expiry_date": expiry_date,
                "strike_prices": [],
                "call_symbols": [],
                "put_symbols": []
            }
            
            # 提取行权价和期权代码（注意：属性名是 price，不是 strike_price）
            for strike_info in resp:
                option_chain["strike_prices"].append(float(strike_info.price))
                option_chain["call_symbols"].append(strike_info.call_symbol)
                option_chain["put_symbols"].append(strike_info.put_symbol)
            
            logger.info(
                f"获取 {symbol} {expiry_date} 期权链: "
                f"{len(option_chain['strike_prices'])} 个行权价"
            )
            
            return option_chain
        except Exception as e:
            logger.error(f"获取期权链信息失败: {e}")
            return {}
    
    def get_option_quote(self, symbols: List[str]) -> List[Dict]:
        """
        获取期权实时报价
        
        Args:
            symbols: 期权代码列表，如 ["AAPL260207C250000.US"]
        
        Returns:
            期权报价列表
        """
        try:
            resp = self._with_fd_std_suppressed(self.quote_ctx.option_quote, symbols)
            
            quotes = []
            for quote in resp:
                # 构建基础报价信息
                quote_data = {
                    "symbol": quote.symbol,
                    "last_done": float(quote.last_done) if quote.last_done else 0,
                    "open": float(quote.open) if hasattr(quote, 'open') and quote.open else 0,
                    "high": float(quote.high) if hasattr(quote, 'high') and quote.high else 0,
                    "low": float(quote.low) if hasattr(quote, 'low') and quote.low else 0,
                    "volume": int(quote.volume) if quote.volume else 0,
                }
                
                # 获取期权扩展信息
                if hasattr(quote, 'extend') and quote.extend:
                    extend = quote.extend
                    quote_data.update({
                        "open_interest": int(extend.open_interest) if hasattr(extend, 'open_interest') and extend.open_interest else 0,
                        "implied_volatility": float(extend.implied_volatility) if hasattr(extend, 'implied_volatility') and extend.implied_volatility else 0,
                        "strike_price": float(extend.strike_price) if hasattr(extend, 'strike_price') and extend.strike_price else 0,
                        "contract_type": str(extend.contract_type) if hasattr(extend, 'contract_type') else "",
                        "direction": str(extend.direction) if hasattr(extend, 'direction') else "",
                    })
                
                quotes.append(quote_data)
            
            return quotes
        except Exception as e:
            logger.error(f"获取期权报价失败: {e}")
            return []
    
    def get_stock_quote(self, symbols: List[str]) -> List[Dict]:
        """
        获取正股实时报价
        
        Args:
            symbols: 股票代码列表，如 ["AAPL.US", "TSLA.US"]
        
        Returns:
            股票报价列表
        """
        try:
            # 确保所有symbol都带有市场后缀
            symbols_with_market = []
            for symbol in symbols:
                if not symbol.endswith('.US') and not symbol.endswith('.HK'):
                    symbol = f"{symbol}.US"
                symbols_with_market.append(symbol)
            
            resp = self._with_fd_std_suppressed(
                self.quote_ctx.quote, symbols_with_market
            )
            
            quotes = []
            for quote in resp:
                quote_data = {
                    "symbol": quote.symbol,
                    "last_done": float(quote.last_done) if quote.last_done else 0,
                    "prev_close": float(quote.prev_close) if quote.prev_close else 0,
                    "open": float(quote.open) if quote.open else 0,
                    "high": float(quote.high) if quote.high else 0,
                    "low": float(quote.low) if quote.low else 0,
                    "volume": int(quote.volume) if quote.volume else 0,
                    "turnover": float(quote.turnover) if quote.turnover else 0,
                    "timestamp": quote.timestamp if hasattr(quote, 'timestamp') else None,
                }
                quotes.append(quote_data)
            
            logger.debug(f"获取 {len(quotes)} 个正股报价")
            return quotes
        except Exception as e:
            logger.error(f"获取正股报价失败: {e}")
            return []
    
    def submit_stock_order(
        self,
        symbol: str,
        side: str,  # "BUY" 或 "SELL"
        quantity: int,
        price: Optional[float] = None,
        order_type: str = "LIMIT",  # "LIMIT" 或 "MARKET"
        remark: str = "",
        trigger_price: Optional[float] = None,  # 触发价格（条件单）
        trailing_percent: Optional[float] = None,  # 跟踪止损百分比
        trailing_amount: Optional[float] = None  # 跟踪止损金额
    ) -> Dict:
        """
        提交正股订单（支持止盈止损）
        
        Args:
            symbol: 股票代码，如 "AAPL.US"
            side: 买卖方向 BUY/SELL
            quantity: 数量（股数）
            price: 限价单价格（市价单传 None）
            order_type: 订单类型 LIMIT/MARKET
            remark: 订单备注
            trigger_price: 触发价格（条件单，用于止盈止损）
            trailing_percent: 跟踪止损百分比（如 5 表示 5%）
            trailing_amount: 跟踪止损金额
        
        Returns:
            订单信息字典
        """
        # 检查是否启用自动交易
        if not self.auto_trade:
            logger.warning("⚠️  自动交易未启用，跳过订单提交")
            mock = self._mock_order_response(symbol, side, quantity, price)
            print_order_submitted_display(mock, multiplier=1)
            return mock
        
        # Dry run 模式
        if self.dry_run:
            logger.info(f"🧪 [DRY RUN] 模拟下单: {symbol} {side} {quantity} @ {price}")
            mock = self._mock_order_response(symbol, side, quantity, price)
            print_order_submitted_display(mock, multiplier=1)
            return mock
        
        try:
            # 确保symbol带有市场后缀
            if not symbol.endswith('.US') and not symbol.endswith('.HK'):
                symbol = f"{symbol}.US"
            
            # 卖出时检查持仓
            if side.upper() == "SELL":
                if not self._check_position_for_sell(symbol, quantity):
                    raise ValueError(f"持仓不足: 无法卖出 {quantity} 股 {symbol}")

            # 转换买卖方向
            order_side = OrderSide.Buy if side.upper() == "BUY" else OrderSide.Sell
            
            # 转换订单类型
            if order_type.upper() == "MARKET":
                o_type = OrderType.MO
                submitted_price = None
            else:
                o_type = OrderType.LO
                if price is None:
                    raise ValueError("限价单必须提供价格")
                submitted_price = Decimal(str(price))
            
            # 准备订单参数
            order_params = {
                "side": order_side,
                "symbol": symbol,
                "order_type": o_type,
                "submitted_price": submitted_price,
                "submitted_quantity": quantity,
                "time_in_force": TimeInForceType.Day,
                "remark": remark or f"Auto trade via OpenAPI - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            }
            
            # 添加止盈止损参数
            if trigger_price:
                order_params["trigger_price"] = Decimal(str(trigger_price))
            if trailing_percent:
                order_params["trailing_percent"] = Decimal(str(trailing_percent))
            if trailing_amount:
                order_params["trailing_amount"] = Decimal(str(trailing_amount))
            
            # 以即将调用 submit_order 的此刻作为「提交订单」时间点
            pre_info = {
                "symbol": symbol,
                "side": side,
                "quantity": quantity,
                "price": float(price) if price else None,
                "mode": "paper" if self.is_paper else "real",
            }
            print_order_submitting_display(pre_info, multiplier=1)
            resp = self.ctx.submit_order(**order_params)
            order_info = {
                "order_id": resp.order_id,
                "symbol": symbol,
                "side": side,
                "quantity": quantity,
                "price": float(price) if price else None,
                "status": "submitted",
                "submitted_at": datetime.now().isoformat(),
                "mode": "paper" if self.is_paper else "real",
                "trigger_price": trigger_price,
                "trailing_percent": trailing_percent,
                "trailing_amount": trailing_amount,
                "remark": remark or f"Auto trade via OpenAPI - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            }
            print_order_push_submitted_display(order_info, multiplier=1)
            return order_info
            
        except ValueError as e:
            # 构造失败订单信息
            failed_order = {
                "symbol": symbol,
                "side": side,
                "quantity": quantity,
                "price": float(price) if price else None,
                "mode": "paper" if self.is_paper else "real",
                "remark": remark or f"Auto trade via OpenAPI - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            }
            
            # 使用红色边框表格展示失败订单
            print_order_failed_table(failed_order, str(e))
            
            logger.error(f"❌ 正股订单提交失败: {e}")
            raise
        except Exception as e:
            logger.error(f"❌ 正股订单提交失败: {e}")
            raise


def validate_option_expiry(symbol: str) -> None:
    """
    从长桥期权代码中解析到期日并校验是否已过期。
    格式：TICKER + YYMMDD + C/P + 价格 + .US
    
    Raises:
        ValueError: 若期权已过期
    """
    import re
    # 匹配 YYMMDD（6 位数字，在 C 或 P 之前）
    m = re.search(r"(\d{6})[CP]\d+\.US$", symbol, re.IGNORECASE)
    if not m:
        return
    yy, mm, dd = int(m.group(1)[:2]), int(m.group(1)[2:4]), int(m.group(1)[4:6])
    year = 2000 + yy
    now = datetime.now()
    expiry_date = datetime(year, mm, dd)
    expiry_end = expiry_date.replace(hour=23, minute=59, second=59)
    if now > expiry_end:
        raise ValueError(
            f"期权已过期: 到期日 {expiry_date.strftime('%Y-%m-%d')} "
            f"早于当前日期 {now.strftime('%Y-%m-%d %H:%M:%S')}"
        )


def convert_to_longport_symbol(ticker: str, option_type: str, strike: float, expiry: str) -> str:
    """
    将期权信息转换为长桥期权代码格式
    
    格式：TICKER + YYMMDD + C/P + 价格.US，价格为行权价×1000 不补前导零
    示例：EOSE260109C13500.US（行权价 13.5）、AAPL260206C110000.US（行权价 110）
    
    Args:
        ticker: 股票代码，如 "AAPL"
        option_type: "CALL" 或 "PUT"
        strike: 行权价，如 150.0
        expiry: 到期日，如 "1/31" 或 "2025-01-31"
    
    Returns:
        长桥期权代码
        
    Raises:
        ValueError: 如果期权已过期
    """
    from datetime import datetime, timedelta
    
    now = datetime.now()
    expiry_date = None
    
    # 处理 "本周" 等中文到期日
    if expiry in ["本周", "this week"]:
        # 简化处理：使用本周五
        days_until_friday = (4 - now.weekday()) % 7
        if days_until_friday == 0:
            days_until_friday = 7
        expiry_date = now + timedelta(days=days_until_friday)
        expiry = expiry_date.strftime("%m/%d")
    
    # 解析到期日
    import re
    if "/" in expiry:
        # 格式：1/31 或 01/31
        parts = expiry.split("/")
        month, day = int(parts[0]), int(parts[1])
        year = now.year
        if month < now.month:
            year += 1
        expiry_date = datetime(year, month, day)
        expiry_str = f"{year % 100:02d}{month:02d}{day:02d}"
    else:
        # 格式：2月13（中文）
        m_yue_d = re.match(r"^(\d{1,2})月(\d{1,2})$", expiry.strip())
        if m_yue_d:
            month, day = int(m_yue_d.group(1)), int(m_yue_d.group(2))
            year = now.year
            if month < now.month:
                year += 1
            expiry_date = datetime(year, month, day)
            expiry_str = f"{year % 100:02d}{month:02d}{day:02d}"
        else:
            # 假设格式：2025-01-31 或 20250131
            expiry_clean = expiry.replace("-", "")
            if len(expiry_clean) == 8 and expiry_clean.isdigit():
                year = int(expiry_clean[:4])
                month = int(expiry_clean[4:6])
                day = int(expiry_clean[6:8])
                expiry_date = datetime(year, month, day)
                expiry_str = expiry_clean[-6:]  # YYMMDD
            else:
                raise ValueError(f"无法解析到期日格式: {expiry!r}，支持 1/31、2月13、2025-01-31、20250131")
    
    # 检查期权是否已过期
    if expiry_date:
        # 设置到期日为当天23:59:59进行比较
        expiry_end_of_day = expiry_date.replace(hour=23, minute=59, second=59)
        if now > expiry_end_of_day:
            raise ValueError(
                f"期权已过期: 到期日 {expiry_date.strftime('%Y-%m-%d')} "
                f"早于当前日期 {now.strftime('%Y-%m-%d %H:%M:%S')}"
            )
    
    # 期权类型
    opt_type = "C" if option_type.upper() == "CALL" else "P"
    
    # 价格为行权价×1000，不补前导零。例：13.5 → 13500, 110 → 110000
    strike_str = str(int(strike * 1000))
    
    # 组合期权代码
    symbol = f"{ticker}{expiry_str}{opt_type}{strike_str}.US"
    
    return symbol


def calculate_quantity(price: float, available_cash: float) -> int:
    """
    根据 MAX_OPTION_TOTAL_PRICE 与可用资金计算合约数量。
    
    Args:
        price: 期权单价（每股）
        available_cash: 可用资金
    
    Returns:
        合约数量（至少 1 张，且不超过总价上限与资金允许的数量）
    """
    import os
    max_total = float(os.getenv('MAX_OPTION_TOTAL_PRICE', '10000'))
    cap = min(max_total, available_cash)
    single_contract = price * 100  # 每张 100 股
    if single_contract <= 0:
        return 1
    quantity = int(cap / single_contract)
    return max(1, quantity)
