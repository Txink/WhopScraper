#!/usr/bin/env python3
"""
持仓管理和风险控制测试
演示持仓跟踪、止损止盈等功能
"""
import logging
import time
from broker import (
    load_longport_config,
    LongPortBroker,
    PositionManager,
    create_position_from_order,
    convert_to_longport_symbol
)
from broker.risk_controller import RiskController, AutoTrailingStopLoss

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def test_position_creation():
    """测试 1: 创建持仓"""
    print("\n" + "="*60)
    print("测试 1: 创建持仓")
    print("="*60)
    
    # 创建持仓管理器
    manager = PositionManager(storage_file="data/test_positions.json")
    
    # 模拟开仓
    symbol = convert_to_longport_symbol("AAPL", "CALL", 150.0, "1/31")
    position = create_position_from_order(
        symbol=symbol,
        ticker="AAPL",
        option_type="CALL",
        strike=150.0,
        expiry="2025-01-31",
        quantity=2,
        avg_cost=2.5,
        order_id="TEST_ORDER_001"
    )
    
    manager.add_position(position)
    logger.info(f"✅ 创建持仓: {symbol} x2 @ $2.5")
    
    return manager


def test_position_pnl_calculation(manager: PositionManager):
    """测试 2: 盈亏计算"""
    print("\n" + "="*60)
    print("测试 2: 盈亏计算")
    print("="*60)
    
    positions = manager.get_all_positions()
    if not positions:
        logger.warning("没有持仓可测试")
        return
    
    position = positions[0]
    
    # 模拟价格变化
    test_prices = [2.5, 2.8, 3.0, 2.3, 2.0]
    
    for price in test_prices:
        position.calculate_pnl(price)
        logger.info(
            f"价格: ${price:.2f} | "
            f"盈亏: ${position.unrealized_pnl:,.2f} ({position.unrealized_pnl_pct:+.2f}%)"
        )
    
    logger.info("✅ 盈亏计算测试完成")


def test_stop_loss_take_profit(manager: PositionManager):
    """测试 3: 止损止盈设置"""
    print("\n" + "="*60)
    print("测试 3: 止损止盈设置")
    print("="*60)
    
    positions = manager.get_all_positions()
    if not positions:
        logger.warning("没有持仓可测试")
        return
    
    position = positions[0]
    
    # 设置止损止盈
    position.set_stop_loss(2.0)   # 止损价 $2.0（-20%）
    position.set_take_profit(3.5)  # 止盈价 $3.5（+40%）
    
    manager.update_position(
        position.symbol,
        stop_loss_price=position.stop_loss_price,
        take_profit_price=position.take_profit_price
    )
    
    # 测试触发条件
    test_scenarios = [
        (1.9, "触发止损"),
        (3.6, "触发止盈"),
        (2.5, "正常范围")
    ]
    
    for price, scenario in test_scenarios:
        position.calculate_pnl(price)
        
        logger.info(f"\n场景: {scenario} (价格 ${price:.2f})")
        logger.info(f"  止损触发: {position.should_stop_loss()}")
        logger.info(f"  止盈触发: {position.should_take_profit()}")
    
    logger.info("\n✅ 止损止盈测试完成")


def test_multiple_positions(manager: PositionManager):
    """测试 4: 多持仓管理"""
    print("\n" + "="*60)
    print("测试 4: 多持仓管理")
    print("="*60)
    
    # 添加更多测试持仓
    test_positions = [
        ("TSLA", "PUT", 250.0, "2/7", 1, 3.0),
        ("NVDA", "CALL", 900.0, "2/14", 3, 5.5),
    ]
    
    for ticker, opt_type, strike, expiry, quantity, price in test_positions:
        symbol = convert_to_longport_symbol(ticker, opt_type, strike, expiry)
        position = create_position_from_order(
            symbol=symbol,
            ticker=ticker,
            option_type=opt_type,
            strike=strike,
            expiry=f"2025-{expiry.replace('/', '-')}",
            quantity=quantity,
            avg_cost=price,
            order_id=f"TEST_{ticker}"
        )
        manager.add_position(position)
        logger.info(f"添加持仓: {ticker} {opt_type} {strike} x{quantity}")
    
    # 打印持仓摘要
    manager.print_summary()
    
    logger.info("✅ 多持仓管理测试完成")


