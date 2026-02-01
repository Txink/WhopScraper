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


def test_option_chain(broker: LongPortBroker):
    """测试期权链查询"""
    print("\n" + "="*60)
    print("测试 5: 期权链查询")
    print("="*60)
    
    try:
        symbol = "AAPL.US"
        
        # 1. 获取到期日列表
        expiry_dates = broker.get_option_expiry_dates(symbol)
        if not expiry_dates:
            logger.error("❌ 无法获取期权到期日")
            return None
        
        logger.info(f"找到 {len(expiry_dates)} 个到期日")
        logger.info(f"近期到期日: {expiry_dates[:5]}")
        
        # 2. 获取未过期的到期日的期权链（跳过可能已过期的第一个）
        # 今天是2月1日，使用索引1（第二个到期日）更安全
        expiry_idx = min(1, len(expiry_dates) - 1)
        nearest_expiry = expiry_dates[expiry_idx]
        logger.info(f"\n查询 {nearest_expiry} 到期日的期权链...")
        
        option_chain = broker.get_option_chain_info(symbol, nearest_expiry)
        if not option_chain or not option_chain.get("strike_prices"):
            logger.error("❌ 无法获取期权链信息")
            return None
        
        # 显示部分行权价
        strikes = option_chain["strike_prices"]
        logger.info(f"共有 {len(strikes)} 个行权价")
        logger.info(f"行权价范围: ${min(strikes):.2f} - ${max(strikes):.2f}")
        
        # 找到中间的几个行权价作为示例
        mid_idx = len(strikes) // 2
        sample_strikes = strikes[max(0, mid_idx-2):min(len(strikes), mid_idx+3)]
        logger.info(f"示例行权价: {[f'${s:.2f}' for s in sample_strikes]}")
        
        # 3. 获取部分期权报价
        sample_calls = option_chain["call_symbols"][max(0, mid_idx-2):min(len(strikes), mid_idx+3)]
        logger.info(f"\n查询 {len(sample_calls)} 个看涨期权报价...")
        
        quotes = broker.get_option_quote(sample_calls[:3])  # 只查询前3个
        for quote in quotes:
            logger.info(
                f"  {quote['symbol']}: "
                f"最新价 ${quote['last_done']:.2f}, "
                f"开盘 ${quote['open']:.2f}, "
                f"最高 ${quote['high']:.2f}, "
                f"最低 ${quote['low']:.2f}, "
                f"成交量 {quote['volume']}, "
                f"未平仓 {quote.get('open_interest', 0)}"
            )
        
        logger.info("✅ 期权链查询测试完成")
        return {
            "expiry_dates": expiry_dates,
            "nearest_expiry": nearest_expiry,
            "option_chain": option_chain
        }
    except Exception as e:
        logger.error(f"❌ 期权链查询失败: {e}")
        return None


def test_dry_run_order(broker: LongPortBroker, option_chain_result: dict = None):
    """测试 Dry Run 模式下单"""
    print("\n" + "="*60)
    print("测试 6: Dry Run 模式下单")
    print("="*60)
    
    try:
        # 如果有期权链查询结果，使用真实的期权代码
        if option_chain_result and option_chain_result.get("option_chain"):
            chain = option_chain_result["option_chain"]
            # 使用中间的行权价和对应的call期权代码
            mid_idx = len(chain["strike_prices"]) // 2
            symbol = chain["call_symbols"][mid_idx]
            strike = chain["strike_prices"][mid_idx]
            logger.info(f"使用期权链中的真实期权: {symbol} (行权价 ${strike:.2f})")
        else:
            # 否则使用手动转换（可能不存在）
            symbol = convert_to_longport_symbol("AAPL", "CALL", 250.0, "2026-02-07")
            logger.info(f"使用手动生成的期权代码: {symbol}")
        
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
    print("测试 7: 获取当日订单")
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
    print("测试 8: 获取持仓信息")
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
    
    # 6. 测试期权链查询（新增）
    option_chain_result = test_option_chain(broker)
    
    # 7. 测试 Dry Run 下单
    test_dry_run_order(broker, option_chain_result)
    
    # 8. 测试获取订单
    test_get_orders(broker)
    
    # 9. 测试获取持仓
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
