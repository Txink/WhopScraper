"""
持仓管理模块
跟踪和管理期权持仓，计算盈亏，支持止损止盈
"""
from typing import Dict, List, Optional
from datetime import datetime
from dataclasses import dataclass, asdict
import json
import logging

logger = logging.getLogger(__name__)


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
    
    def calculate_pnl(self, current_price: float = None):
        """
        计算盈亏
        
        Args:
            current_price: 当前价格（可选，默认使用对象的 current_price）
        """
        if current_price:
            self.current_price = current_price
        
        # 计算市值和盈亏
        self.market_value = self.current_price * self.quantity * 100
        cost = self.avg_cost * self.quantity * 100
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


class PositionManager:
    """持仓管理器"""
    
    def __init__(self, storage_file: str = "data/positions.json"):
        """
        初始化持仓管理器
        
        Args:
            storage_file: 持仓数据存储文件
        """
        self.storage_file = storage_file
        self.positions: Dict[str, Position] = {}
        self._load_positions()
    
    def _load_positions(self):
        """从文件加载持仓"""
        try:
            import os
            if os.path.exists(self.storage_file):
                with open(self.storage_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    for symbol, pos_data in data.items():
                        self.positions[symbol] = Position(**pos_data)
                logger.info(f"加载持仓: {len(self.positions)} 个")
        except Exception as e:
            logger.error(f"加载持仓失败: {e}")
    
    def _save_positions(self):
        """保存持仓到文件"""
        try:
            import os
            os.makedirs(os.path.dirname(self.storage_file), exist_ok=True)
            
            data = {symbol: pos.to_dict() for symbol, pos in self.positions.items()}
            
            with open(self.storage_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            
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
        logger.info(f"添加持仓: {position.symbol} x{position.quantity}")
    
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
    
    def remove_position(self, symbol: str):
        """
        移除持仓（已全部平仓）
        
        Args:
            symbol: 期权代码
        """
        if symbol in self.positions:
            del self.positions[symbol]
            self._save_positions()
            logger.info(f"移除持仓: {symbol}")
    
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
