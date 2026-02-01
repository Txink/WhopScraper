"""
风险控制模块
自动执行止损和止盈，管理仓位风险
"""
from typing import Dict, List, Optional, Callable
from datetime import datetime
import logging
import time
import threading

from .position_manager import PositionManager, Position
from .longport_broker import LongPortBroker

logger = logging.getLogger(__name__)


class RiskController:
    """风险控制器 - 自动止损止盈"""
    
    def __init__(
        self,
        broker: LongPortBroker,
        position_manager: PositionManager,
        check_interval: int = 10
    ):
        """
        初始化风险控制器
        
        Args:
            broker: 交易接口
            position_manager: 持仓管理器
            check_interval: 检查间隔（秒）
        """
        self.broker = broker
        self.position_manager = position_manager
        self.check_interval = check_interval
        
        self._running = False
        self._thread = None
        
        # 回调函数
        self.on_stop_loss: Optional[Callable] = None
        self.on_take_profit: Optional[Callable] = None
        self.on_risk_alert: Optional[Callable] = None
    
    def start(self):
        """启动风险控制"""
        if self._running:
            logger.warning("风险控制器已经在运行")
            return
        
        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        logger.info(f"✅ 风险控制器已启动（检查间隔: {self.check_interval}秒）")
    
    def stop(self):
        """停止风险控制"""
        if not self._running:
            return
        
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
        logger.info("⏹  风险控制器已停止")
    
    def _run_loop(self):
        """主循环"""
        while self._running:
            try:
                # 先检查是否有持仓，避免不必要的API调用
                positions = self.position_manager.get_all_positions()
                if positions:
                    self._check_and_execute()
                else:
                    logger.debug("当前无持仓，跳过风险检查")
            except Exception as e:
                logger.error(f"风险检查错误: {e}")
            
            time.sleep(self.check_interval)
    
    def _check_and_execute(self):
        """检查并执行风险控制"""
        # 1. 从券商同步持仓价格
        self._sync_positions()
        
        # 2. 检查止损止盈触发
        alerts = self.position_manager.check_alerts()
        
        if not alerts:
            return
        
        logger.info(f"⚠️  检测到 {len(alerts)} 个风险警报")
        
        for alert in alerts:
            try:
                self._handle_alert(alert)
            except Exception as e:
                logger.error(f"处理警报失败: {alert['symbol']} - {e}")
    
    def _sync_positions(self):
        """从券商同步持仓，更新实时价格"""
        try:
            broker_positions = self.broker.get_positions()
            
            if not broker_positions:
                logger.debug("当前无持仓")
                return
            
            # 收集所有持仓的 symbol
            symbols = [pos.get('symbol') for pos in broker_positions if pos.get('symbol')]
            
            if not symbols:
                logger.debug("未找到有效的持仓代码")
                return
            
            # 批量获取期权实时报价
            quotes = self.broker.get_option_quote(symbols)
            
            if not quotes:
                logger.debug(f"未能获取 {len(symbols)} 个期权的实时报价，使用成本价")
                # 降级方案：使用成本价
                price_updates = {}
                for pos_data in broker_positions:
                    symbol = pos_data.get('symbol')
                    cost_price = pos_data.get('cost_price', 0)
                    if symbol and cost_price > 0:
                        price_updates[symbol] = cost_price
                        logger.debug(f"{symbol}: ${cost_price:.2f} (成本价)")
                
                if price_updates:
                    self.position_manager.update_prices(price_updates)
                    logger.info(f"使用成本价更新 {len(price_updates)} 个持仓")
                return
            
            # 构建报价字典 {symbol: last_done}
            quote_map = {
                q['symbol']: q['last_done'] 
                for q in quotes 
                if q.get('last_done', 0) > 0
            }
            
            # 更新持仓价格
            price_updates = {}
            for pos_data in broker_positions:
                symbol = pos_data.get('symbol')
                if not symbol:
                    continue
                
                # 优先使用实时报价
                if symbol in quote_map:
                    current_price = quote_map[symbol]
                    price_updates[symbol] = current_price
                    logger.debug(f"{symbol}: ${current_price:.2f} (实时)")
                else:
                    # 降级使用成本价
                    cost_price = pos_data.get('cost_price', 0)
                    if cost_price > 0:
                        price_updates[symbol] = cost_price
                        logger.debug(f"{symbol}: ${cost_price:.2f} (成本价)")
            
            # 批量更新价格
            if price_updates:
                self.position_manager.update_prices(price_updates)
                logger.info(f"✅ 同步 {len(price_updates)} 个持仓的实时价格")
            
        except Exception as e:
            logger.error(f"同步持仓失败: {e}", exc_info=True)
    
    def _handle_alert(self, alert: Dict):
        """
        处理风险警报
        
        Args:
            alert: 警报信息
        """
        alert_type = alert['type']
        symbol = alert['symbol']
        position = self.position_manager.get_position(symbol)
        
        if not position:
            logger.warning(f"持仓不存在: {symbol}")
            return
        
        logger.warning(
            f"🚨 {alert_type} 触发: {symbol} "
            f"当前价 ${alert['current_price']:.2f} "
            f"触发价 ${alert['trigger_price']:.2f} "
            f"盈亏 ${alert['pnl']:,.2f} ({alert['pnl_pct']:+.2f}%)"
        )
        
        if alert_type == 'STOP_LOSS':
            self._execute_stop_loss(position, alert)
        elif alert_type == 'TAKE_PROFIT':
            self._execute_take_profit(position, alert)
    
    def _execute_stop_loss(self, position: Position, alert: Dict):
        """
        执行止损
        
        Args:
            position: 持仓
            alert: 警报信息
        """
        logger.info(f"🛑 执行止损: {position.symbol}")
        
        try:
            # 提交市价平仓单
            order = self.broker.submit_option_order(
                symbol=position.symbol,
                side="SELL",
                quantity=position.quantity,
                order_type="MARKET",
                remark=f"Stop loss triggered @ {alert['trigger_price']}"
            )
            
            logger.info(f"✅ 止损订单已提交: {order['order_id']}")
            
            # 回调通知
            if self.on_stop_loss:
                self.on_stop_loss(position, order, alert)
            
            # 移除持仓（等待成交确认后再移除更好）
            # self.position_manager.remove_position(position.symbol)
            
        except Exception as e:
            logger.error(f"❌ 止损失败: {e}")
            
            # 发送风险警报
            if self.on_risk_alert:
                self.on_risk_alert({
                    'type': 'STOP_LOSS_FAILED',
                    'position': position,
                    'error': str(e)
                })
    
    def _execute_take_profit(self, position: Position, alert: Dict):
        """
        执行止盈
        
        Args:
            position: 持仓
            alert: 警报信息
        """
        logger.info(f"💰 执行止盈: {position.symbol}")
        
        try:
            # 可以选择部分平仓或全部平仓
            # 这里默认全部平仓
            order = self.broker.submit_option_order(
                symbol=position.symbol,
                side="SELL",
                quantity=position.quantity,
                price=alert['current_price'],  # 限价单
                order_type="LIMIT",
                remark=f"Take profit triggered @ {alert['trigger_price']}"
            )
            
            logger.info(f"✅ 止盈订单已提交: {order['order_id']}")
            
            # 回调通知
            if self.on_take_profit:
                self.on_take_profit(position, order, alert)
            
        except Exception as e:
            logger.error(f"❌ 止盈失败: {e}")
    
    def set_stop_loss_by_percentage(self, symbol: str, loss_pct: float):
        """
        按百分比设置止损
        
        Args:
            symbol: 期权代码
            loss_pct: 止损百分比（如 -10 表示跌 10%）
        """
        position = self.position_manager.get_position(symbol)
        if not position:
            logger.warning(f"持仓不存在: {symbol}")
            return
        
        stop_price = position.avg_cost * (1 + loss_pct / 100)
        position.set_stop_loss(stop_price)
        self.position_manager.update_position(
            symbol,
            stop_loss_price=stop_price
        )
    
    def set_take_profit_by_percentage(self, symbol: str, profit_pct: float):
        """
        按百分比设置止盈
        
        Args:
            symbol: 期权代码
            profit_pct: 止盈百分比（如 50 表示涨 50%）
        """
        position = self.position_manager.get_position(symbol)
        if not position:
            logger.warning(f"持仓不存在: {symbol}")
            return
        
        take_profit_price = position.avg_cost * (1 + profit_pct / 100)
        position.set_take_profit(take_profit_price)
        self.position_manager.update_position(
            symbol,
            take_profit_price=take_profit_price
        )
    
    def trailing_stop_loss(self, symbol: str, trailing_pct: float):
        """
        移动止损（跟随最高价）
        
        Args:
            symbol: 期权代码
            trailing_pct: 回撤百分比（如 10 表示从最高点回落 10%）
        """
        position = self.position_manager.get_position(symbol)
        if not position:
            logger.warning(f"持仓不存在: {symbol}")
            return
        
        # 计算新的止损价（当前价 - trailing_pct）
        new_stop_loss = position.current_price * (1 - trailing_pct / 100)
        
        # 只有新止损价更高时才调整（不能降低止损）
        if position.stop_loss_price is None or new_stop_loss > position.stop_loss_price:
            position.adjust_stop_loss(new_stop_loss)
            self.position_manager.update_position(
                symbol,
                stop_loss_price=new_stop_loss
            )


