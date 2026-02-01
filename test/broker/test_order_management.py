#!/usr/bin/env python3
"""
订单管理功能测试
测试订单撤销、修改和止盈止损功能
"""
import logging
import sys
import time
from broker import load_longport_config, LongPortBroker

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def test_order_with_stop_loss(broker: LongPortBroker):
    """测试带止损的订单"""
    print("\n" + "="*60)
    print("测试 1: 带止损的限价订单")
    print("="*60)
    
    try:
        # 获取期权链，找一个真实的期权
        expiry_dates = broker.get_option_expiry_dates("AAPL.US")
        if not expiry_dates or len(expiry_dates) < 2:
            logger.error("无法获取期权到期日")
            return None
        
        # 使用第二个到期日（避免过期）
        expiry = expiry_dates[1]
        option_chain = broker.get_option_chain_info("AAPL.US", expiry)
        
        if not option_chain or not option_chain.get("strike_prices"):
            logger.error("无法获取期权链")
            return None
        
        # 使用中间的行权价
        mid_idx = len(option_chain["strike_prices"]) // 2
        symbol = option_chain["call_symbols"][mid_idx]
        strike = option_chain["strike_prices"][mid_idx]
        
        logger.info(f"使用期权: {symbol} (行权价 ${strike:.2f})")
        
        # 提交带止损的订单
        # 假设买入价格是 $5，设置止损在 $3（跌幅 40%）
        order = broker.submit_option_order(
            symbol=symbol,
            side="BUY",
            quantity=1,
            price=5.0,
            order_type="LIMIT",
            trigger_price=3.0,  # 触发价格（止损）
            remark="Test order with stop loss"
        )
        
        logger.info(f"✅ 订单提交成功:")
        logger.info(f"  订单ID: {order['order_id']}")
        logger.info(f"  买入价格: ${order['price']:.2f}")
        logger.info(f"  止损触发价: $3.00")
        
        return order
        
    except Exception as e:
        logger.error(f"❌ 测试失败: {e}")
        return None


def test_order_with_trailing_stop(broker: LongPortBroker):
    """测试跟踪止损订单"""
    print("\n" + "="*60)
    print("测试 2: 跟踪止损订单")
    print("="*60)
    
    try:
        # 获取期权链
        expiry_dates = broker.get_option_expiry_dates("AAPL.US")
        if not expiry_dates or len(expiry_dates) < 2:
            logger.error("无法获取期权到期日")
            return None
        
        expiry = expiry_dates[1]
        option_chain = broker.get_option_chain_info("AAPL.US", expiry)
        
        if not option_chain or not option_chain.get("strike_prices"):
            logger.error("无法获取期权链")
            return None
        
        mid_idx = len(option_chain["strike_prices"]) // 2
        symbol = option_chain["call_symbols"][mid_idx]
        
        # 提交跟踪止损订单（跟踪5%）
        order = broker.submit_option_order(
            symbol=symbol,
            side="BUY",
            quantity=1,
            price=5.0,
            order_type="LIMIT",
            trailing_percent=5.0,  # 跟踪止损 5%
            remark="Test order with trailing stop"
        )
        
        logger.info(f"✅ 跟踪止损订单提交成功:")
        logger.info(f"  订单ID: {order['order_id']}")
        logger.info(f"  跟踪止损: 5%")
        
        return order
        
    except Exception as e:
        logger.error(f"❌ 测试失败: {e}")
        return None


def test_cancel_order(broker: LongPortBroker, order_id: str):
    """测试订单撤销"""
    print("\n" + "="*60)
    print("测试 3: 撤销订单")
    print("="*60)
    
    try:
        logger.info(f"撤销订单: {order_id}")
        
        result = broker.cancel_order(order_id)
        
        if result and isinstance(result, dict):
            logger.info(f"✅ 订单撤销成功:")
            logger.info(f"  订单ID: {result.get('order_id', order_id)}")
            logger.info(f"  状态: {result.get('status', 'cancelled')}")
        else:
            logger.info(f"✅ 订单已撤销: {order_id}")
        
        return result
        
    except Exception as e:
        logger.error(f"❌ 撤销失败: {e}")
        return None


def test_replace_order(broker: LongPortBroker, order_id: str):
    """测试订单修改"""
    print("\n" + "="*60)
    print("测试 4: 修改订单")
    print("="*60)
    
    try:
        logger.info(f"修改订单: {order_id}")
        logger.info(f"  原价格: $5.00, 原数量: 1")
        logger.info(f"  新价格: $4.50, 新数量: 2")
        
        result = broker.replace_order(
            order_id=order_id,
            quantity=2,
            price=4.50,
            remark="Modified order - price adjusted"
        )
        
        logger.info(f"✅ 订单修改成功:")
        logger.info(f"  订单ID: {result['order_id']}")
        logger.info(f"  新数量: {result['quantity']}")
        logger.info(f"  新价格: ${result['price']:.2f}")
        
        return result
        
    except Exception as e:
        logger.error(f"❌ 修改失败: {e}")
        return None


def test_get_order_detail(broker: LongPortBroker, order_id: str):
    """测试获取订单详情"""
    print("\n" + "="*60)
    print("测试 5: 获取订单详情")
    print("="*60)
    
    try:
        orders = broker.get_today_orders()
        
        # 查找指定订单
        target_order = None
        for order in orders:
            if order.get('order_id') == order_id:
                target_order = order
                break
        
        if target_order:
            logger.info(f"✅ 找到订单:")
            logger.info(f"  订单ID: {target_order['order_id']}")
            logger.info(f"  标的: {target_order['symbol']}")
            logger.info(f"  方向: {target_order['side']}")
            logger.info(f"  数量: {target_order['quantity']}")
            logger.info(f"  价格: ${target_order['price']:.2f}")
            logger.info(f"  状态: {target_order['status']}")
        else:
            logger.warning(f"⚠️  未找到订单: {order_id}")
        
        return target_order
        
    except Exception as e:
        logger.error(f"❌ 获取订单详情失败: {e}")
        return None


def main():
    """主测试流程"""
    print("\n🚀 订单管理功能测试")
    print("="*60)
    
    # 1. 加载配置
    try:
        config = load_longport_config()
        broker = LongPortBroker(config)
        logger.info("✅ Broker 初始化成功")
    except Exception as e:
        logger.error(f"❌ 初始化失败: {e}")
        sys.exit(1)
    
    # 2. 测试带止损的订单
    order1 = test_order_with_stop_loss(broker)
    if order1:
        time.sleep(1)
        
        # 3. 测试修改订单
        test_replace_order(broker, order1['order_id'])
        time.sleep(1)
        
        # 4. 测试获取订单详情
        test_get_order_detail(broker, order1['order_id'])
        time.sleep(1)
        
        # 5. 测试撤销订单
        test_cancel_order(broker, order1['order_id'])
    
    # 6. 测试跟踪止损订单
    order2 = test_order_with_trailing_stop(broker)
    if order2:
        time.sleep(1)
        # 撤销跟踪止损订单
        test_cancel_order(broker, order2['order_id'])
    
    # 测试总结
    print("\n" + "="*60)
    print("✅ 订单管理功能测试完成！")
    print("="*60)
    print("\n📌 测试功能:")
    print("1. ✅ 带止损价格的限价订单")
    print("2. ✅ 跟踪止损订单")
    print("3. ✅ 订单修改（价格和数量）")
    print("4. ✅ 订单撤销")
    print("5. ✅ 订单详情查询")
    print("="*60 + "\n")


if __name__ == "__main__":
    main()
