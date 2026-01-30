"""
长桥证券交易接口
支持模拟账户和真实账户，带风险控制和 dry_run 模式
"""
from decimal import Decimal
from typing import Dict, Optional
from longport.openapi import TradeContext, Config, OrderSide, OrderType, TimeInForceType
import logging
import os
from datetime import datetime

from .config_loader import LongPortConfigLoader

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
        self.ctx = TradeContext(self.config)
        self.positions: Dict[str, Dict] = {}  # 持仓跟踪
        self.daily_pnl = 0.0
        
        # 风险控制配置
        risk_config = config_loader.get_risk_config()
        self.max_position_ratio = risk_config["max_position_ratio"]
        self.max_daily_loss = risk_config["max_daily_loss"]
        self.min_order_amount = risk_config["min_order_amount"]
        
        # 模式标志
        self.dry_run = config_loader.is_dry_run()
        self.auto_trade = config_loader.is_auto_trade_enabled()
        self.is_paper = config_loader.is_paper_mode()
        
        logger.info(f"交易接口初始化完成 - 模式: {'模拟' if self.is_paper else '真实'}")
    
    def submit_option_order(
        self,
        symbol: str,
        side: str,  # "BUY" 或 "SELL"
        quantity: int,
        price: Optional[float] = None,
        order_type: str = "LIMIT",  # "LIMIT" 或 "MARKET"
        remark: str = ""
    ) -> Dict:
        """
        提交期权订单
        
        Args:
            symbol: 期权代码，如 "AAPL250131C00150000.US"
            side: 买卖方向 BUY/SELL
            quantity: 数量（合约数）
            price: 限价单价格（市价单传 None）
            order_type: 订单类型 LIMIT/MARKET
            remark: 订单备注
        
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
            # 风险检查
            order_amount = (price or 0) * quantity * 100  # 每张期权 100 股
            if not self._check_risk_limits(order_amount):
                raise ValueError("风险检查未通过，订单被拒绝")
            
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
            
            # 提交订单
            resp = self.ctx.submit_order(
                side=order_side,
                symbol=symbol,
                order_type=o_type,
                submitted_price=submitted_price,
                submitted_quantity=quantity,
                time_in_force=TimeInForceType.Day,
                remark=remark or f"Auto trade via OpenAPI - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            )
            
            order_info = {
                "order_id": resp.order_id,
                "symbol": symbol,
                "side": side,
                "quantity": quantity,
                "price": float(price) if price else None,
                "status": "submitted",
                "submitted_at": datetime.now().isoformat(),
                "mode": "paper" if self.is_paper else "real"
            }
            
            logger.info(f"✅ 订单提交成功: {order_info}")
            return order_info
            
        except Exception as e:
            logger.error(f"❌ 订单提交失败: {e}")
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
    
    def _check_risk_limits(self, order_amount: float) -> bool:
        """
        检查风险限制
        
        Args:
            order_amount: 订单金额
        
        Returns:
            bool: 是否通过风险检查
        """
        try:
            # 获取账户余额
            balance = self.ctx.account_balance()
            total_cash = float(balance[0].total_cash)
            
            # 特殊处理：如果是模拟账户且余额为负数，使用绝对值进行风险检查
            # 这是为了支持模拟账户的测试场景
            if self.is_paper and total_cash < 0:
                logger.warning(f"⚠️  模拟账户余额为负数: ${total_cash:.2f}，使用绝对值进行风险检查")
                total_cash = abs(total_cash)
            
            # 检查最小下单金额
            if order_amount < self.min_order_amount:
                logger.warning(f"订单金额过小: ${order_amount:.2f} < ${self.min_order_amount:.2f}")
                return False
            
            # 检查单笔投资是否超限
            max_position_amount = total_cash * self.max_position_ratio
            if order_amount > max_position_amount:
                logger.warning(
                    f"单笔投资超限: ${order_amount:.2f} > "
                    f"${max_position_amount:.2f} "
                    f"({self.max_position_ratio*100:.1f}%)"
                )
                return False
            
            # 检查当日亏损是否超限
            max_daily_loss = total_cash * self.max_daily_loss
            if self.daily_pnl < -max_daily_loss:
                logger.warning(
                    f"当日亏损超限: ${self.daily_pnl:.2f} < "
                    f"-${max_daily_loss:.2f} "
                    f"({self.max_daily_loss*100:.1f}%)"
                )
                return False
            
            logger.info(f"✅ 风险检查通过: 订单金额 ${order_amount:.2f}")
            return True
            
        except Exception as e:
            logger.error(f"风险检查失败: {e}")
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
    
    def cancel_order(self, order_id: str) -> bool:
        """撤销订单"""
        if self.dry_run:
            logger.info(f"🧪 [DRY RUN] 模拟撤销订单: {order_id}")
            return True
        
        try:
            self.ctx.cancel_order(order_id)
            logger.info(f"✅ 订单已撤销: {order_id}")
            return True
        except Exception as e:
            logger.error(f"❌ 撤销订单失败: {e}")
            return False
    
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
        """获取账户余额"""
        try:
            balance = self.ctx.account_balance()
            return {
                "total_cash": float(balance[0].total_cash),
                "available_cash": float(balance[0].cash_infos[0].available_cash) if balance[0].cash_infos else 0,
                "currency": balance[0].currency,
                "mode": "paper" if self.is_paper else "real"
            }
        except Exception as e:
            logger.error(f"获取账户余额失败: {e}")
            return {}


def convert_to_longport_symbol(ticker: str, option_type: str, strike: float, expiry: str) -> str:
    """
    将期权信息转换为长桥期权代码格式
    
    格式：TICKER + YYMMDD + C/P + 价格(8位，小数点后3位)
    示例：AAPL250131C00150000.US
    
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
        # 假设格式：2025-01-31 或 20250131
        expiry_clean = expiry.replace("-", "")
        if len(expiry_clean) == 8:
            # 格式：20250131
            year = int(expiry_clean[:4])
            month = int(expiry_clean[4:6])
            day = int(expiry_clean[6:8])
            expiry_date = datetime(year, month, day)
        expiry_str = expiry_clean[-6:]  # YYMMDD
    
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
    
    # 行权价格式化（8位数字，小数点后3位）
    strike_str = f"{int(strike * 1000):08d}"
    
    # 组合期权代码
    symbol = f"{ticker}{expiry_str}{opt_type}{strike_str}.US"
    
    return symbol


def calculate_quantity(price: float, available_cash: float, position_size: str = None) -> int:
    """
    计算购买数量
    
    根据账户资金和仓位大小计算合约数量
    
    Args:
        price: 期权价格
        available_cash: 可用资金
        position_size: 仓位大小 "小仓位"/"中仓位"/"大仓位"
    
    Returns:
        合约数量
    """
    # 根据仓位大小计算投入资金比例
    if position_size == "小仓位":
        invest_ratio = 0.05  # 5%
    elif position_size == "中仓位":
        invest_ratio = 0.10  # 10%
    elif position_size == "大仓位":
        invest_ratio = 0.15  # 15%
    else:
        invest_ratio = 0.05  # 默认 5%
    
    invest_amount = available_cash * invest_ratio
    
    # 计算合约数量（每张期权100股）
    quantity = int(invest_amount / (price * 100))
    
    # 至少买1张
    return max(1, quantity)