class AutoTrailingStopLoss:
    """自动移动止损"""
    
    def __init__(
        self,
        risk_controller: RiskController,
        trailing_pct: float = 10.0,
        check_interval: int = 30
    ):
        """
        初始化自动移动止损
        
        Args:
            risk_controller: 风险控制器
            trailing_pct: 回撤百分比
            check_interval: 检查间隔（秒）
        """
        self.risk_controller = risk_controller
        self.trailing_pct = trailing_pct
        self.check_interval = check_interval
        
        self._running = False
        self._thread = None
    
    def start(self):
        """启动自动移动止损"""
        if self._running:
            return
        
        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        logger.info(f"✅ 自动移动止损已启动（回撤 {self.trailing_pct}%）")
    
    def stop(self):
        """停止自动移动止损"""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
        logger.info("⏹  自动移动止损已停止")
    
    def _run_loop(self):
        """主循环"""
        while self._running:
            try:
                self._update_trailing_stops()
            except Exception as e:
                logger.error(f"移动止损更新错误: {e}")
            
            time.sleep(self.check_interval)
    
    def _update_trailing_stops(self):
        """更新所有持仓的移动止损"""
        positions = self.risk_controller.position_manager.get_all_positions()
        
        for position in positions:
            # 只对盈利的持仓启用移动止损
            if position.unrealized_pnl > 0:
                self.risk_controller.trailing_stop_loss(
                    position.symbol,
                    self.trailing_pct
                )


if __name__ == "__main__":
    # 测试风险控制器
    import sys
    
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )
    
    print("风险控制器模块测试")
    print("=" * 60)
    print("功能:")
    print("  ✅ 自动止损")
    print("  ✅ 自动止盈")
    print("  ✅ 移动止损")
    print("  ✅ 风险警报")
    print("=" * 60)
    print("\n使用示例请查看 LONGPORT_INTEGRATION_GUIDE.md")