def test_risk_controller():
    """测试 5: 风险控制器"""
    print("\n" + "="*60)
    print("测试 5: 风险控制器")
    print("="*60)
    
    try:
        # 初始化组件
        config = load_longport_config()
        broker = LongPortBroker(config)
        manager = PositionManager(storage_file="data/test_positions.json")
        
        # 创建风险控制器
        risk_controller = RiskController(
            broker=broker,
            position_manager=manager,
            check_interval=5  # 5秒检查一次
        )
        
        # 设置回调
        def on_stop_loss(position, order, alert):
            logger.info(f"🛑 止损回调: {position.symbol} 订单 {order['order_id']}")
        
        def on_take_profit(position, order, alert):
            logger.info(f"💰 止盈回调: {position.symbol} 订单 {order['order_id']}")
        
        def on_risk_alert(alert_data):
            logger.warning(f"⚠️  风险警报: {alert_data}")
        
        risk_controller.on_stop_loss = on_stop_loss
        risk_controller.on_take_profit = on_take_profit
        risk_controller.on_risk_alert = on_risk_alert
        
        logger.info("风险控制器配置完成")
        logger.info("  • 止损回调: ✅")
        logger.info("  • 止盈回调: ✅")
        logger.info("  • 风险警报: ✅")
        
        # 测试按百分比设置止损止盈
        positions = manager.get_all_positions()
        if positions:
            pos = positions[0]
            risk_controller.set_stop_loss_by_percentage(pos.symbol, -15)  # 止损 -15%
            risk_controller.set_take_profit_by_percentage(pos.symbol, 50)  # 止盈 +50%
            logger.info(f"为 {pos.symbol} 设置止损 -15%，止盈 +50%")
        
        logger.info("✅ 风险控制器测试完成")
        logger.info("ℹ️  如需实际运行，调用 risk_controller.start()")
        
    except Exception as e:
        logger.error(f"❌ 风险控制器测试失败: {e}")


def test_trailing_stop():
    """测试 6: 移动止损"""
    print("\n" + "="*60)
    print("测试 6: 移动止损")
    print("="*60)
    
    manager = PositionManager(storage_file="data/test_positions.json")
    positions = manager.get_all_positions()
    
    if not positions:
        logger.warning("没有持仓可测试")
        return
    
    position = positions[0]
    
    # 模拟价格上涨过程
    logger.info(f"初始成本: ${position.avg_cost:.2f}")
    logger.info(f"初始止损: ${position.stop_loss_price:.2f if position.stop_loss_price else 'N/A'}")
    
    price_sequence = [2.5, 2.8, 3.0, 3.2, 3.0, 2.9, 2.7]
    trailing_pct = 10  # 10% 回撤
    
    for price in price_sequence:
        position.calculate_pnl(price)
        
        # 计算移动止损
        if position.unrealized_pnl > 0:  # 盈利才启用移动止损
            new_stop_loss = price * (1 - trailing_pct / 100)
            
            if position.stop_loss_price is None or new_stop_loss > position.stop_loss_price:
                old_stop = position.stop_loss_price
                position.adjust_stop_loss(new_stop_loss)
                logger.info(
                    f"价格 ${price:.2f} | "
                    f"止损 ${old_stop:.2f if old_stop else 'N/A'} → ${new_stop_loss:.2f}"
                )
            else:
                logger.info(f"价格 ${price:.2f} | 止损保持 ${position.stop_loss_price:.2f}")
    
    logger.info("✅ 移动止损测试完成")


def main():
    """主测试流程"""
    print("\n🚀 持仓管理和风险控制测试")
    print("="*60)
    
    try:
        # 测试 1: 创建持仓
        manager = test_position_creation()
        
        # 测试 2: 盈亏计算
        test_position_pnl_calculation(manager)
        
        # 测试 3: 止损止盈
        test_stop_loss_take_profit(manager)
        
        # 测试 4: 多持仓管理
        test_multiple_positions(manager)
        
        # 测试 5: 风险控制器
        test_risk_controller()
        
        # 测试 6: 移动止损
        test_trailing_stop()
        
        # 最终摘要
        print("\n" + "="*60)
        print("✅ 所有测试完成！")
        print("="*60)
        
        print("\n📊 最终持仓摘要:")
        manager.print_summary()
        
        print("\n📌 下一步:")
        print("1. 在 main.py 中集成持仓管理器")
        print("2. 启动风险控制器：risk_controller.start()")
        print("3. 启用移动止损：auto_trailing.start()")
        print("4. 监控持仓和自动止损止盈")
        print("="*60 + "\n")
        
    except Exception as e:
        logger.error(f"测试失败: {e}", exc_info=True)


if __name__ == "__main__":
    main()
