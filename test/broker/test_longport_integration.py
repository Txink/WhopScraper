#!/usr/bin/env python3
"""
长桥 OpenAPI 集成测试
演示如何在模拟账户和真实账户之间切换
"""
import logging
import sys
from broker import load_longport_config, LongPortBroker, convert_to_longport_symbol, calculate_quantity

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def test_config_loading():
    """测试配置加载"""
    print("\n" + "="*60)
    print("测试 1: 配置加载")
    print("="*60)
    
    try:
        config = load_longport_config()
        logger.info("✅ 配置加载成功")
        return config
    except Exception as e:
        logger.error(f"❌ 配置加载失败: {e}")
        return None


def test_account_info(broker: LongPortBroker):
    """测试获取账户信息"""
    print("\n" + "="*60)
    print("测试 2: 获取账户信息")
    print("="*60)
    
    try:
        balance = broker.get_account_balance()
        logger.info(f"账户模式: {balance.get('mode', 'unknown')}")
        logger.info(f"总资金: {balance.get('total_cash', 0):,.2f} {balance.get('currency', 'USD')}")
        logger.info(f"可用资金: {balance.get('available_cash', 0):,.2f} {balance.get('currency', 'USD')}")
        logger.info("✅ 账户信息获取成功")
        return balance
    except Exception as e:
        logger.error(f"❌ 获取账户信息失败: {e}")
        return None


def test_symbol_conversion():
    """测试期权代码转换"""
    print("\n" + "="*60)
    print("测试 3: 期权代码转换")
    print("="*60)
    
    test_cases = [
        ("AAPL", "CALL", 150.0, "1/31"),
        ("TSLA", "PUT", 250.0, "2/7"),
        ("NVDA", "CALL", 900.0, "本周"),
    ]
    
    for ticker, opt_type, strike, expiry in test_cases:
        symbol = convert_to_longport_symbol(ticker, opt_type, strike, expiry)
        logger.info(f"{ticker} {strike} {opt_type} {expiry} → {symbol}")
    
    logger.info("✅ 期权代码转换测试完成")


def test_quantity_calculation(available_cash: float):
    """测试数量计算"""
    print("\n" + "="*60)
    print("测试 4: 购买数量计算")
    print("="*60)
    
    price = 2.5
    position_sizes = ["小仓位", "中仓位", "大仓位"]
    
    for size in position_sizes:
        quantity = calculate_quantity(price, available_cash, size)
        cost = quantity * price * 100
        logger.info(f"{size}: {quantity} 张，成本 ${cost:,.2f}")
    
    logger.info("✅ 数量计算测试完成")


def test_dry_run_order(broker: LongPortBroker):
    """测试 Dry Run 模式下单"""
    print("\n" + "="*60)
    print("测试 5: Dry Run 模式下单")
    print("="*60)
    
    try:
        # 测试期权代码
        symbol = convert_to_longport_symbol("AAPL", "CALL", 150.0, "1/31")
        
        # 提交测试订单（dry run 模式不会真实下单）
        order = broker.submit_option_order(
            symbol=symbol,
            side="BUY",
            quantity=1,
            price=2.5,
            order_type="LIMIT",
            remark="Test order - Dry Run"
        )
        
        logger.info(f"订单 ID: {order['order_id']}")
        logger.info(f"订单状态: {order['status']}")
        logger.info(f"订单模式: {order['mode']}")
        logger.info("✅ Dry Run 模式下单测试完成")
        return order
    except Exception as e:
        logger.error(f"❌ 下单测试失败: {e}")
        return None


def test_get_orders(broker: LongPortBroker):
    """测试获取订单"""
    print("\n" + "="*60)
    print("测试 6: 获取当日订单")
    print("="*60)
    
    try:
        orders = broker.get_today_orders()
        logger.info(f"当日订单数: {len(orders)}")
        
        for order in orders[:5]:  # 只显示前5个
            logger.info(f"  订单: {order['symbol']} {order['side']} {order['quantity']} @ {order['price']}")
        
        logger.info("✅ 获取订单测试完成")
        return orders
    except Exception as e:
        logger.error(f"❌ 获取订单失败: {e}")
        return []


def test_get_positions(broker: LongPortBroker):
    """测试获取持仓"""
    print("\n" + "="*60)
    print("测试 7: 获取持仓信息")
    print("="*60)
    
    try:
        positions = broker.get_positions()
        logger.info(f"持仓数: {len(positions)}")
        
        for pos in positions[:5]:  # 只显示前5个
            logger.info(f"  持仓: {pos['symbol']} {pos['quantity']} @ {pos['cost_price']:.2f}")
        
        logger.info("✅ 获取持仓测试完成")
        return positions
    except Exception as e:
        logger.error(f"❌ 获取持仓失败: {e}")
        return []


def main():
    """主测试流程"""
    print("\n🚀 长桥 OpenAPI 集成测试")
    print("="*60)
    
    # 1. 加载配置
    config = test_config_loading()
    if not config:
        logger.error("配置加载失败，退出测试")
        sys.exit(1)
    
    # 2. 初始化 Broker
    try:
        broker = LongPortBroker(config)
        logger.info("Broker 初始化成功")
    except Exception as e:
        logger.error(f"Broker 初始化失败: {e}")
        sys.exit(1)
    
    # 3. 获取账户信息
    balance = test_account_info(broker)
    if not balance:
        logger.warning("无法获取账户信息，继续其他测试")
        available_cash = 10000  # 默认值用于测试
    else:
        available_cash = balance.get('available_cash', 10000)
    
    # 4. 测试期权代码转换
    test_symbol_conversion()
    
    # 5. 测试数量计算
    test_quantity_calculation(available_cash)
    
    # 6. 测试 Dry Run 下单
    test_dry_run_order(broker)
    
    # 7. 测试获取订单
    test_get_orders(broker)
    
    # 8. 测试获取持仓
    test_get_positions(broker)
    
    # 测试总结
    print("\n" + "="*60)
    print("✅ 所有测试完成！")
    print("="*60)
    print("\n📌 下一步:")
    print("1. 如果在模拟账户下测试，可以将 LONGPORT_AUTO_TRADE=true")
    print("2. 如果要切换到真实账户，请修改 .env 中的 LONGPORT_MODE=real")
    print("3. 开始实盘前，请确认关闭 LONGPORT_DRY_RUN=false")
    print("="*60 + "\n")


if __name__ == "__main__":
    main()
